"""Administrator list projection; never constructs packing/detail snapshots."""

from datetime import date
from typing import Any

from sqlalchemy import Date, DateTime, Integer, String, bindparam, cast, func, select, text
from sqlalchemy.orm import Session

from app.db.natural_sort import natural_sort_keys

# Ordering follows _box_inputs: first occurrence in box number / item id order.
# Binary grouping preserves JavaScript Set semantics for case and accents.
SUMMARY_CTE = """
WITH visible AS (
 SELECT s.shipment_id, s.shipment_no, s.status, s.factory_id, s.business_date,
        s.submitted_at, COALESCE(NULLIF(f.factory_name, ''), s.factory_id) AS factory_name
 FROM shipments s LEFT JOIN factories f ON f.factory_id = s.factory_id
 WHERE s.status != 'DRAFT' AND s.deleted_at IS NULL AND s.source_shipment_id IS NULL
 AND (:all_factories = 1 OR COALESCE(NULLIF(f.factory_name, ''), s.factory_id)
      COLLATE utf8mb4_0900_bin IN :factories)
 AND (:date_from IS NULL OR COALESCE(s.business_date, '') >= :date_from)
 AND (:date_to IS NULL OR COALESCE(s.business_date, '') <= :date_to)
), packed AS (
 SELECT b.shipment_id, b.box_no, i.item_id, o.order_no,
        l.product_name_snapshot AS product_name,
        CASE WHEN r.status = 'CONFIRMED' THEN ri.quantity ELSE i.quantity END AS quantity,
        ROW_NUMBER() OVER (PARTITION BY b.shipment_id, o.order_no COLLATE utf8mb4_0900_bin
                          ORDER BY b.box_no, i.item_id) AS order_rank,
        ROW_NUMBER() OVER (
          PARTITION BY b.shipment_id, l.product_name_snapshot COLLATE utf8mb4_0900_bin
          ORDER BY b.box_no, i.item_id) AS product_rank
 FROM visible s JOIN shipment_boxes b ON b.shipment_id = s.shipment_id
 JOIN shipment_box_items i ON i.box_id = b.box_id
 JOIN order_assignments a ON a.order_assignment_id = i.order_assignment_id
 JOIN order_lines l ON l.order_line_id = a.order_line_id
 JOIN orders o ON o.order_id = l.order_id
 LEFT JOIN shipment_receipts r ON r.shipment_id = s.shipment_id
 LEFT JOIN shipment_receipt_items ri ON ri.box_item_id = i.item_id
), summaries AS (
 SELECT shipment_id,
 GROUP_CONCAT(CASE WHEN order_rank = 1 THEN order_no END
              ORDER BY box_no, item_id SEPARATOR '、') AS order_nos,
 GROUP_CONCAT(CASE WHEN product_rank = 1 THEN product_name END
              ORDER BY box_no, item_id SEPARATOR '、') AS product_names,
 SUM(quantity) AS total_quantity FROM packed GROUP BY shipment_id
), rows_to_filter AS (
 SELECT s.shipment_id, s.shipment_no, s.status, s.factory_id, s.factory_name,
 s.business_date, s.submitted_at, COALESCE(NULLIF(p.order_nos, ''), '—') AS order_nos,
 COALESCE(NULLIF(p.product_names, ''), '—') AS product_names,
 COALESCE(p.total_quantity, 0) AS total_quantity
 FROM visible s LEFT JOIN summaries p ON p.shipment_id = s.shipment_id
), filtered AS (
 SELECT * FROM rows_to_filter
 WHERE (:keyword = '' OR LOCATE(:keyword, LOWER(CONCAT(COALESCE(shipment_no, ''),
        ' ', order_nos)) COLLATE utf8mb4_0900_bin) > 0)
)
"""
# Query-local settings avoid GROUP_CONCAT's default 1024-byte truncation without
# leaking connection state to other requests. Same bounds as candidate summaries.
HINT = "/*+ SET_VAR(group_concat_max_len=4294967295) SET_VAR(max_sort_length=8388608) */"
SORT_FIELDS = {
    "shipmentNo": "shipment_no",
    "orderNos": "order_nos",
    "factory": "factory_name",
    "productNames": "product_names",
    "totalQuantity": "total_quantity",
    "businessDate": "business_date",
}


def page_shipments(
    session: Session,
    *,
    keyword: str = "",
    factory: str = "",
    factories: list[str] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort_by: str = "",
    sort_order: str = "asc",
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[dict[str, Any]], int]:
    selected_factories = list(
        dict.fromkeys(name for name in [factory, *(factories or [])] if name)
    )
    params = dict(
        keyword=keyword.strip().lower(),
        all_factories=not selected_factories,
        factories=selected_factories,
        date_from=date_from,
        date_to=date_to,
    )
    total = int(
        session.scalar(
            text(SUMMARY_CTE + f"SELECT {HINT} COUNT(*) FROM filtered").bindparams(
                bindparam("factories", expanding=True)
            ),
            params,
        ) or 0
    )
    if not total:
        return [], 0
    projection = (
        text(SUMMARY_CTE + "SELECT * FROM filtered")
        .bindparams(bindparam("factories", expanding=True))
        .columns(
            shipment_id=String,
            shipment_no=String,
            status=String,
            factory_id=String,
            factory_name=String,
            business_date=Date,
            submitted_at=DateTime,
            order_nos=String,
            product_names=String,
            total_quantity=Integer,
        )
        .cte("shipment_rows")
    )
    query = select(projection)
    if sort_by:
        field = projection.c[SORT_FIELDS[sort_by]]
        keys = natural_sort_keys(
            select(
                projection.c.shipment_id.label("id"),
                func.coalesce(cast(field, String), "").label("value"),
            ),
            name="shipment_sort",
        )
        query = query.join(keys, keys.c.id == projection.c.shipment_id)
        ordering = keys.c.sort_key.desc() if sort_order == "desc" else keys.c.sort_key.asc()
        query = query.order_by(ordering)
    else:
        query = query.order_by(projection.c.business_date.desc(), projection.c.shipment_no.desc())
    query = query.order_by(projection.c.submitted_at.desc(), projection.c.shipment_id)
    query = (
        query.limit(page_size)
        .offset((page - 1) * page_size)
        .prefix_with(
            "/*+ SET_VAR(group_concat_max_len=4294967295) "
            "SET_VAR(cte_max_recursion_depth=1000000) SET_VAR(max_sort_length=8388608) */"
        )
    )
    rows = session.execute(query, params).mappings()
    return [dict(row) for row in rows], total


def shipment_factories(session: Session) -> list[str]:
    return list(
        session.scalars(
            text("""
        SELECT DISTINCT COALESCE(NULLIF(f.factory_name, ''), s.factory_id)
          COLLATE utf8mb4_0900_bin AS name
        FROM shipments s LEFT JOIN factories f ON f.factory_id = s.factory_id
        WHERE s.status != 'DRAFT' AND s.deleted_at IS NULL AND s.source_shipment_id IS NULL
    """)
        )
    )
