import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import (
    DeliveryRequest,
    FeishuBusinessNotifier,
    NotificationDeliveryError,
    OpsAlert,
    OpsAlertNotifier,
    WechatNotifier,
)
from app.db.models import (
    Notification,
    NotificationAuthorization,
    Order,
    OrderAssignment,
    OrderLine,
    OutboxMessage,
    QuantityLedger,
    RepairOrder,
    RepairReturnBatch,
    Shipment,
    ShipmentLine,
    ShipmentVoidRequest,
    User,
)
from app.modules.infrastructure import utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationSnapshot:
    notification_id: int
    category: str
    event_type: str
    target_type: str
    target_id: str
    title: str
    summary: str
    target_path: str
    read_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class NotificationPage:
    items: list[NotificationSnapshot]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class AuditSnapshot:
    audit_id: int
    action: str
    target_type: str
    target_id: str
    changes: dict[str, Any]
    actor_id: str | None
    operator_name: str
    source_terminal: str | None
    created_at: datetime


@dataclass(frozen=True)
class AuditPage:
    items: list[AuditSnapshot]
    total: int
    page: int
    page_size: int


class NotificationsAuditService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record_authorizations(
        self,
        *,
        user_id: str,
        results: Mapping[str, str],
        authorized_at: datetime | None = None,
    ) -> None:
        current = authorized_at or utc_now()
        allowed_results = {"accepted", "rejected", "closed"}
        if not results or any(result not in allowed_results for result in results.values()):
            raise ValueError("invalid notification authorization result")
        with self._session_factory() as session, session.begin():
            user = session.get(User, user_id)
            if user is None or not user.is_enabled or user.role not in {"admin", "factory"}:
                raise ValueError("enabled mini program user required")
            allowed_keys = (
                {"admin_shipment", "admin_repair"}
                if user.role == "admin"
                else {"factory_order", "factory_repair"}
            )
            if not set(results).issubset(allowed_keys):
                raise ValueError("notification template is not allowed for role")
            session.add_all(
                NotificationAuthorization(
                    user_id=user_id,
                    template_key=template_key,
                    result=result,
                    authorized_at=current,
                )
                for template_key, result in sorted(results.items())
            )

    def consume_next_business_event(
        self, *, worker_id: str, now: datetime | None = None
    ) -> bool:
        current = now or utc_now()
        with self._session_factory() as session, session.begin():
            message = session.scalar(
                select(OutboxMessage)
                .where(
                    OutboxMessage.message_kind == "business_event",
                    OutboxMessage.status == "pending",
                    OutboxMessage.available_at <= current,
                )
                .order_by(OutboxMessage.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if message is None:
                return False
            message.status = "processing"
            message.locked_by = worker_id
            message.locked_at = current
            message.attempts += 1
            if message.event_type == "order_published":
                self._consume_order_published(session, message)
            elif message.event_type in {"order_withdrawn", "order_deleted"}:
                self._consume_order_unpublished(session, message)
            elif message.event_type == "shipment.submitted":
                self._consume_shipment_submitted(session, message)
            elif message.event_type == "shipment.void_requested":
                self._consume_void_requested(session, message)
            elif message.event_type in {"shipment.void_approved", "shipment.void_rejected"}:
                self._consume_void_result(session, message)
            elif message.event_type == "shipment.returned":
                self._consume_shipment_returned(session, message)
            elif message.event_type == "repair.created":
                self._consume_repair_created(session, message)
            elif message.event_type == "repair.return_submitted":
                self._consume_repair_returned(session, message)
            message.status = "completed"
            message.completed_at = current
            message.locked_by = None
            message.locked_at = None
            return True

    def deliver_next(
        self,
        *,
        worker_id: str,
        wechat_notifier: WechatNotifier,
        feishu_notifier: FeishuBusinessNotifier | None = None,
        ops_alert_notifier: OpsAlertNotifier | None = None,
        now: datetime | None = None,
    ) -> bool:
        current = now or utc_now()
        with self._session_factory() as session, session.begin():
            message = session.scalar(
                select(OutboxMessage)
                .where(
                    OutboxMessage.message_kind == "delivery",
                    OutboxMessage.status == "pending",
                    OutboxMessage.available_at <= current,
                )
                .order_by(OutboxMessage.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if message is None:
                return False
            recipient = session.get(User, message.recipient_id)
            if recipient is None or not recipient.is_enabled:
                message.status = "completed"
                message.completed_at = current
                message.last_error_code = "recipient_disabled"
                message.last_error_summary = "接收账号不存在或已停用，已跳过外部通知"
                return True
            message.status = "processing"
            message.locked_by = worker_id
            message.locked_at = current
            message.attempts += 1
            request = self._delivery_request(message)

        try:
            if request.channel == "wechat":
                wechat_notifier.send(request)
            elif request.channel == "feishu" and feishu_notifier is not None:
                feishu_notifier.send(request)
            else:
                raise NotificationDeliveryError(
                    "delivery_channel_not_configured",
                    retryable=False,
                    safe_summary="外部通知渠道未配置",
                )
        except Exception as raw_error:
            error = (
                raw_error
                if isinstance(raw_error, NotificationDeliveryError)
                else NotificationDeliveryError(
                    "unexpected_delivery_error",
                    retryable=True,
                    safe_summary="外部通知发送发生未预期错误",
                )
            )
            exhausted = False
            with self._session_factory() as session, session.begin():
                message = session.get(OutboxMessage, request.delivery_id)
                if message is not None and message.status == "processing":
                    message.last_error_code = error.code
                    message.last_error_summary = error.safe_summary[:500]
                    message.locked_by = None
                    message.locked_at = None
                    if error.retryable and message.attempts < 3:
                        message.status = "pending"
                        message.available_at = current + timedelta(
                            seconds=30 * (2 ** (message.attempts - 1))
                        )
                    else:
                        message.status = "manual_review"
                        message.failed_at = current
                        message.manual_review_required = True
                        message.alert_status = (
                            "pending" if ops_alert_notifier is not None else "not_configured"
                        )
                        message.alert_error_code = (
                            None if ops_alert_notifier is not None else "ops_alert_not_configured"
                        )
                        exhausted = True
            if exhausted and ops_alert_notifier is not None:
                alert = OpsAlert(
                    delivery_id=request.delivery_id,
                    channel=request.channel,
                    error_code=error.code,
                    error_summary=error.safe_summary,
                )
                try:
                    ops_alert_notifier.send(alert)
                except Exception as raw_alert_error:
                    alert_error = (
                        raw_alert_error
                        if isinstance(raw_alert_error, NotificationDeliveryError)
                        else NotificationDeliveryError(
                            "unexpected_ops_alert_error",
                            retryable=False,
                            safe_summary="运维告警发送发生未预期错误",
                        )
                    )
                    logger.warning(
                        "ops alert delivery failed delivery_id=%s error_code=%s",
                        request.delivery_id,
                        alert_error.code,
                    )
                    with self._session_factory() as session, session.begin():
                        message = session.get(OutboxMessage, request.delivery_id)
                        if message is not None:
                            message.alert_status = "failed"
                            message.alert_error_code = alert_error.code
                else:
                    with self._session_factory() as session, session.begin():
                        message = session.get(OutboxMessage, request.delivery_id)
                        if message is not None:
                            message.alert_status = "sent"
                            message.alert_error_code = None
            return True
        with self._session_factory() as session, session.begin():
            message = session.get(OutboxMessage, request.delivery_id)
            if message is not None and message.status == "processing":
                message.status = "completed"
                message.completed_at = current
                message.sent_at = current
                message.locked_by = None
                message.locked_at = None
        return True

    def recover_stale_outbox(self, *, before: datetime) -> int:
        with self._session_factory() as session, session.begin():
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(OutboxMessage)
                    .where(
                        OutboxMessage.status == "processing",
                        OutboxMessage.locked_at < before,
                    )
                    .values(
                        status="pending",
                        locked_by=None,
                        locked_at=None,
                        available_at=utc_now(),
                    )
                ),
            )
            return int(result.rowcount or 0)

    def scan_due_reminders(self, *, business_date: date) -> int:
        created = 0
        current = utc_now()
        with self._session_factory() as session, session.begin():
            orders = session.scalars(
                select(Order)
                .where(
                    Order.lifecycle == "PUBLISHED",
                    Order.deleted_at.is_(None),
                    Order.contract_ship_date.in_(
                        [
                            business_date + timedelta(days=10),
                            business_date + timedelta(days=5),
                            business_date + timedelta(days=3),
                            business_date,
                        ]
                    ),
                )
                .order_by(Order.order_id)
            ).all()
            for order in orders:
                days = (order.contract_ship_date - business_date).days
                node = "D0" if days == 0 else f"D-{days}"
                title = (
                    f"订单 {order.order_no} 今日到期"
                    if days == 0
                    else f"订单 {order.order_no} 距合同出货还有 {days} 天"
                )
                summary = f"合同出货时间为 {order.contract_ship_date.isoformat()}，请及时跟进"
                admin_users = list(
                    session.scalars(
                        select(User)
                        .where(
                            User.role == "admin",
                            User.is_enabled.is_(True),
                            User.feishu_display_name == order.tracker,
                        )
                        .order_by(User.user_id)
                    ).all()
                )
                if days == 3:
                    admin_users.extend(
                        session.scalars(
                            select(User)
                            .where(
                                User.role == "admin",
                                User.is_enabled.is_(True),
                                User.feishu_display_name.in_(["煎饼", "核桃"]),
                            )
                            .order_by(User.user_id)
                        ).all()
                    )
                seen_admins: set[str] = set()
                for user in admin_users:
                    if user.user_id in seen_admins:
                        continue
                    seen_admins.add(user.user_id)
                    dedupe_key = f"due:{order.order_id}:{node}"
                    if self._notification_exists(session, user.user_id, dedupe_key):
                        continue
                    session.add(
                        Notification(
                            recipient_id=user.user_id,
                            category="DUE_REMINDER",
                            event_type="order.due_reminder",
                            target_type="order",
                            target_id=order.order_id,
                            title=title,
                            summary=summary,
                            target_path=f"/orders/{order.order_id}",
                            dedupe_key=dedupe_key,
                            created_at=current,
                        )
                    )
                    self._add_delivery(
                        session,
                        event_type="order.due_reminder",
                        aggregate_type="order",
                        aggregate_id=order.order_id,
                        source_event_id=None,
                        recipient_id=user.user_id,
                        channel="feishu",
                        template_key="due_reminder",
                        title=title,
                        summary=summary,
                        target_type="order",
                        target_id=order.order_id,
                        target_path=f"/orders/{order.order_id}",
                        dedupe_key=f"delivery:due:{order.order_id}:{node}:{user.user_id}:feishu",
                        available_at=current,
                    )
                    created += 1

                shipped_by_assignment = (
                    select(
                        QuantityLedger.order_assignment_id.label("assignment_id"),
                        func.sum(QuantityLedger.quantity_delta).label("system_quantity"),
                    )
                    .group_by(QuantityLedger.order_assignment_id)
                    .subquery()
                )
                factory_ids = session.scalars(
                    select(OrderAssignment.factory_id)
                    .join(
                        OrderLine,
                        OrderLine.order_line_id == OrderAssignment.order_line_id,
                    )
                    .outerjoin(
                        shipped_by_assignment,
                        shipped_by_assignment.c.assignment_id
                        == OrderAssignment.order_assignment_id,
                    )
                    .where(OrderLine.order_id == order.order_id)
                    .group_by(OrderAssignment.factory_id)
                    .having(
                        func.sum(OrderAssignment.assigned_quantity)
                        > func.sum(
                            OrderAssignment.initial_shipped_quantity
                            + func.coalesce(shipped_by_assignment.c.system_quantity, 0)
                        )
                    )
                    .order_by(OrderAssignment.factory_id)
                ).all()
                factory_users = session.scalars(
                    select(User)
                    .where(
                        User.role == "factory",
                        User.is_enabled.is_(True),
                        User.factory_id.in_(factory_ids),
                    )
                    .order_by(User.user_id)
                ).all()
                for user in factory_users:
                    dedupe_key = f"due:{order.order_id}:{node}"
                    if self._notification_exists(session, user.user_id, dedupe_key):
                        continue
                    target_path = (
                        "/pages/factory-task-detail/factory-task-detail"
                        f"?orderId={order.order_id}"
                    )
                    session.add(
                        Notification(
                            recipient_id=user.user_id,
                            category="DUE_REMINDER",
                            event_type="order.due_reminder",
                            target_type="factory_task",
                            target_id=order.order_id,
                            title=title,
                            summary=summary,
                            target_path=target_path,
                            dedupe_key=dedupe_key,
                            created_at=current,
                        )
                    )
                    authorization = self._take_authorization(
                        session,
                        user_id=user.user_id,
                        template_key="factory_order",
                        consumed_at=current,
                    )
                    if authorization is not None:
                        self._add_delivery(
                            session,
                            event_type="order.due_reminder",
                            aggregate_type="order",
                            aggregate_id=order.order_id,
                            source_event_id=None,
                            recipient_id=user.user_id,
                            channel="wechat",
                            template_key="factory_order",
                            title=title,
                            summary=summary,
                            target_type="factory_task",
                            target_id=order.order_id,
                            target_path=target_path,
                            dedupe_key=(
                                f"delivery:due:{order.order_id}:{node}:{user.user_id}:wechat"
                            ),
                            available_at=current,
                        )
                    created += 1
        return created

    def list_notifications(
        self,
        *,
        user_id: str,
        unread_only: bool,
        page: int,
        page_size: int,
    ) -> NotificationPage:
        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        filters = [Notification.recipient_id == user_id]
        if unread_only:
            filters.append(Notification.read_at.is_(None))
        with self._session_factory() as session:
            total = int(
                session.scalar(select(func.count(Notification.notification_id)).where(*filters))
                or 0
            )
            rows = session.scalars(
                select(Notification)
                .where(*filters)
                .order_by(Notification.created_at.desc(), Notification.notification_id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return NotificationPage(
                items=[self._snapshot(item) for item in rows],
                total=total,
                page=page,
                page_size=page_size,
            )

    def unread_count(self, *, user_id: str) -> int:
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count(Notification.notification_id)).where(
                        Notification.recipient_id == user_id,
                        Notification.read_at.is_(None),
                    )
                )
                or 0
            )

    def mark_read(
        self, *, user_id: str, notification_id: int, read_at: datetime | None = None
    ) -> NotificationSnapshot:
        with self._session_factory() as session, session.begin():
            notification = session.scalar(
                select(Notification)
                .where(
                    Notification.notification_id == notification_id,
                    Notification.recipient_id == user_id,
                )
                .with_for_update()
            )
            if notification is None:
                raise KeyError(notification_id)
            if notification.read_at is None:
                notification.read_at = read_at or utc_now()
            session.flush()
            return self._snapshot(notification)

    def list_audit_logs(
        self,
        *,
        actor_user_id: str,
        target_type: str | None = None,
        target_id: str | None = None,
        filter_actor_id: str | None = None,
        source_terminal: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> AuditPage:
        from app.db.models import AuditLog

        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        with self._session_factory() as session:
            actor = session.get(User, actor_user_id)
            if actor is None or actor.role != "admin" or not actor.is_enabled:
                raise PermissionError("enabled administrator required")
            filters = []
            if target_type:
                filters.append(AuditLog.target_type == target_type)
            if target_id:
                filters.append(AuditLog.target_id == target_id)
            if filter_actor_id:
                filters.append(AuditLog.actor_id == filter_actor_id)
            if source_terminal:
                filters.append(AuditLog.source_terminal == source_terminal)
            if created_from:
                filters.append(AuditLog.created_at >= created_from)
            if created_to:
                filters.append(AuditLog.created_at <= created_to)
            total = int(session.scalar(select(func.count(AuditLog.id)).where(*filters)) or 0)
            rows = session.execute(
                select(AuditLog, User.feishu_display_name)
                .outerjoin(User, User.user_id == AuditLog.actor_id)
                .where(*filters)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
            return AuditPage(
                items=[
                    AuditSnapshot(
                        audit_id=log.id,
                        action=log.action,
                        target_type=log.target_type,
                        target_id=log.target_id,
                        changes=self._redact_changes(log.changes),
                        actor_id=log.actor_id,
                        operator_name=display_name or "系统",
                        source_terminal=log.source_terminal,
                        created_at=log.created_at,
                    )
                    for log, display_name in rows
                ],
                total=total,
                page=page,
                page_size=page_size,
            )

    @staticmethod
    def _consume_order_published(session: Session, message: OutboxMessage) -> None:
        factory_id = str(message.payload["factoryId"])
        order_id = str(message.payload["orderId"])
        order = session.get(Order, order_id)
        if order is None:
            return
        users = session.scalars(
            select(User)
            .where(
                User.role == "factory",
                User.factory_id == factory_id,
                User.is_enabled.is_(True),
            )
            .order_by(User.user_id)
        ).all()
        for user in users:
            dedupe_key = f"event:{message.dedupe_key}"
            existing = session.scalar(
                select(Notification.notification_id).where(
                    Notification.recipient_id == user.user_id,
                    Notification.dedupe_key == dedupe_key,
                )
            )
            if existing is not None:
                continue
            session.add(
                Notification(
                    recipient_id=user.user_id,
                    category="NEW_ORDER",
                    event_type=message.event_type,
                    target_type="factory_task",
                    target_id=order_id,
                    title="新订单任务",
                    summary=f"订单 {order.order_no} 已发布，请查看本厂任务",
                    target_path=f"/pages/factory-task-detail/factory-task-detail?orderId={order_id}",
                    dedupe_key=dedupe_key,
                )
            )
            authorization = NotificationsAuditService._take_authorization(
                session,
                user_id=user.user_id,
                template_key="factory_order",
                consumed_at=message.locked_at or utc_now(),
            )
            if authorization is None:
                continue
            delivery_dedupe = f"delivery:{message.dedupe_key}:{user.user_id}:wechat"
            existing_delivery = session.scalar(
                select(OutboxMessage.id).where(OutboxMessage.dedupe_key == delivery_dedupe)
            )
            if existing_delivery is None:
                session.add(
                    OutboxMessage(
                        event_type=message.event_type,
                        aggregate_type=message.aggregate_type,
                        aggregate_id=message.aggregate_id,
                        dedupe_key=delivery_dedupe,
                        payload={
                            "templateKey": "factory_order",
                            "title": "新订单任务",
                            "summary": f"订单 {order.order_no} 已发布，请查看本厂任务",
                            "targetType": "factory_task",
                            "targetId": order_id,
                            "targetPath": (
                                "/pages/factory-task-detail/factory-task-detail"
                                f"?orderId={order_id}"
                            ),
                        },
                        message_kind="delivery",
                        channel="wechat",
                        recipient_id=user.user_id,
                        source_event_id=message.id,
                        available_at=message.locked_at or utc_now(),
                    )
                )

    def _consume_order_unpublished(self, session: Session, message: OutboxMessage) -> None:
        order = session.get(Order, str(message.payload["orderId"]))
        if order is None:
            return
        title = "订单任务已撤回" if message.event_type == "order_withdrawn" else "订单任务已删除"
        for user in self._enabled_factory_users(session, str(message.payload["factoryId"])):
            self._notify_user(
                session,
                message=message,
                user_id=user.user_id,
                category="BUSINESS_RESULT",
                target_type="factory_task_list",
                target_id=order.order_id,
                title=title,
                summary=f"订单 {order.order_no} 已不再可执行，请返回任务列表查看",
                target_path="/pages/factory-tasks/factory-tasks",
                channel="wechat",
                template_key="factory_order",
            )

    def _consume_shipment_submitted(self, session: Session, message: OutboxMessage) -> None:
        shipment = session.get(Shipment, message.aggregate_id)
        if shipment is None:
            return
        for user in self._enabled_admins(session):
            self._notify_user(
                session,
                message=message,
                user_id=user.user_id,
                category="SHIPMENT",
                target_type="shipment",
                target_id=shipment.shipment_id,
                title="工厂已提交发货",
                summary=f"发货单 {shipment.shipment_no or shipment.shipment_id} 已形成正式记录",
                target_path=f"/shipments/{shipment.shipment_id}",
                delivery_target_path=(
                    "/pages/admin-shipment-detail/admin-shipment-detail"
                    f"?shipmentId={shipment.shipment_id}"
                ),
                channel="wechat",
                template_key="admin_shipment",
            )

    def _consume_void_requested(self, session: Session, message: OutboxMessage) -> None:
        shipment = session.get(Shipment, message.aggregate_id)
        if shipment is None:
            return
        for user in self._enabled_admins(session):
            self._notify_user(
                session,
                message=message,
                user_id=user.user_id,
                category="SHIPMENT",
                target_type="shipment",
                target_id=shipment.shipment_id,
                title="收到撤回发货申请",
                summary=f"发货单 {shipment.shipment_no or shipment.shipment_id} 等待审核",
                target_path=f"/shipments/{shipment.shipment_id}",
                channel=None,
                template_key=None,
            )

    def _consume_void_result(self, session: Session, message: OutboxMessage) -> None:
        request = session.get(ShipmentVoidRequest, str(message.payload["requestId"]))
        shipment = session.get(Shipment, message.aggregate_id)
        if request is None or shipment is None:
            return
        approved = message.event_type == "shipment.void_approved"
        self._notify_user(
            session,
            message=message,
            user_id=request.requested_by,
            category="BUSINESS_RESULT",
            target_type="shipment",
            target_id=shipment.shipment_id,
            title="撤回发货申请已通过" if approved else "撤回发货申请已拒绝",
            summary=f"发货单 {shipment.shipment_no or shipment.shipment_id} 的申请已处理",
            target_path=(
                "/pages/factory-shipment-detail/factory-shipment-detail"
                f"?shipmentId={shipment.shipment_id}"
            ),
            channel="wechat",
            template_key="factory_order",
        )

    def _consume_shipment_returned(self, session: Session, message: OutboxMessage) -> None:
        shipment = session.get(Shipment, message.aggregate_id)
        if shipment is None:
            return
        order_id = session.scalar(
            select(OrderLine.order_id)
            .join(OrderAssignment, OrderAssignment.order_line_id == OrderLine.order_line_id)
            .join(
                ShipmentLine,
                ShipmentLine.order_assignment_id == OrderAssignment.order_assignment_id,
            )
            .where(ShipmentLine.shipment_id == shipment.shipment_id)
            .order_by(OrderLine.order_id)
            .limit(1)
        )
        if order_id is None:
            return
        for user in self._enabled_factory_users(session, shipment.factory_id):
            self._notify_user(
                session,
                message=message,
                user_id=user.user_id,
                category="BUSINESS_RESULT",
                target_type="factory_task",
                target_id=order_id,
                title="发货退回已生效",
                summary="原订单未发数量已增加，请按普通发货流程补发",
                target_path=(
                    f"/pages/factory-task-detail/factory-task-detail?orderId={order_id}"
                ),
                channel="wechat",
                template_key="factory_order",
            )

    def _consume_repair_created(self, session: Session, message: OutboxMessage) -> None:
        repair = session.get(RepairOrder, message.aggregate_id)
        if repair is None:
            return
        for user in self._enabled_factory_users(session, repair.factory_id):
            self._notify_user(
                session,
                message=message,
                user_id=user.user_id,
                category="REPAIR",
                target_type="repair",
                target_id=repair.repair_id,
                title="新返修任务",
                summary=f"返修单 {repair.repair_no} 待处理 {repair.warehouse_return_quantity} 件",
                target_path=(
                    "/pages/factory-repair-detail/factory-repair-detail"
                    f"?repairId={repair.repair_id}"
                ),
                channel="wechat",
                template_key="factory_repair",
            )

    def _consume_repair_returned(self, session: Session, message: OutboxMessage) -> None:
        repair = session.get(RepairOrder, message.aggregate_id)
        if repair is None:
            return
        batch = session.get(RepairReturnBatch, str(message.payload["batchId"]))
        status_text = "，返修已完成" if repair.status == "COMPLETED" else ""
        for user in self._enabled_admins(session):
            self._notify_user(
                session,
                message=message,
                user_id=user.user_id,
                category="REPAIR",
                target_type="repair",
                target_id=repair.repair_id,
                title="工厂已提交返修结果",
                summary=(
                    f"返修单 {repair.repair_no} 已提交一批发回记录{status_text}"
                    if batch is not None
                    else f"返修单 {repair.repair_no} 已更新{status_text}"
                ),
                target_path=f"/repairs/{repair.repair_id}",
                delivery_target_path=(
                    "/pages/admin-repair-detail/admin-repair-detail"
                    f"?repairId={repair.repair_id}"
                ),
                channel="wechat",
                template_key="admin_repair",
            )

    @staticmethod
    def _enabled_admins(session: Session) -> list[User]:
        return list(
            session.scalars(
                select(User)
                .where(User.role == "admin", User.is_enabled.is_(True))
                .order_by(User.user_id)
            ).all()
        )

    @staticmethod
    def _enabled_factory_users(session: Session, factory_id: str) -> list[User]:
        return list(
            session.scalars(
                select(User)
                .where(
                    User.role == "factory",
                    User.factory_id == factory_id,
                    User.is_enabled.is_(True),
                )
                .order_by(User.user_id)
            ).all()
        )

    def _notify_user(
        self,
        session: Session,
        *,
        message: OutboxMessage,
        user_id: str,
        category: str,
        target_type: str,
        target_id: str,
        title: str,
        summary: str,
        target_path: str,
        delivery_target_path: str | None = None,
        channel: str | None,
        template_key: str | None,
    ) -> None:
        dedupe_key = f"event:{message.dedupe_key}"
        if self._notification_exists(session, user_id, dedupe_key):
            return
        session.add(
            Notification(
                recipient_id=user_id,
                category=category,
                event_type=message.event_type,
                target_type=target_type,
                target_id=target_id,
                title=title,
                summary=summary,
                target_path=target_path,
                dedupe_key=dedupe_key,
            )
        )
        if channel is None or template_key is None:
            return
        if channel == "wechat":
            authorization = self._take_authorization(
                session,
                user_id=user_id,
                template_key=template_key,
                consumed_at=message.locked_at or utc_now(),
            )
            if authorization is None:
                return
        self._add_delivery(
            session,
            event_type=message.event_type,
            aggregate_type=message.aggregate_type,
            aggregate_id=message.aggregate_id,
            source_event_id=message.id,
            recipient_id=user_id,
            channel=channel,
            template_key=template_key,
            title=title,
            summary=summary,
            target_type=target_type,
            target_id=target_id,
            target_path=delivery_target_path or target_path,
            dedupe_key=f"delivery:{message.dedupe_key}:{user_id}:{channel}",
            available_at=message.locked_at or utc_now(),
        )

    @staticmethod
    def _notification_exists(session: Session, recipient_id: str, dedupe_key: str) -> bool:
        return (
            session.scalar(
                select(Notification.notification_id).where(
                    Notification.recipient_id == recipient_id,
                    Notification.dedupe_key == dedupe_key,
                )
            )
            is not None
        )

    @staticmethod
    def _take_authorization(
        session: Session, *, user_id: str, template_key: str, consumed_at: datetime
    ) -> NotificationAuthorization | None:
        authorization = session.scalar(
            select(NotificationAuthorization)
            .where(
                NotificationAuthorization.user_id == user_id,
                NotificationAuthorization.template_key == template_key,
                NotificationAuthorization.result == "accepted",
                NotificationAuthorization.consumed_at.is_(None),
            )
            .order_by(NotificationAuthorization.authorization_id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if authorization is not None:
            authorization.consumed_at = consumed_at
        return authorization

    @staticmethod
    def _add_delivery(
        session: Session,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        source_event_id: int | None,
        recipient_id: str,
        channel: str,
        template_key: str,
        title: str,
        summary: str,
        target_type: str,
        target_id: str,
        target_path: str,
        dedupe_key: str,
        available_at: datetime,
    ) -> None:
        session.add(
            OutboxMessage(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                dedupe_key=dedupe_key,
                payload={
                    "templateKey": template_key,
                    "title": title,
                    "summary": summary,
                    "targetType": target_type,
                    "targetId": target_id,
                    "targetPath": target_path,
                },
                message_kind="delivery",
                channel=channel,
                recipient_id=recipient_id,
                source_event_id=source_event_id,
                available_at=available_at,
            )
        )

    @staticmethod
    def _snapshot(item: Notification) -> NotificationSnapshot:
        return NotificationSnapshot(
            notification_id=item.notification_id,
            category=item.category,
            event_type=item.event_type,
            target_type=item.target_type,
            target_id=item.target_id,
            title=item.title,
            summary=item.summary,
            target_path=item.target_path,
            read_at=item.read_at,
            created_at=item.created_at,
        )

    @staticmethod
    def _delivery_request(message: OutboxMessage) -> DeliveryRequest:
        if message.recipient_id is None or message.channel is None:
            raise ValueError("delivery recipient and channel are required")
        return DeliveryRequest(
            delivery_id=message.id,
            recipient_id=message.recipient_id,
            channel=message.channel,
            template_key=str(message.payload["templateKey"]),
            title=str(message.payload["title"]),
            summary=str(message.payload["summary"]),
            target_type=str(message.payload["targetType"]),
            target_id=str(message.payload["targetId"]),
            target_path=str(message.payload["targetPath"]),
        )

    @classmethod
    def _redact_changes(cls, value: dict[str, Any]) -> dict[str, Any]:
        sensitive = {
            "accesstoken",
            "refreshtoken",
            "authorization",
            "cookie",
            "password",
            "secret",
            "appsecret",
            "webhook",
            "devicecode",
        }
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = "".join(character for character in key.lower() if character.isalnum())
            if any(marker in normalized for marker in sensitive):
                continue
            if isinstance(item, dict):
                result[key] = cls._redact_changes(item)
            elif isinstance(item, list):
                result[key] = [
                    cls._redact_changes(element) if isinstance(element, dict) else element
                    for element in item
                ]
            else:
                result[key] = item
        return result
