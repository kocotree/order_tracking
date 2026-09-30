from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.errors import ExternalAdapterUnavailable
from app.adapters.order_source import FeishuOrderSource
from app.adapters.product import ProductSourceError
from app.db.models import (
    AuditLog,
    BackgroundJob,
    Order,
    OrderDetail,
    OrderImportCandidate,
    OrderImportRun,
)
from app.modules.order_import.service import ACTIVE_KEY, OrderImportService
from app.modules.orders import OrderConflict, OrderValidationError
from app.modules.orders.dispatch import OrderDispatchService
from app.modules.product_sync.service import ProductSyncService

JOB_TYPE = "order_auto_sync"
LOCK_NAME = "order_tracking_auto_sync"


class OrderAutoSync:
    def __init__(
        self, sessions: sessionmaker[Session], *, source: FeishuOrderSource,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        product_sync: ProductSyncService | None = None,
    ) -> None:
        self._sessions = sessions
        self._source = source
        self._clock = clock
        self._importer = OrderImportService(sessions, clock=clock, product_sync=product_sync)
        self._orders = OrderDispatchService(
            sessions, source=source, clock=clock, product_sync=product_sync,
        )

    def _now(self) -> datetime:
        return self._clock().replace(tzinfo=None)

    def ensure_due(self) -> str | None:
        # ponytail: 单来源全局连接锁；多租户需求出现时按来源分锁。
        with self._sessions() as guard:
            if guard.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": LOCK_NAME}) != 1:
                return None
            try:
                return self._schedule()
            finally:
                guard.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME})

    def _schedule(self) -> str | None:
        now = self._now()
        with self._sessions() as session, session.begin():
            active = session.scalar(select(OrderImportRun).where(
                OrderImportRun.active_key == ACTIVE_KEY
            ).with_for_update())
            if active is not None:
                if active.requested_by is None:
                    session.execute(update(BackgroundJob).where(
                        BackgroundJob.job_type == JOB_TYPE,
                        BackgroundJob.status == "running",
                        BackgroundJob.locked_at < now - timedelta(minutes=5),
                    ).values(status="pending", locked_at=None, locked_by=None))
                return active.run_id
            latest = session.scalar(select(OrderImportRun).where(
                OrderImportRun.requested_by.is_(None)
            ).order_by(OrderImportRun.started_at.desc()).limit(1))
            if latest is not None and now < latest.started_at + timedelta(minutes=20):
                return None
            run = OrderImportRun(
                run_id=str(uuid4()), status="PENDING", active_key=ACTIVE_KEY,
                requested_by=None, request_id=str(uuid4()), started_at=now, created_at=now,
                sync_result={"phase": "carry", "step": 0, "created_orders": 0,
                             "updated_orders": 0, "dispatched_groups": 0, "failed_orders": 0},
            )
            session.add(run)
            self._enqueue(session, run)
            return run.run_id

    def _enqueue(self, session: Session, run: OrderImportRun) -> None:
        now = self._now()
        session.add(BackgroundJob(
            job_type=JOB_TYPE, dedupe_key=f"{run.run_id}:{run.sync_result['step']}",
            payload={"runId": run.run_id}, status="pending",
            available_at=now + timedelta(seconds=1), created_at=now, updated_at=now,
        ))

    def run_step(self, payload: dict[str, Any]) -> bool:
        run_id = payload.get("runId")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("auto_sync_run_id_required")
        with self._sessions() as guard:
            if guard.scalar(text("SELECT GET_LOCK(:name, 0)"), {"name": LOCK_NAME}) != 1:
                raise RuntimeError("auto_sync_busy")
            try:
                return self._step(run_id)
            finally:
                guard.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": LOCK_NAME})

    def _step(self, run_id: str) -> bool:
        with self._sessions() as session:
            run = session.get(OrderImportRun, run_id)
            if run is None or run.requested_by is not None:
                raise ValueError("auto_sync_run_not_found")
            if run.active_key is None:
                return True
            state = dict(run.sync_result)
            request_id = run.request_id
        phase = state["phase"]
        target_id = run_id
        changes: dict[str, Any] = {"phase": phase}
        done = False
        try:
            if phase in {"carry", "create"}:
                with self._sessions() as session:
                    candidate_id = session.scalar(select(OrderImportCandidate.candidate_id).where(
                        OrderImportCandidate.status == "PENDING",
                        OrderImportCandidate.candidate_id > state.get("candidate_cursor", ""),
                    ).order_by(OrderImportCandidate.candidate_id).limit(1))
                if candidate_id is None:
                    state["phase"] = "discover" if phase == "carry" else "orders"
                    state.pop("candidate_cursor", None)
                else:
                    target_id = candidate_id
                    state["candidate_cursor"] = candidate_id
                    changes["orderId"] = self._importer.create_draft_automatically(
                        candidate_id=candidate_id, request_id=request_id
                    )
                    state["created_orders"] += 1
            elif phase == "discover":
                # 完整视图读取也能重试曾因采购失败或进度门槛跳过的新订单。
                groups: dict[str, list[str]] = {}
                pages = 0
                for page in self._source.read_pages(include_purchase=False):
                    for row in page:
                        groups.setdefault((row.order_no or "").strip().upper(), []).append(
                            row.record_id
                        )
                    pages += 1
                with self._sessions() as session:
                    existing = set(session.scalars(select(Order.order_no)))
                    existing.update(session.scalars(select(OrderImportCandidate.order_no)))
                state["new_sources"] = {
                    name: ids for name, ids in sorted(groups.items()) if name not in existing
                }
                state["discovery_pages"] = pages
                state["discovery_skipped_orders"] = len(groups) - len(state["new_sources"])
                state["phase"] = "discover_orders"
            elif phase == "discover_orders":
                groups = dict(state["new_sources"])
                if not groups:
                    state.pop("new_sources")
                    state["phase"] = "create"
                else:
                    target_id = next(iter(groups))
                    record_ids = groups.pop(target_id)
                    state["new_sources"] = groups
                    rows = self._source.read_records(record_ids)
                    if (
                        len(record_ids) != len(set(record_ids))
                        or len(rows) != len(record_ids)
                        or {row.record_id for row in rows} != set(record_ids)
                        or any((row.order_no or "").strip().upper() != target_id for row in rows)
                    ):
                        raise ValueError("发现的新订单来源集合已变化，本轮跳过")
                    self._importer.process_page(
                        run_id=run_id, rows=rows, page_number=state["discovery_pages"],
                        source_scope=self._source.source_scope,
                    )
            elif phase == "orders":
                with self._sessions() as session:
                    order_id = session.scalar(select(Order.order_id).where(
                        Order.source == "feishu", Order.deleted_at.is_(None),
                        Order.lifecycle.in_(["DRAFT", "PUBLISHED"]),
                        Order.order_id > state.get("order_cursor", ""),
                        select(OrderDetail.detail_id).where(
                            OrderDetail.order_id == Order.order_id,
                            OrderDetail.dispatch_state == "UNASSIGNED",
                        ).exists(),
                    ).order_by(Order.order_id).limit(1))
                if order_id is None:
                    done = True
                else:
                    target_id = order_id
                    state["order_cursor"] = order_id
                    self._orders.refresh_automatically(order_id=order_id, request_id=request_id)
                    state["updated_orders"] += 1
                    changes.update(self._orders.dispatch_automatically(
                        order_id=order_id, request_id=request_id
                    ))
                    state["dispatched_groups"] += changes["dispatched_groups"]
            else:
                raise ValueError("auto_sync_phase_invalid")
        except Exception as error:
            # 已确认的逐订单隔离边界；事务自行回滚，下一轮重新读取。
            if target_id == run_id and phase != "discover":
                raise
            state["failed_orders"] += 1
            changes["errorCode"] = type(error).__name__
            if isinstance(error, (ValueError, OrderConflict, OrderValidationError,
                                  ExternalAdapterUnavailable, ProductSourceError)):
                changes["reason"] = str(error)
            if phase == "discover":
                state["phase"] = "create"
        with self._sessions() as session, session.begin():
            run = session.get(OrderImportRun, run_id, with_for_update=True)
            if run is None:
                raise ValueError("auto_sync_run_not_found")
            session.add(AuditLog(
                request_id=request_id, action="order_sync.step", target_type="order_sync",
                target_id=target_id, changes={"runId": run_id, **changes},
                actor_id=None, source_terminal="system", created_at=self._now(),
            ))
            # 在释放执行锁前结束本步；进程此后退出也不会重复领取已完成步骤。
            session.execute(update(BackgroundJob).where(
                BackgroundJob.job_type == JOB_TYPE,
                BackgroundJob.dedupe_key == f"{run_id}:{state['step']}",
            ).values(status="completed", updated_at=self._now()))
            state["step"] += 1
            run.sync_result = dict(state)
            run.status = "SUCCEEDED" if done else "RUNNING"
            if done:
                for key, action in (
                    ("created_orders", "order.imported_from_feishu"),
                    ("updated_orders", "order.source_refreshed"),
                    ("unchanged_orders", "order.source_checked"),
                    ("dispatched_groups", "order.detail_dispatched"),
                ):
                    count = (
                        func.count(AuditLog.id) if key == "dispatched_groups"
                        else func.count(func.distinct(AuditLog.target_id))
                    )
                    state[key] = session.scalar(select(count).where(
                        AuditLog.request_id == request_id,
                        AuditLog.action == action, AuditLog.source_terminal == "system",
                    ))
                state["duration_seconds"] = (self._now() - run.started_at).total_seconds()
                state["results"] = [
                    {"targetId": audit.target_id, **audit.changes}
                    for audit in session.scalars(select(AuditLog).where(
                        AuditLog.request_id == request_id,
                        AuditLog.action == "order_sync.step",
                    ).order_by(AuditLog.id))
                    if "errorCode" in audit.changes or "blocked_factories" in audit.changes
                ]
                run.sync_result = state
                run.active_key = None
                run.finished_at = self._now()
            else:
                self._enqueue(session, run)
        return done

    def handle(self, payload: dict[str, Any]) -> None:
        self.run_step(payload)

    def fail(self, payload: dict[str, Any], error: Exception) -> None:
        self._importer.fail_run(run_id=payload["runId"], error_code=type(error).__name__)
