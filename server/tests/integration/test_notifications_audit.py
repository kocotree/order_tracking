from datetime import date, datetime, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import (
    DeliveryRequest,
    FakeFeishuBusinessNotifier,
    FakeOpsAlertNotifier,
    FakeWechatNotifier,
    NotificationDeliveryError,
)
from app.db.models import (
    Factory,
    Order,
    OrderAssignment,
    OutboxMessage,
    Product,
    ProductVariant,
    QuantityLedger,
    RepairOrder,
    RepairReturnBatch,
    RepairReturnLine,
    Shipment,
    ShipmentLine,
    StoredFile,
    User,
)
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.orders import AssignmentInput, DraftLineInput, OrderService


def _publish_order(test_database_engine: Engine, *, factory_user_ids: list[str]):
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with sessions() as session, session.begin():
        session.add(
            Factory(
                factory_id="factory-notice-a",
                supplier_number="S11A",
                factory_name="通知工厂甲",
                factory_code="S11A",
                is_enabled=True,
            )
        )
        session.flush()
        session.add(
            User(
                user_id="admin-notice",
                role="admin",
                is_enabled=True,
                feishu_display_name="松子",
            )
        )
        session.add_all(
            User(
                user_id=user_id,
                role="factory",
                is_enabled=True,
                feishu_display_name=f"工厂用户{index}",
                factory_id="factory-notice-a",
                factory_position="employee",
            )
            for index, user_id in enumerate(factory_user_ids, start=1)
        )
        session.add(
            Product(
                product_id="product-notice",
                source_i_id="ITEM-S11",
                name="通知测试童帽",
                is_available=True,
                source_modified_at=datetime(2026, 8, 27, 8, 0),
                first_synced_at=datetime(2026, 8, 27, 8, 0),
                last_synced_at=datetime(2026, 8, 27, 8, 0),
            )
        )
        session.add(
            ProductVariant(
                variant_id="variant-notice",
                product_id="product-notice",
                source_sku_id="SKU-S11",
                properties_value="蓝色 / 120",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=datetime(2026, 8, 27, 8, 0),
                first_synced_at=datetime(2026, 8, 27, 8, 0),
                last_synced_at=datetime(2026, 8, 27, 8, 0),
            )
        )

    order_service = OrderService(sessions)
    draft = order_service.create_draft(
        actor_id="admin-notice",
        order_no="S11-001",
        order_date=date(2026, 8, 27),
        tracker="松子",
        contract_ship_date=date(2026, 9, 10),
        lines=[
            DraftLineInput(
                variant_id="variant-notice",
                order_quantity=100,
                assignments=[AssignmentInput(factory_id="factory-notice-a", quantity=100)],
            )
        ],
        request_id="s11-create-order",
    )
    order_service.publish(
        actor_id="admin-notice",
        order_id=draft.order_id,
        version=draft.version,
        request_id="s11-publish-order",
        idempotency_key="s11-publish-order",
    )
    return sessions, order_service, draft


def test_published_order_creates_queryable_notification_for_factory_user(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )

    service = NotificationsAuditService(sessions)
    assert service.consume_next_business_event(worker_id="s11-worker") is True

    page = service.list_notifications(
        user_id="factory-notice-user", unread_only=False, page=1, page_size=10
    )
    assert page.total == 1
    assert page.items[0].category == "NEW_ORDER"
    assert page.items[0].title == "新订单任务"
    assert page.items[0].target_type == "factory_task"
    assert page.items[0].target_id == draft.order_id
    assert page.items[0].read_at is None


def test_repeated_publish_is_deduplicated_and_each_enabled_factory_user_is_notified(
    test_database_engine: Engine,
) -> None:
    sessions, order_service, draft = _publish_order(
        test_database_engine,
        factory_user_ids=["factory-notice-user", "factory-notice-user-2"],
    )
    replay = order_service.publish(
        actor_id="admin-notice",
        order_id=draft.order_id,
        version=draft.version,
        request_id="s11-publish-order-replay",
        idempotency_key="s11-publish-order",
    )
    assert replay.order_id == draft.order_id

    service = NotificationsAuditService(sessions)
    assert service.consume_next_business_event(worker_id="s11-worker") is True
    assert service.consume_next_business_event(worker_id="s11-worker") is False

    for user_id in ["factory-notice-user", "factory-notice-user-2"]:
        page = service.list_notifications(
            user_id=user_id, unread_only=False, page=1, page_size=10
        )
        assert page.total == 1

    with sessions() as session:
        assert session.query(OutboxMessage).filter_by(message_kind="business_event").count() == 1


def test_rejected_wechat_authorization_keeps_in_app_notification_without_delivery(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_status": "rejected"},
        authorized_at=datetime(2026, 8, 27, 9, 0),
    )
    assert service.consume_next_business_event(worker_id="s11-worker") is True

    page = service.list_notifications(
        user_id="factory-notice-user", unread_only=False, page=1, page_size=10
    )
    assert page.total == 1
    with sessions() as session:
        assert session.query(OutboxMessage).filter_by(message_kind="delivery").count() == 0


def test_authorization_rejects_template_keys_outside_current_mini_program_role(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    service = NotificationsAuditService(sessions)

    try:
        service.record_authorizations(
            user_id="factory-notice-user",
            results={"admin_shipment": "accepted"},
        )
    except ValueError as error:
        assert str(error) == "notification template is not allowed for role"
    else:
        raise AssertionError("factory user must not authorize administrator templates")


def test_submitted_shipment_uses_selected_supplier_shipment_template_fields(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    submitted_at = datetime(2026, 8, 27, 2, 15)
    with sessions() as session, session.begin():
        session.query(OutboxMessage).filter_by(message_kind="business_event").update(
            {"status": "completed"}
        )
        assignment = session.query(OrderAssignment).one()
        session.add(
            Shipment(
                shipment_id="shipment-notice",
                shipment_no="FH20260827-001",
                factory_id="factory-notice-a",
                status="SHIPPED",
                business_date=date(2026, 8, 27),
                created_by="factory-notice-user",
                submitted_by="factory-notice-user",
                submitted_at=submitted_at,
            )
        )
        session.flush()
        session.add(
            ShipmentLine(
                shipment_id="shipment-notice",
                order_assignment_id=assignment.order_assignment_id,
                quantity=12,
                order_no_snapshot="S11-001",
                sku_id_snapshot="SKU-S11",
                product_name_snapshot="通知测试童帽",
                properties_value_snapshot="蓝色 / 120",
            )
        )
        session.add(
            OutboxMessage(
                event_type="shipment.submitted",
                aggregate_type="shipment",
                aggregate_id="shipment-notice",
                dedupe_key="shipment:shipment-notice:submitted",
                payload={"shipmentId": "shipment-notice", "shipmentNo": "FH20260827-001"},
                status="pending",
                available_at=submitted_at,
            )
        )

    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="admin-notice",
        results={"admin_shipment": "accepted"},
        authorized_at=datetime(2026, 8, 27, 2, 0),
    )
    assert service.consume_next_business_event(
        worker_id="s11-shipment-event", now=submitted_at
    ) is True
    notifier = FakeWechatNotifier()
    assert service.deliver_next(
        worker_id="s11-shipment-delivery",
        wechat_notifier=notifier,
        now=submitted_at,
    ) is True
    assert notifier.sent[0].template_key == "admin_shipment"
    assert notifier.sent[0].template_data == {
        "character_string1": "FH20260827-001",
        "thing2": "通知工厂甲",
        "time3": "2026-08-27 10:15",
        "number7": "12",
        "thing4": "请查看发货单详情",
    }


def test_created_repair_uses_selected_product_repair_template_fields(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    created_at = datetime(2026, 8, 27, 3, 20)
    with sessions() as session, session.begin():
        session.query(OutboxMessage).filter_by(message_kind="business_event").update(
            {"status": "completed"}
        )
        stored_file = StoredFile(
            bucket="repair-test",
            object_key="repair-test/s11.xlsx",
            original_filename="s11.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=100,
            content_sha256="a" * 64,
            uploaded_by="admin-notice",
        )
        session.add(stored_file)
        session.flush()
        session.add(
            RepairOrder(
                repair_id="repair-notice",
                repair_no="FX20260827-001",
                factory_id="factory-notice-a",
                status="INCOMPLETE",
                warehouse_return_quantity=25,
                repaired_quantity=0,
                scrapped_quantity=0,
                returned_quantity=0,
                return_date=date(2026, 8, 27),
                original_file_id=stored_file.file_id,
                source_sha256="b" * 64,
                created_by="admin-notice",
            )
        )
        session.add(
            OutboxMessage(
                event_type="repair.created",
                aggregate_type="repair",
                aggregate_id="repair-notice",
                dedupe_key="repair:repair-notice:created",
                payload={"repairId": "repair-notice", "repairNo": "FX20260827-001"},
                status="pending",
                available_at=created_at,
            )
        )

    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_repair": "accepted"},
        authorized_at=datetime(2026, 8, 27, 3, 0),
    )
    assert service.consume_next_business_event(
        worker_id="s11-repair-event", now=created_at
    ) is True
    notifier = FakeWechatNotifier()
    assert service.deliver_next(
        worker_id="s11-repair-delivery",
        wechat_notifier=notifier,
        now=created_at,
    ) is True
    assert notifier.sent[0].template_key == "factory_repair"
    assert notifier.sent[0].template_data == {
        "thing6": "通知工厂甲",
        "thing2": "25",
        "time4": "2026-08-27 11:20",
        "thing5": "FX20260827-001待处理",
    }


def test_returned_repair_reuses_selected_product_repair_template_for_admin(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    submitted_at = datetime(2026, 8, 27, 6, 5)
    with sessions() as session, session.begin():
        session.query(OutboxMessage).filter_by(message_kind="business_event").update(
            {"status": "completed"}
        )
        stored_file = StoredFile(
            bucket="repair-return-test",
            object_key="repair-return-test/s11.xlsx",
            original_filename="s11.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=100,
            content_sha256="c" * 64,
            uploaded_by="admin-notice",
        )
        session.add(stored_file)
        session.flush()
        session.add(
            RepairOrder(
                repair_id="repair-return-notice",
                repair_no="FX20260827-002",
                factory_id="factory-notice-a",
                status="COMPLETED",
                warehouse_return_quantity=5,
                repaired_quantity=5,
                scrapped_quantity=0,
                returned_quantity=5,
                return_date=date(2026, 8, 27),
                original_file_id=stored_file.file_id,
                source_sha256="d" * 64,
                created_by="admin-notice",
            )
        )
        session.add(
            RepairReturnBatch(
                batch_id="repair-return-batch",
                repair_id="repair-return-notice",
                submitted_by="factory-notice-user",
                submitted_at=submitted_at,
                idempotency_key="s11-repair-return",
                request_sha256="e" * 64,
            )
        )
        session.flush()
        session.add(
            RepairReturnLine(
                batch_id="repair-return-batch",
                line_order=1,
                variant_id="variant-notice",
                repaired_quantity=5,
                scrapped_quantity=0,
            )
        )
        session.add(
            OutboxMessage(
                event_type="repair.return_submitted",
                aggregate_type="repair",
                aggregate_id="repair-return-notice",
                dedupe_key="repair:repair-return-notice:return:repair-return-batch",
                payload={
                    "repairId": "repair-return-notice",
                    "batchId": "repair-return-batch",
                },
                status="pending",
                available_at=submitted_at,
            )
        )

    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="admin-notice",
        results={"admin_repair": "accepted"},
        authorized_at=datetime(2026, 8, 27, 6, 0),
    )
    assert service.consume_next_business_event(
        worker_id="s11-repair-return-event", now=submitted_at
    ) is True
    notifier = FakeWechatNotifier()
    assert service.deliver_next(
        worker_id="s11-repair-return-delivery",
        wechat_notifier=notifier,
        now=submitted_at,
    ) is True
    assert notifier.sent[0].template_key == "admin_repair"
    assert notifier.sent[0].template_data == {
        "thing6": "通知工厂甲",
        "thing2": "5",
        "time4": "2026-08-27 14:05",
        "thing5": "FX20260827-002已完成",
    }


def test_accepted_wechat_authorization_creates_and_sends_one_user_delivery(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    with sessions() as session, session.begin():
        business_event = session.query(OutboxMessage).filter_by(
            message_kind="business_event"
        ).one()
        business_event.available_at = datetime(2026, 8, 27, 1, 30)
    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_status": "accepted"},
        authorized_at=datetime(2026, 8, 27, 1, 0),
    )
    assert service.consume_next_business_event(
        worker_id="s11-event-worker", now=datetime(2026, 8, 27, 1, 30)
    ) is True
    with sessions() as session:
        pending_delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        delivery_time = pending_delivery.available_at

    notifier = FakeWechatNotifier()
    assert service.deliver_next(
        worker_id="s11-delivery-worker",
        wechat_notifier=notifier,
        now=delivery_time,
    ) is True

    assert len(notifier.sent) == 1
    assert notifier.sent[0].recipient_id == "factory-notice-user"
    assert notifier.sent[0].template_key == "factory_status"
    assert notifier.sent[0].template_data == {
        "thing1": "跟单管理系统",
        "character_string2": "S11-001",
        "phrase3": "新订单",
        "time4": "2026-08-27 09:30",
    }
    assert notifier.sent[0].target_id == draft.order_id
    with sessions() as session:
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.status == "completed"


class RetryOnceWechatNotifier:
    def __init__(self) -> None:
        self.attempts = 0

    def send(self, _request: DeliveryRequest) -> None:
        self.attempts += 1
        if self.attempts == 1:
            raise NotificationDeliveryError(
                "wechat_timeout", retryable=True, safe_summary="微信接口响应超时"
            )


def test_retryable_wechat_failure_keeps_business_fact_and_resumes_after_worker_restart(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_status": "accepted"},
        authorized_at=datetime(2026, 8, 27, 9, 0),
    )
    assert service.consume_next_business_event(worker_id="s11-event-worker") is True
    with sessions() as session:
        first_available_at = (
            session.query(OutboxMessage).filter_by(message_kind="delivery").one().available_at
        )

    notifier = RetryOnceWechatNotifier()
    assert service.deliver_next(
        worker_id="delivery-worker-1",
        wechat_notifier=notifier,
        now=first_available_at,
    ) is True
    with sessions() as session:
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.status == "pending"
        assert delivery.last_error_code == "wechat_timeout"
        retry_at = delivery.available_at

    restarted_service = NotificationsAuditService(sessions)
    assert restarted_service.deliver_next(
        worker_id="delivery-worker-2",
        wechat_notifier=notifier,
        now=retry_at + timedelta(microseconds=1),
    ) is True
    assert notifier.attempts == 2
    with sessions() as session:
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.status == "completed"
        assert delivery.attempts == 2
    assert restarted_service.list_notifications(
        user_id="factory-notice-user", unread_only=False, page=1, page_size=10
    ).total == 1


class AlwaysFailWechatNotifier:
    def send(self, _request: DeliveryRequest) -> None:
        raise NotificationDeliveryError(
            "wechat_server_error", retryable=True, safe_summary="微信服务持续失败"
        )


class UnexpectedFailureWechatNotifier:
    def send(self, _request: DeliveryRequest) -> None:
        raise RuntimeError("provider response contains an unsafe internal detail")


class UnexpectedFailureOpsAlertNotifier:
    def send(self, _alert) -> None:
        raise RuntimeError("ops provider response contains an unsafe internal detail")


def test_retry_exhaustion_requires_manual_review_and_uses_independent_ops_alert(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_status": "accepted"},
        authorized_at=datetime(2026, 8, 27, 9, 0),
    )
    assert service.consume_next_business_event(worker_id="s11-event-worker") is True
    notifier = AlwaysFailWechatNotifier()
    alerts = FakeOpsAlertNotifier()

    for attempt in range(3):
        with sessions() as session:
            available_at = (
                session.query(OutboxMessage)
                .filter_by(message_kind="delivery")
                .one()
                .available_at
            )
        assert service.deliver_next(
            worker_id=f"delivery-worker-{attempt}",
            wechat_notifier=notifier,
            ops_alert_notifier=alerts,
            now=available_at,
        ) is True

    assert len(alerts.sent) == 1
    assert alerts.sent[0].channel == "wechat"
    assert alerts.sent[0].error_code == "wechat_server_error"
    with sessions() as session:
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.status == "manual_review"
        assert delivery.manual_review_required is True
        assert delivery.alert_status == "sent"


def test_disabled_recipient_is_skipped_without_external_send_or_ops_alert(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_status": "accepted"},
        authorized_at=datetime(2026, 8, 27, 9, 0),
    )
    assert service.consume_next_business_event(worker_id="s11-event-worker") is True
    with sessions() as session, session.begin():
        user = session.get(User, "factory-notice-user")
        assert user is not None
        user.is_enabled = False
        ready_at = (
            session.query(OutboxMessage)
            .filter_by(message_kind="delivery")
            .one()
            .available_at
        )

    notifier = FakeWechatNotifier()
    alerts = FakeOpsAlertNotifier()
    assert service.deliver_next(
        worker_id="delivery-worker",
        wechat_notifier=notifier,
        ops_alert_notifier=alerts,
        now=ready_at,
    ) is True

    assert notifier.sent == []
    assert alerts.sent == []
    with sessions() as session:
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.status == "completed"
        assert delivery.last_error_code == "recipient_disabled"


def test_unexpected_ops_alert_failure_keeps_manual_review_and_safe_failed_state(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_status": "accepted"},
        authorized_at=datetime(2026, 8, 27, 9, 0),
    )
    assert service.consume_next_business_event(worker_id="s11-event-worker") is True

    for attempt in range(3):
        with sessions() as session:
            ready_at = (
                session.query(OutboxMessage)
                .filter_by(message_kind="delivery")
                .one()
                .available_at
            )
        assert service.deliver_next(
            worker_id=f"delivery-worker-{attempt}",
            wechat_notifier=AlwaysFailWechatNotifier(),
            ops_alert_notifier=UnexpectedFailureOpsAlertNotifier(),
            now=ready_at,
        ) is True

    with sessions() as session:
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.status == "manual_review"
        assert delivery.manual_review_required is True
        assert delivery.alert_status == "failed"
        assert delivery.alert_error_code == "unexpected_ops_alert_error"


def test_unexpected_delivery_failure_is_safely_retried_and_stale_claim_is_recovered(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, _draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_status": "accepted"},
        authorized_at=datetime(2026, 8, 27, 9, 0),
    )
    assert service.consume_next_business_event(worker_id="s11-event-worker") is True
    with sessions() as session, session.begin():
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        ready_at = delivery.available_at

    assert service.deliver_next(
        worker_id="delivery-worker",
        wechat_notifier=UnexpectedFailureWechatNotifier(),
        now=ready_at,
    ) is True
    with sessions() as session, session.begin():
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.last_error_code == "unexpected_delivery_error"
        assert delivery.last_error_summary == "外部通知发送发生未预期错误"
        delivery.status = "processing"
        delivery.locked_by = "dead-worker"
        delivery.locked_at = datetime(2026, 8, 27, 8, 0)

    assert service.recover_stale_outbox(before=datetime(2026, 8, 27, 8, 5)) == 1
    with sessions() as session:
        delivery = session.query(OutboxMessage).filter_by(message_kind="delivery").one()
        assert delivery.status == "pending"
        assert delivery.locked_by is None
def test_d3_scan_notifies_tracker_factory_users_and_two_special_admins_once(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    with sessions() as session, session.begin():
        session.add_all(
            [
                User(
                    user_id="admin-pancake",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="煎饼",
                ),
                User(
                    user_id="admin-walnut",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="核桃",
                ),
                User(
                    user_id="factory-disabled",
                    role="factory",
                    is_enabled=False,
                    feishu_display_name="已停用工厂用户",
                    factory_id="factory-notice-a",
                    factory_position="employee",
                ),
            ]
        )

    service = NotificationsAuditService(sessions)
    service.record_authorizations(
        user_id="factory-notice-user",
        results={"factory_due": "accepted"},
        authorized_at=datetime(2026, 9, 7, 8, 50),
    )
    reminder_time = datetime(2026, 9, 7, 1, 0)
    assert service.scan_due_reminders(
        business_date=date(2026, 9, 7), now=reminder_time
    ) == 4
    assert service.scan_due_reminders(
        business_date=date(2026, 9, 7), now=reminder_time
    ) == 0

    for user_id in [
        "admin-notice",
        "factory-notice-user",
        "admin-pancake",
        "admin-walnut",
    ]:
        page = service.list_notifications(
            user_id=user_id, unread_only=False, page=1, page_size=10
        )
        assert page.total == 1
        assert page.items[0].category == "DUE_REMINDER"
        assert page.items[0].target_id == draft.order_id

    with sessions() as session:
        deliveries = session.query(OutboxMessage).filter_by(message_kind="delivery").all()
        assert sorted(item.channel for item in deliveries) == [
            "feishu",
            "feishu",
            "feishu",
            "wechat",
        ]

    wechat = FakeWechatNotifier()
    feishu = FakeFeishuBusinessNotifier()
    for index in range(4):
        assert service.deliver_next(
            worker_id=f"s11-due-delivery-{index}",
            wechat_notifier=wechat,
            feishu_notifier=feishu,
            now=reminder_time,
        ) is True
    assert service.deliver_next(
        worker_id="s11-due-delivery-empty",
        wechat_notifier=wechat,
        feishu_notifier=feishu,
        now=reminder_time,
    ) is False
    assert len(wechat.sent) == 1
    assert wechat.sent[0].template_key == "factory_due"
    assert wechat.sent[0].template_data == {
        "character_string1": "S11-001",
        "thing5": "合同出货时间2026-09-10",
        "short_thing6": "D-3",
        "time8": "2026-09-07 09:00",
    }

    assert service.list_notifications(
        user_id="factory-disabled", unread_only=False, page=1, page_size=10
    ).total == 0

    for business_date, contract_date in [
        (date(2026, 9, 1), date(2026, 9, 11)),
        (date(2026, 9, 2), date(2026, 9, 7)),
        (date(2026, 9, 3), date(2026, 9, 3)),
    ]:
        with sessions() as session, session.begin():
            order = session.get(Order, draft.order_id)
            assert order is not None
            order.contract_ship_date = contract_date
        assert service.scan_due_reminders(business_date=business_date) == 2
        assert service.scan_due_reminders(business_date=business_date) == 0

    with sessions() as session, session.begin():
        order = session.get(Order, draft.order_id)
        assert order is not None
        order.contract_ship_date = date(2026, 9, 2)
    assert service.scan_due_reminders(business_date=date(2026, 9, 3)) == 0


def test_due_scan_stops_and_restores_for_fully_shipped_factory_and_completed_order(
    test_database_engine: Engine,
) -> None:
    sessions, _order_service, draft = _publish_order(
        test_database_engine, factory_user_ids=["factory-notice-user"]
    )
    with sessions() as session, session.begin():
        assignment = session.query(OrderAssignment).one()
        session.add(
            QuantityLedger(
                order_assignment_id=assignment.order_assignment_id,
                source_type="shipment",
                source_id="s11-full-shipment",
                quantity_delta=100,
                actor_id="factory-notice-user",
                created_at=datetime(2026, 9, 7, 8, 0),
            )
        )

    service = NotificationsAuditService(sessions)
    assert service.scan_due_reminders(business_date=date(2026, 9, 7)) == 1
    assert service.list_notifications(
        user_id="factory-notice-user", unread_only=False, page=1, page_size=10
    ).total == 0

    with sessions() as session, session.begin():
        assignment = session.query(OrderAssignment).one()
        session.add(
            QuantityLedger(
                order_assignment_id=assignment.order_assignment_id,
                source_type="shipment_return",
                source_id="s11-returned-shipment",
                quantity_delta=-1,
                actor_id="admin-notice",
                created_at=datetime(2026, 9, 7, 9, 0),
            )
        )
    assert service.scan_due_reminders(business_date=date(2026, 9, 7)) == 1
    assert service.list_notifications(
        user_id="factory-notice-user", unread_only=False, page=1, page_size=10
    ).total == 1

    with sessions() as session, session.begin():
        order = session.get(Order, draft.order_id)
        assert order is not None
        order.lifecycle = "COMPLETED"
        order.contract_ship_date = date(2026, 9, 12)
    assert service.scan_due_reminders(business_date=date(2026, 9, 7)) == 0

    with sessions() as session, session.begin():
        order = session.get(Order, draft.order_id)
        assert order is not None
        order.lifecycle = "PUBLISHED"
    assert service.scan_due_reminders(business_date=date(2026, 9, 7)) == 2
