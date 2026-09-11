"""Order list expressions with optional factory scope; paginate before detailed snapshots."""

from datetime import date
from typing import Any

from sqlalchemy import Select, case, func, literal_column, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import Order, OrderAssignment, OrderLine, QuantityLedger


def display_status(today: date, factory_id: str | None = None) -> ColumnElement[str]:
    # Uncorrelated membership is materialized once; a correlated EXISTS may scan every
    # assignment for each order when MySQL chooses the date condition as its entry point.
    ledger = (
        select(
            QuantityLedger.order_assignment_id,
            func.sum(QuantityLedger.quantity_delta).label("quantity"),
        )
        .group_by(QuantityLedger.order_assignment_id)
        .subquery()
    )
    overdue_orders = (
        select(OrderLine.order_id)
        .join(OrderAssignment, OrderAssignment.order_line_id == OrderLine.order_line_id)
        .outerjoin(ledger, ledger.c.order_assignment_id == OrderAssignment.order_assignment_id)
        .where(
            OrderAssignment.is_active.is_(True),
            OrderAssignment.contract_ship_date < today,
            OrderAssignment.assigned_quantity
            > OrderAssignment.initial_shipped_quantity + func.coalesce(ledger.c.quantity, 0),
        )
    )
    if factory_id is not None:
        overdue_orders = overdue_orders.where(OrderAssignment.factory_id == factory_id)
    overdue = Order.order_id.in_(overdue_orders)
    return case(
        (Order.lifecycle == "DRAFT", "草稿"),
        (Order.lifecycle == "COMPLETED", "已完成"),
        (overdue, "已逾期"),
        else_="未完成",
    )


def page_orders(
    session: Session,
    query: Select[tuple[Order]],
    *,
    today: date,
    status: str,
    ship_date_from: date | None,
    ship_date_to: date | None,
    sort_by: str,
    page: int,
    page_size: int,
    factory_id: str | None = None,
) -> tuple[list[Order], int]:
    state = display_status(today, factory_id)
    visible_line = (
        (
            select(OrderAssignment.order_assignment_id)
            .where(
                OrderAssignment.order_line_id == OrderLine.order_line_id,
                OrderAssignment.factory_id == factory_id,
                OrderAssignment.is_active.is_(True),
            )
            .correlate(OrderLine)
            .exists()
        )
        if factory_id is not None
        else true()
    )
    if status != "all":
        query = query.where(state == status)
    dates = (
        select(OrderAssignment.contract_ship_date)
        .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
        .where(
            OrderLine.order_id == Order.order_id,
            OrderAssignment.is_active.is_(True),
        )
        .correlate(Order)
    )
    if factory_id is not None:
        dates = dates.where(OrderAssignment.factory_id == factory_id)
    if ship_date_from or ship_date_to:
        matching_dates = dates
        if ship_date_from:
            matching_dates = matching_dates.where(
                OrderAssignment.contract_ship_date >= ship_date_from
            )
        if ship_date_to:
            matching_dates = matching_dates.where(
                OrderAssignment.contract_ship_date <= ship_date_to
            )
        query = query.where(matching_dates.exists())
    first_date = dates.with_only_columns(
        func.min(OrderAssignment.contract_ship_date)
    ).scalar_subquery()
    last_date = dates.with_only_columns(
        func.max(OrderAssignment.contract_ship_date)
    ).scalar_subquery()

    def string_key(value: Any) -> ColumnElement[Any]:
        return func.coalesce(value, "").collate("utf8mb4_0900_bin")

    order_no = string_key(Order.order_no)
    normalized = sort_by.removesuffix("Asc").removesuffix("Desc")
    value: ColumnElement[Any]
    keys: list[ColumnElement[Any]]
    reverse = sort_by.endswith("Desc")
    if normalized == "orderNo":
        keys = [order_no]
    elif normalized == "productName":
        names = (
            select(
                func.group_concat(
                    literal_column(
                        "order_lines.product_name_snapshot ORDER BY "
                        "order_lines.order_line_id SEPARATOR '、'"
                    )
                )
            )
            .where(OrderLine.order_id == Order.order_id, visible_line)
            .correlate(Order)
            .scalar_subquery()
        )
        keys = [string_key(names), order_no]
    elif normalized == "category":
        clothes = (
            select(OrderLine.order_line_id)
            .where(
                OrderLine.order_id == Order.order_id,
                visible_line,
                OrderLine.category_snapshot.collate("utf8mb4_0900_bin").in_(
                    ["童装春夏", "童装秋冬"]
                ),
            )
            .correlate(Order)
            .exists()
        )
        hats = (
            select(OrderLine.order_line_id)
            .where(
                OrderLine.order_id == Order.order_id,
                visible_line,
                OrderLine.category_snapshot.collate("utf8mb4_0900_bin") != "",
                OrderLine.category_snapshot.collate("utf8mb4_0900_bin").not_in(
                    ["童装春夏", "童装秋冬"]
                ),
            )
            .correlate(Order)
            .exists()
        )
        label = case((clothes & hats, "服装、帽子"), (clothes, "服装"), (hats, "帽子"), else_="")
        keys = [string_key(label), order_no]
    elif normalized == "tracker":
        keys = [string_key(Order.tracker), order_no]
    elif normalized == "factory":
        # Snapshot chooses the final name for each factory in line/assignment ID order.
        ranked = (
            select(
                OrderLine.order_id.label("order_id"),
                OrderAssignment.factory_id.label("factory_id"),
                OrderAssignment.factory_name_snapshot.label("name"),
                func.row_number()
                .over(
                    partition_by=[
                        OrderLine.order_id,
                        OrderAssignment.factory_id.collate("utf8mb4_0900_bin"),
                    ],
                    order_by=[
                        OrderLine.order_line_id.desc(),
                        OrderAssignment.order_assignment_id.desc(),
                    ],
                )
                .label("position"),
            )
            .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
            .where(
                OrderAssignment.is_active.is_(True),
                OrderAssignment.factory_id == factory_id if factory_id is not None else true(),
            )
            .subquery("names")
        )
        names = (
            select(
                func.group_concat(
                    literal_column(
                        "names.name ORDER BY names.factory_id "
                        "COLLATE utf8mb4_0900_bin SEPARATOR '、'"
                    )
                )
            )
            .where(ranked.c.order_id == Order.order_id, ranked.c.position == 1)
            .correlate(Order)
            .scalar_subquery()
        )
        keys = [string_key(names), order_no]
    elif normalized in {"contractShipDate", "shipDate"}:
        value = last_date if reverse else first_date
        keys = [value.is_(None), value.desc() if reverse else value.asc(), order_no]
        reverse = False
    elif normalized in {"progressPercent", "shippedQuantity"}:
        ledger_totals = (
            select(
                QuantityLedger.order_assignment_id,
                func.sum(QuantityLedger.quantity_delta).label("quantity"),
            )
            .group_by(QuantityLedger.order_assignment_id)
            .subquery()
        )
        assignment_totals = (
            select(
                OrderLine.order_id,
                func.sum(
                    OrderAssignment.initial_shipped_quantity
                    + func.coalesce(ledger_totals.c.quantity, 0)
                ).label("shipped"),
                func.sum(OrderAssignment.assigned_quantity).label("assigned"),
            )
            .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
            .outerjoin(
                ledger_totals,
                ledger_totals.c.order_assignment_id == OrderAssignment.order_assignment_id,
            )
            .where(
                OrderAssignment.is_active.is_(True),
                OrderAssignment.factory_id == factory_id if factory_id is not None else true(),
            )
            .group_by(OrderLine.order_id)
            .subquery()
        )
        query = query.outerjoin(assignment_totals, assignment_totals.c.order_id == Order.order_id)
        shipped = func.coalesce(assignment_totals.c.shipped, 0)
        if normalized == "shippedQuantity":
            value = shipped
        else:
            line_totals = (
                select(OrderLine.order_id, func.sum(OrderLine.order_quantity).label("quantity"))
                .group_by(OrderLine.order_id)
                .subquery()
            )
            query = query.outerjoin(line_totals, line_totals.c.order_id == Order.order_id)
            denominator = func.nullif(
                assignment_totals.c.assigned if factory_id is not None else line_totals.c.quantity,
                0,
            )
            numerator = shipped * 100
            # Integer remainder avoids MySQL decimal division rounding a near-half into a tie.
            # Python round uses ties-to-even, including negative values.
            lower = numerator.op("DIV")(denominator) - case(
                (func.mod(numerator, denominator) < 0, 1), else_=0
            )
            twice_remainder = (numerator - lower * denominator) * 2
            value = func.coalesce(
                lower
                + case(
                    (twice_remainder > denominator, 1),
                    (twice_remainder == denominator, func.abs(func.mod(lower, 2))),
                    else_=0,
                ),
                0,
            )
        keys = [value, order_no]
    elif normalized == "status":
        keys = [string_key(state), order_no]
    elif sort_by == "orderDateDesc":
        keys = [Order.order_date.is_(None), Order.order_date.desc(), order_no]
        reverse = False
    elif sort_by == "updatedDesc":
        keys = [Order.updated_at.desc(), order_no]
        reverse = False
    else:
        keys = [
            case(
                (state == "已逾期", 0),
                (Order.lifecycle == "PUBLISHED", 1),
                (Order.lifecycle == "COMPLETED", 2),
                else_=3,
            ),
            func.coalesce(first_date, date.max),
            order_no,
        ]
        reverse = False
    if reverse:
        keys = [key.desc() for key in keys]
    total_count = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
    orders = list(
        session.scalars(
            query.prefix_with(
                "/*+ SET_VAR(group_concat_max_len=4294967295) SET_VAR(max_sort_length=8388608) */"
            )
            .order_by(*keys, Order.order_id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return orders, total_count
