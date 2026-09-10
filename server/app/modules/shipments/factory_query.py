"""Factory card projection: authorized summaries, then pagination; no detail snapshots."""

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.shipments.list_query import HINT

CTE = """
WITH visible AS (
 SELECT shipment_id, shipment_no, status, business_date, submitted_at
 FROM shipments
 WHERE factory_id = :factory_id AND status != 'DRAFT'
 AND deleted_at IS NULL AND source_shipment_id IS NULL
 AND (:date_from IS NULL OR COALESCE(business_date, '') >= :date_from)
 AND (:date_to IS NULL OR COALESCE(business_date, '') <= :date_to)
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
  ORDER BY box_no, item_id SEPARATOR '、') AS order_summary,
 GROUP_CONCAT(CASE WHEN product_rank = 1 THEN product_name END
  ORDER BY box_no, item_id SEPARATOR '、') AS product_names,
 SUM(CASE WHEN product_rank = 1 THEN 1 ELSE 0 END) AS product_count,
 SUM(quantity) AS total_quantity
 FROM packed GROUP BY shipment_id
), cards AS (
 SELECT s.*, COALESCE(p.order_summary, '') AS order_summary,
 COALESCE(p.product_names, '') AS product_names,
 CASE WHEN p.product_count > 1 THEN CONCAT(
  (SELECT product_name FROM packed x WHERE x.shipment_id = s.shipment_id
   ORDER BY box_no, item_id LIMIT 1), '等', p.product_count, '个产品')
 ELSE COALESCE(NULLIF(p.product_names, ''), '—') END AS product_summary,
 COALESCE(p.total_quantity, 0) AS total_quantity,
 (SELECT COUNT(*) FROM shipment_boxes b WHERE b.shipment_id = s.shipment_id) AS total_boxes
 FROM visible s LEFT JOIN summaries p ON p.shipment_id = s.shipment_id
), filtered AS (
 SELECT * FROM cards WHERE :keyword = '' OR
 LOCATE(:keyword, LOWER(CONCAT(product_summary, ' ', order_summary, ' ', product_names))
 COLLATE utf8mb4_0900_bin) > 0
)
"""


def page_factory_shipments(
    session: Session,
    *,
    factory_id: str,
    keyword: str = "",
    ship_date_from: date | None = None,
    ship_date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    params = dict(
        factory_id=factory_id,
        keyword=keyword.strip().lower(),
        date_from=ship_date_from,
        date_to=ship_date_to,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    total = int(session.scalar(text(CTE + f"SELECT {HINT} COUNT(*) FROM filtered"), params) or 0)
    if not total:
        return [], 0
    rows = session.execute(
        text(
            CTE
            + f"""SELECT {HINT}
      shipment_id, shipment_no, status, business_date, total_quantity, total_boxes,
      product_summary, order_summary FROM filtered
      ORDER BY submitted_at DESC, shipment_id LIMIT :limit OFFSET :offset"""
        ),
        params,
    ).mappings()
    return [dict(row) for row in rows], total
