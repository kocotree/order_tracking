import argparse
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, MetaData, Table, inspect, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuditLog,
    BackgroundJob,
    Order,
    OrderAssignment,
    OrderDetail,
    OrderLine,
    OutboxMessage,
    QuantityLedger,
    Shipment,
    ShipmentBox,
    ShipmentBoxItem,
    ShipmentLine,
    ShipmentReceipt,
    ShipmentReceiptItem,
    ShipmentReturnEvent,
    ShipmentReturnLine,
    ShipmentWritebackFact,
)
from app.db.session import create_database_engine
from app.modules.shipments.service import ShipmentService
from app.settings.config import Settings

OLD_EVENT = "shipment.receipt_confirmed"
UNCHANGED = (Order, OrderLine, OrderAssignment, OrderDetail, QuantityLedger, ShipmentBox,
             ShipmentBoxItem, ShipmentLine, ShipmentReturnEvent, ShipmentReturnLine,
             ShipmentWritebackFact)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def rows(session: Session, model: Any, *, old_schema: bool = False) -> list[dict[str, Any]]:
    table = Table(model.__tablename__, MetaData(), autoload_with=session.connection())
    columns = [column for column in table.columns
               if not (old_schema and column.name == "first_submitted_at")]
    return [dict(row) for row in session.execute(
        select(*columns).order_by(*table.primary_key.columns)
    ).mappings()]


def preview(session: Session, *, schema_ready: bool, now: datetime) -> dict[str, Any]:
    shipments = rows(session, Shipment, old_schema=not schema_ready)
    receipts = {row["shipment_id"]: row for row in rows(session, ShipmentReceipt)}
    receipt_items = rows(session, ShipmentReceiptItem)
    audits = rows(session, AuditLog)
    events = rows(session, OutboxMessage)
    jobs = rows(session, BackgroundJob)
    facts = rows(session, ShipmentWritebackFact)
    boxes = {row["box_id"]: row["shipment_id"] for row in rows(session, ShipmentBox)}
    originals = rows(session, ShipmentBoxItem)
    returns = {row["shipment_id"] for row in rows(session, ShipmentReturnEvent)}
    result: dict[str, Any] = {
        "schemaReady": schema_ready, "convert": [], "received": [], "returns": [],
        "excluded": [], "firstSubmittedAt": {}, "errors": [], "retire": [],
        "retryJobs": [], "applied": False,
    }
    current = now.astimezone(UTC).replace(tzinfo=None)
    for shipment in shipments:
        sid = shipment["shipment_id"]
        if shipment["source_shipment_id"] or shipment["submitted_at"] is None:
            if not shipment["source_shipment_id"] and shipment["status"] != "DRAFT":
                result["errors"].append({"shipmentId": sid, "reason": "first_submission_unproven"})
            result["excluded"].append(sid)
            continue
        related = [entry for entry in audits if (
            entry["target_type"] == "shipment" and entry["target_id"] == sid
        ) or entry["changes"].get("shipmentId") == sid]
        first = shipment.get("first_submitted_at")
        evidence = [entry["created_at"] for entry in related
                    if entry["action"] == "shipment_submitted"]
        evidence += [entry["submitted_at"] for entry in shipments
                     if entry["source_shipment_id"] == sid and entry["status"] == "SHIPPED"
                     and entry["submitted_at"] is not None]
        evidence += [entry["occurred_at"] for entry in facts
                     if entry["root_id"] == sid and entry["status"] == "SHIPPED"
                     and entry["event_key"] == f"submit:{sid}"]
        resubmitted = any(entry["action"] == "shipment_resubmitted" for entry in related)
        resubmitted = resubmitted or any(
            entry["source_shipment_id"] == sid and entry["submitted_at"] is not None
            for entry in shipments
        )
        if not resubmitted:
            evidence.append(shipment["submitted_at"])
        if first is None and evidence:
            first = min(evidence)
        if (first is None or first > shipment["submitted_at"]
                or (evidence and first != min(evidence))
                or shipment["submitted_at"] > current or any(at > current for at in evidence)):
            result["errors"].append({"shipmentId": sid, "reason": "first_submission_unproven"})
        else:
            result["firstSubmittedAt"][sid] = first.isoformat()
        if shipment["status"] != "SHIPPED" or shipment["deleted_at"] is not None:
            result["excluded"].append(sid)
            continue
        if sid in returns:
            result["returns"].append(sid)
        receipt = receipts.get(sid)
        if receipt and receipt["status"] == "CONFIRMED":
            result["received"].append(sid)
            continue
        original = {row["item_id"]: (row["order_assignment_id"], row["quantity"])
                    for row in originals if boxes[row["box_id"]] == sid}
        saved = {row["box_item_id"]: (
            row["order_assignment_id"] or original.get(row["box_item_id"], (None,))[0],
            row["quantity"],
        ) for row in receipt_items if row["shipment_id"] == sid}
        if not original or (saved and saved != original):
            result["errors"].append({"shipmentId": sid, "reason": "unapplied_receipt_draft"})
        result["convert"].append(sid)
    old_ids = {entry["id"] for entry in events if entry["event_type"] == OLD_EVENT}
    result["retire"] = [entry["id"] for entry in events if (
        entry["id"] in old_ids or entry["source_event_id"] in old_ids
    ) and entry["status"] != "completed" and entry["sent_at"] is None]
    # 当前重试由 Outbox 承担；旧版独立投递重试一并终结。
    result["retryJobs"] = [entry["id"] for entry in jobs
                           if entry["status"] != "completed"
                           and entry["payload"].get("deliveryId") in result["retire"]]
    result["invariantDigest"] = digest([rows(session, model) for model in UNCHANGED])
    result["digest"] = digest([result, shipments, list(receipts.values()), receipt_items,
                               events, jobs, audits])
    return result


def convert(
    engine: Engine, *, expected_digest: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    columns = {column["name"] for column in inspect(engine).get_columns("shipments")}
    schema_ready = "first_submitted_at" in columns
    with Session(engine) as session, session.begin():
        if expected_digest is not None:
            if not schema_ready:
                raise ValueError("auto_receipt_schema_required")
            session.execute(select(Shipment.shipment_id).order_by(
                Shipment.shipment_id,
            ).with_for_update()).all()
        report = preview(session, schema_ready=schema_ready, now=current)
        if expected_digest is None:
            return report
        if expected_digest != report["digest"]:
            raise ValueError("auto_receipt_preview_changed")
        if report["errors"]:
            raise ValueError("auto_receipt_precheck_failed")
        for sid, value in report["firstSubmittedAt"].items():
            shipment = session.get(Shipment, sid)
            assert shipment is not None
            if shipment.first_submitted_at is None:
                shipment.first_submitted_at = datetime.fromisoformat(value)
        for sid in report["convert"]:
            shipment = session.get(Shipment, sid)
            assert shipment is not None
            ShipmentService._auto_receive(session, shipment, current)
            session.add(AuditLog(
                request_id=f"auto-receipt:{sid}", action="shipment_receipt_converted",
                target_type="shipment", target_id=sid, actor_id=None,
                source_terminal="internal_cli", created_at=current,
                changes={"content": "历史发货单收货转换，数量保持不变"},
            ))
        for message_id in report["retire"]:
            message = session.get(OutboxMessage, message_id, with_for_update=True)
            assert message is not None
            message.status = "completed"
            message.completed_at = current
            message.locked_by = message.locked_at = None
            message.last_error_code = "receipt_notification_retired"
            message.last_error_summary = "收货通知已删除，终结旧事件"
        for job_id in report["retryJobs"]:
            job = session.get(BackgroundJob, job_id, with_for_update=True)
            assert job is not None
            job.status = "completed"
            job.locked_by = job.locked_at = None
            job.last_error = "receipt_notification_retired"
        session.flush()
        if digest([rows(session, model) for model in UNCHANGED]) != report["invariantDigest"]:
            raise ValueError("auto_receipt_quantity_or_fact_changed")
        report["applied"] = True
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="发货自动收货转换，默认只读预检")
    parser.add_argument("--apply", metavar="PREVIEW_DIGEST",
                        help="仅在获授权、停止旧 API/worker 并备份后，应用未变化的预检")
    args = parser.parse_args()
    engine = create_database_engine(Settings().database_url)
    try:
        report = convert(engine, expected_digest=args.apply)
        print(json.dumps(report, ensure_ascii=False))
        return 1 if report["errors"] else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
