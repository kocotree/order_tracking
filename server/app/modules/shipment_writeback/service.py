from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.shipment_writeback import FeishuShipmentWriter
from app.db.models import (
    AuditLog,
    BackgroundJob,
    OutboxMessage,
    Shipment,
    ShipmentWritebackClaim,
    ShipmentWritebackFact,
    ShipmentWritebackRow,
    ShipmentWritebackStage,
)
from app.modules.infrastructure import InfrastructureStore
from app.modules.shipment_writeback.facts import lock_facts, shipment_lines, utc_naive
from app.modules.shipment_writeback.periods import SHANGHAI, START, Stage, month_stages


class ShipmentWriteback:
    def __init__(self, sessions: sessionmaker[Session], *, source_scope: str,
                 target: FeishuShipmentWriter | None = None) -> None:
        self.sessions = sessions
        self.source_scope = source_scope
        self.target = target

    def ensure_due(self, *, now: datetime | None = None) -> list[int]:
        current = now or datetime.now(UTC)
        local = current.astimezone(SHANGHAI)
        store = InfrastructureStore(self.sessions)
        scheduled = []
        year, month = 2026, 10
        while (year, month) <= (local.year, local.month):
            label = f"{year:04}-{month:02}"
            scheduled.append(store.enqueue_job(
                job_type="shipment_writeback", dedupe_key=f"month:{label}",
                payload={"month": label}, available_at=utc_naive(current),
            ))
            for stage in month_stages(year, month):
                if utc_naive(current) >= utc_naive(stage.until):
                    scheduled.append(store.enqueue_job(
                        job_type="shipment_writeback", dedupe_key=f"stage:{stage.key}",
                        payload={"month": label, "stage": stage.key},
                        available_at=utc_naive(current),
                    ))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return scheduled

    def retry(self, job_id: int) -> None:
        with self.sessions() as session, session.begin():
            job = session.get(BackgroundJob, job_id, with_for_update=True)
            if job is None or job.job_type != "shipment_writeback" or job.status != "failed":
                raise ValueError("shipment_writeback_retry_requires_failed_job")
            job.status = "pending"
            job.attempts = 0
            job.available_at = utc_naive(datetime.now(UTC))
            job.locked_at = None
            job.locked_by = None

    def handle(self, payload: dict[str, Any]) -> None:
        self.run(payload)

    def _save_structure(self, value: dict[str, Any]) -> None:
        with self.sessions() as session, session.begin():
            control = lock_facts(session)
            control.structure = {**value, "source_scope": self.source_scope}

    def executions(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            return [dict(log.changes) for log in session.scalars(select(AuditLog).where(
                AuditLog.action == "shipment_writeback.execute",
            ).order_by(AuditLog.id))]

    def run(self, payload: dict[str, Any], *, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        month = datetime.strptime(payload["month"], "%Y-%m")
        stages = month_stages(month.year, month.month)
        stage = next((s for s in stages if s.key == payload.get("stage")), None)
        if "stage" in payload and stage is None:
            raise ValueError("shipment_writeback_invalid_stage")
        if current.astimezone(SHANGHAI).date() < stages[0].first.replace(day=1):
            raise ValueError("shipment_writeback_month_not_due")
        execution_id = str(uuid4())
        report: dict[str, Any] = {
            "execution_id": execution_id, "month": payload["month"],
            "stage": stage.key if stage else None, "status": "RUNNING",
            "started_at": datetime.now(UTC).isoformat(),
            "cutoff": stage.until.astimezone(SHANGHAI).isoformat() if stage else None,
        }
        with self.sessions() as session, session.begin():
            target_id = stage.key if stage else payload["month"]
            report["attempt"] = 1 + (session.scalar(select(func.count(AuditLog.id)).where(
                AuditLog.action == "shipment_writeback.execute", AuditLog.target_id == target_id,
            )) or 0)
            report["job_id"] = session.scalar(select(BackgroundJob.id).where(
                BackgroundJob.job_type == "shipment_writeback",
                BackgroundJob.dedupe_key == (f"stage:{stage.key}" if stage else
                                             f"month:{payload['month']}"),
            ))
            log = AuditLog(request_id=execution_id, action="shipment_writeback.execute",
                           target_type="shipment_writeback", target_id=target_id,
                           source_terminal="system", changes=report)
            session.add(log)
            session.flush()
            log_id = log.id
        try:
            with self.sessions() as guard:
                if guard.scalar(text("SELECT GET_LOCK('shipment_writeback_run', 0)")) != 1:
                    raise RuntimeError("shipment_writeback_busy")
                try:
                    with self.sessions() as session, session.begin():
                        for old in session.scalars(select(AuditLog).where(
                            AuditLog.action == "shipment_writeback.execute",
                            AuditLog.target_id == target_id, AuditLog.id < log_id,
                        )):
                            if old.changes.get("status") == "RUNNING":
                                old.changes = {**old.changes, "status": "INTERRUPTED",
                                               "finished_at": datetime.now(UTC).isoformat()}
                    if self.target is None:
                        raise ValueError("shipment_writeback_target_not_configured")
                    if stage is not None:
                        self.freeze(stage, now=current)
                    with self.sessions() as session, session.begin():
                        structure = dict(lock_facts(session).structure)
                    if structure.get("source_scope", self.source_scope) != self.source_scope:
                        raise ValueError("shipment_writeback_source_changed")
                    report["formula_before"] = structure.get(
                        "formula", self.target.baseline_formula,
                    )
                    structure = self.target.prepare_month(stages, structure, self._save_structure)
                    report["formula_after"] = structure.get("formula", self.target.baseline_formula)
                    report["field_count"] = len(structure["fields"])
                    if stage is not None:
                        for record_id, row in self.results(stage).items():
                            if row["verified"]:
                                continue
                            field_id = structure["fields"][stage.key]

                            def save_before(value: Any, record_id: str = record_id,
                                            field_id: str = field_id) -> None:
                                with self.sessions() as session, session.begin():
                                    saved = session.get(
                                        ShipmentWritebackRow, (stage.key, record_id),
                                        with_for_update=True,
                                    )
                                    if saved is None:
                                        raise ValueError("shipment_writeback_snapshot_missing")
                                    if saved.before_value is None:
                                        saved.before_value = {"value": value}
                                    saved.field_id = field_id

                            self.target.write_row(stage, field_id, record_id, row,
                                                  row["quantity"], save_before)
                            with self.sessions() as session, session.begin():
                                saved = session.get(ShipmentWritebackRow, (stage.key, record_id))
                                if saved is None:
                                    raise ValueError("shipment_writeback_snapshot_missing")
                                saved.verified = True
                    report["status"] = "SUCCEEDED"
                finally:
                    guard.execute(text("SELECT RELEASE_LOCK('shipment_writeback_run')"))
        except Exception as error:
            # 任务边界只记失败并重新抛出，重试保留原快照。
            report["status"] = "FAILED"
            report["error"] = (str(error) if isinstance(error, (ValueError, RuntimeError))
                               else type(error).__name__)
            raise
        finally:
            if stage is not None:
                rows = self.results(stage)
                report.update(rows=len(rows), verified=sum(r["verified"] for r in rows.values()),
                              quantity=sum(r["quantity"] for r in rows.values()))
                with self.sessions() as session:
                    frozen = session.get(ShipmentWritebackStage, stage.key)
                    report["excluded"] = frozen.excluded if frozen else {}
            report["finished_at"] = datetime.now(UTC).isoformat()
            with self.sessions() as session, session.begin():
                stored_log = session.get(AuditLog, log_id)
                if stored_log is None:
                    raise ValueError("shipment_writeback_log_missing")
                stored_log.changes = report

    def prepare_history(self) -> None:
        with self.sessions() as session, session.begin():
            control = lock_facts(session)
            if control.history_ready:
                return
            existing = set(session.scalars(select(ShipmentWritebackFact.event_key)))
            roots = session.scalars(select(Shipment).where(
                Shipment.source_shipment_id.is_(None), Shipment.submitted_at.is_not(None),
            )).all()
            for root in roots:
                if root.submitted_at and root.submitted_at < utc_naive(START):
                    continue
                messages = session.scalars(select(OutboxMessage).where(
                    OutboxMessage.aggregate_id == root.shipment_id,
                    OutboxMessage.message_kind == "business_event",
                    OutboxMessage.event_type.in_(["shipment.submitted", "shipment.withdrawn"]),
                ).order_by(OutboxMessage.id)).all()
                if not messages:
                    if root.submitted_at and root.submitted_at < utc_naive(START):
                        continue
                    raise ValueError(f"shipment_writeback_history_missing:{root.shipment_id}")
                withdrawals = session.scalar(select(func.count(AuditLog.id)).where(
                    AuditLog.action == "shipment_withdrawn", AuditLog.target_type == "shipment",
                    AuditLog.target_id == root.shipment_id,
                ))
                if withdrawals != sum(m.event_type == "shipment.withdrawn" for m in messages):
                    raise ValueError(f"shipment_writeback_history_missing:{root.shipment_id}")
                expected_times = set(session.scalars(select(Shipment.submitted_at).where(
                    or_(Shipment.shipment_id == root.shipment_id,
                        Shipment.source_shipment_id == root.shipment_id),
                    Shipment.submitted_at >= utc_naive(START),
                )))
                submitted_times = set()
                final_status = ""
                for message in messages:
                    fact_id = message.payload.get("factShipmentId", root.shipment_id)
                    formal = session.get(Shipment, fact_id)
                    if formal is None or formal.submitted_at is None:
                        raise ValueError(f"shipment_writeback_history_missing:{root.shipment_id}")
                    if message.event_type == "shipment.submitted":
                        at = formal.submitted_at
                        if at >= utc_naive(START):
                            submitted_times.add(at)
                        key = (f"submit:{root.shipment_id}"
                               if message.dedupe_key.endswith(":submitted")
                               else f"resubmit:{fact_id}")
                        final_status = "SHIPPED"
                    else:
                        at = utc_naive(datetime.fromisoformat(message.payload["occurredAt"]))
                        key = f"withdraw:{message.dedupe_key.split(':')[-1]}"
                        final_status = "WITHDRAWN"
                    if key not in existing and at >= utc_naive(START):
                        session.add(ShipmentWritebackFact(
                            root_id=root.shipment_id, event_key=key, status=final_status,
                            occurred_at=at, lines=shipment_lines(session, fact_id),
                        ))
                        existing.add(key)
                if submitted_times != expected_times:
                    raise ValueError(f"shipment_writeback_history_missing:{root.shipment_id}")
                if root.status != final_status or root.deleted_at is not None:
                    raise ValueError(
                        f"shipment_writeback_history_state_mismatch:{root.shipment_id}"
                    )
            control.history_ready = True

    def results(self, stage: Stage) -> dict[str, dict[str, Any]]:
        with self.sessions() as session:
            return {row.record_id: {**row.identity, "quantity": row.quantity,
                                    "verified": row.verified, "field_id": row.field_id}
                    for row in session.scalars(select(ShipmentWritebackRow)
                                               .where(ShipmentWritebackRow.stage_key == stage.key))}

    def freeze(self, stage: Stage, *, now: datetime) -> dict[str, dict[str, Any]]:
        stages = month_stages(stage.first.year, stage.first.month)
        if stage not in stages:
            raise ValueError("shipment_writeback_invalid_stage")
        if utc_naive(now) < utc_naive(stage.until):
            raise ValueError("shipment_writeback_not_due")
        self.prepare_history()
        with self.sessions() as session, session.begin():
            lock_facts(session)
            stored = session.get(ShipmentWritebackStage, stage.key)
            if stored is not None:
                if stored.source_scope != self.source_scope:
                    raise ValueError("shipment_writeback_source_changed")
            else:
                if stage.key != "2026-10-06":
                    index = stages.index(stage)
                    previous_month = stage.first.replace(day=1) - timedelta(days=1)
                    previous = (stages[index - 1] if index else
                                month_stages(previous_month.year, previous_month.month)[-1])
                    prior = session.get(ShipmentWritebackStage, previous.key)
                    if prior is None or prior.source_scope != self.source_scope:
                        raise ValueError("shipment_writeback_previous_stage_not_frozen")
                latest: dict[str, ShipmentWritebackFact] = {}
                submitted: dict[str, ShipmentWritebackFact] = {}
                for fact in session.scalars(select(ShipmentWritebackFact).where(
                    ShipmentWritebackFact.occurred_at >= utc_naive(START),
                    ShipmentWritebackFact.occurred_at < utc_naive(stage.until),
                ).order_by(ShipmentWritebackFact.occurred_at, ShipmentWritebackFact.id)):
                    latest[fact.root_id] = fact
                    if fact.status == "SHIPPED":
                        submitted[fact.root_id] = fact
                claimed = set(session.scalars(select(ShipmentWritebackClaim.root_id)))
                stored = ShipmentWritebackStage(
                    stage_key=stage.key, source_scope=self.source_scope,
                    since=utc_naive(stage.since), until=utc_naive(stage.until), excluded={},
                )
                session.add(stored)
                session.flush()
                rows: dict[str, ShipmentWritebackRow] = {}
                excluded: dict[str, Any] = {}
                for root, fact in latest.items():
                    if (root not in submitted or
                            submitted[root].occurred_at < utc_naive(stage.since)):
                        continue
                    if root in claimed:
                        excluded[root] = {"reason": "ALREADY_ASSIGNED", "quantity": sum(
                            line["quantity"] for line in fact.lines
                            if line["source_scope"] == self.source_scope
                        )}
                        continue
                    included = False
                    for line in fact.lines:
                        if line["source_scope"] not in (None, self.source_scope):
                            continue
                        if not line["record_id"] or not line["detail_id"]:
                            raise ValueError(
                                f"shipment_writeback_source_missing:{root}:{line['assignment_id']}"
                            )
                        record_id = line["record_id"]
                        identity = {key: line[key] for key in ("order_no", "detail_id")}
                        if record_id not in rows:
                            rows[record_id] = ShipmentWritebackRow(
                                stage_key=stage.key, record_id=record_id, identity=identity,
                                quantity=0, verified=False,
                            )
                        row = rows[record_id]
                        if row.identity != identity:
                            raise ValueError("shipment_writeback_source_ambiguous")
                        if fact.status == "SHIPPED":
                            row.quantity += line["quantity"]
                            included = True
                        else:
                            excluded.setdefault(root, {"reason": fact.status, "quantity": 0})
                            excluded[root]["quantity"] += line["quantity"]
                    if included:
                        session.add(ShipmentWritebackClaim(
                            root_id=root, stage_key=stage.key, fact_id=fact.id,
                        ))
                stored.excluded = excluded
                session.add_all(rows.values())
        return self.results(stage)
