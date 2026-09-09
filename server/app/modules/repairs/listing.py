"""Administrator list reads; detail/return workflows keep their existing contracts."""

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Factory, RepairOrder
from app.db.natural_sort import natural_sort_keys


class RepairListingService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def factories(self) -> list[str]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(Factory.factory_name)
                    .where(
                        select(RepairOrder.repair_id)
                        .where(
                            RepairOrder.factory_id == Factory.factory_id,
                            RepairOrder.archived_at.is_(None),
                        )
                        .exists()
                    )
                    .order_by(Factory.factory_name, Factory.factory_id)
                )
            )

    def page(
        self,
        *,
        keyword: str = "",
        status: str = "all",
        factories: list[str] | None = None,
        return_from: date | None = None,
        return_to: date | None = None,
        sort_by: str = "",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[dict[str, Any]], int]:
        # These quantities and status are maintained atomically by confirmation/returns.
        # Reading the same header as detail avoids joining inspection x return rows.
        fields = {
            "repairNo": RepairOrder.repair_no,
            "factoryName": Factory.factory_name,
            "repairedQuantity": RepairOrder.repaired_quantity,
            "scrappedQuantity": RepairOrder.scrapped_quantity,
            "returnedQuantity": RepairOrder.returned_quantity,
            "warehouseReturnQuantity": RepairOrder.warehouse_return_quantity,
            "returnDate": RepairOrder.return_date,
            "status": RepairOrder.status,
        }
        query = (
            select(
                RepairOrder.repair_id,
                RepairOrder.repair_no,
                RepairOrder.factory_id,
                Factory.factory_name,
                RepairOrder.status,
                RepairOrder.return_date,
                RepairOrder.warehouse_return_quantity,
                RepairOrder.repaired_quantity,
                RepairOrder.scrapped_quantity,
                RepairOrder.returned_quantity,
            )
            .join(Factory, Factory.factory_id == RepairOrder.factory_id)
            .where(RepairOrder.archived_at.is_(None))
        )
        if keyword.strip():
            query = query.where(
                func.lower(
                    func.concat(
                        RepairOrder.repair_no,
                        " ",
                        Factory.factory_name,
                    )
                )
                .collate("utf8mb4_0900_bin")
                .contains(keyword.strip().lower(), autoescape=True)
            )
        if status != "all":
            query = query.where(RepairOrder.status.collate("utf8mb4_0900_bin") == status)
        if factories:
            query = query.where(Factory.factory_name.collate("utf8mb4_0900_bin").in_(factories))
        if return_from:
            query = query.where(RepairOrder.return_date >= return_from)
        if return_to:
            query = query.where(RepairOrder.return_date <= return_to)
        count_query = select(func.count()).select_from(query.subquery())
        ordering: list[Any] = []
        if sort_by in fields:
            field = fields[sort_by]
            if sort_by in {"repairNo", "factoryName"}:
                keys = natural_sort_keys(
                    query.with_only_columns(
                        RepairOrder.repair_id.label("id"), field.label("value")
                    ),
                    name="repair_sort",
                )
                query = query.join(keys, keys.c.id == RepairOrder.repair_id)
                ordering.append(
                    keys.c.sort_key.desc() if sort_order == "desc" else keys.c.sort_key.asc()
                )
            else:
                ordering.append(field.desc() if sort_order == "desc" else field.asc())
        ordering.extend([RepairOrder.return_date.desc(), RepairOrder.repair_no.desc()])
        with self._session_factory() as session:
            total = session.scalar(count_query) or 0
            rows = session.execute(
                query.prefix_with(
                    "/*+ SET_VAR(cte_max_recursion_depth=1000000) "
                    "SET_VAR(max_sort_length=8388608) */"
                )
                .order_by(*ordering)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings()
            return [dict(row) for row in rows], total
