from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IncomingDiffRecord


def duplicate_evidence(
    session: Session, lines: list[dict[str, Any]]
) -> dict[int, list[dict[str, Any]]]:
    groups: dict[tuple[str, int], list[int]] = defaultdict(list)
    for line in lines:
        if line.get("detailId"):
            groups[(line["detailId"], line["quantity"])].append(line["number"])
    records = session.scalars(select(IncomingDiffRecord).where(
        IncomingDiffRecord.detail_id.in_({key[0] for key in groups})
    ).order_by(IncomingDiffRecord.record_id).with_for_update()).all()
    evidence: dict[int, list[dict[str, Any]]] = {}
    for (detail_id, quantity), numbers in groups.items():
        history = [{"recordId": record.record_id, "quantity": record.quantity,
                    "initialQuantity": record.initial_quantity,
                    "registeredAt": record.registered_at.isoformat(),
                    "sheetName": record.source_sheet_name, "rowNumber": record.source_row_number}
                   for record in records if record.detail_id == detail_id
                   and quantity in {record.quantity, record.initial_quantity}]
        for number in numbers:
            candidates = history + [{"number": other} for other in numbers if other != number]
            if candidates:
                evidence[number] = candidates
    return evidence
