from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    AuditLog,
    Factory,
    IdempotencyRecord,
    Order,
    OrderAssignment,
    OrderCompletionRecord,
    OutboxMessage,
    Product,
    ProductVariant,
    User,
)
from app.modules.orders import (
    AssignmentInput,
    DraftLineInput,
    OrderConflict,
    OrderNotFound,
    OrderPermissionDenied,
    OrderService,
    OrderValidationError,
)


class ConfigurableExecutionGuard:
    def __init__(self, *, shipments: bool = False, pending_void: bool = False) -> None:
        self.shipments = shipments
        self.pending_void = pending_void

    def has_valid_shipments(self, *, order_id: str) -> bool:
        return self.shipments

    def has_pending_void_requests(self, *, order_id: str) -> bool:
        return self.pending_void


def _clean_order_tables(engine: Engine) -> None:
    from app.db.models import OrderAssignment, OrderCompletionRecord, OrderLine

    with Session(engine) as session, session.begin():
        session.execute(delete(OrderCompletionRecord))
        session.execute(delete(OrderAssignment))
        session.execute(delete(OrderLine))
        session.execute(delete(Order))
        session.execute(delete(OutboxMessage))
        session.execute(delete(AuditLog))
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.scope.like("order.%")))
        session.execute(
            delete(ProductVariant).where(ProductVariant.variant_id == "variant-order-1")
        )
        session.execute(delete(Product).where(Product.product_id == "product-order-1"))
        session.execute(
            delete(User).where(
                User.user_id.in_(["admin-order-service", "factory-user-a", "factory-user-b"])
            )
        )
        session.execute(
            delete(Factory).where(Factory.factory_id.in_(["factory-order-a", "factory-order-b"]))
        )


def _seed_order_dependencies(engine: Engine) -> tuple[str, str, str, str]:
    with Session(engine) as session, session.begin():
        admin_id = "admin-order-service"
        factory_a_id = "factory-order-a"
        factory_b_id = "factory-order-b"
        variant_id = "variant-order-1"
        session.add_all(
            [
                Factory(
                    factory_id=factory_a_id,
                    supplier_number="S04A",
                    factory_name="工厂甲",
                    factory_code="S04A",
                    is_enabled=True,
                ),
                Factory(
                    factory_id=factory_b_id,
                    supplier_number="S04B",
                    factory_name="工厂乙",
                    factory_code="S04B",
                    is_enabled=True,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                User(
                    user_id=admin_id,
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="松子",
                ),
                User(
                    user_id="factory-user-a",
                    role="factory",
                    is_enabled=True,
                    feishu_display_name="甲工厂用户",
                    factory_id=factory_a_id,
                    factory_position="employee",
                ),
                User(
                    user_id="factory-user-b",
                    role="factory",
                    is_enabled=True,
                    feishu_display_name="乙工厂用户",
                    factory_id=factory_b_id,
                    factory_position="owner",
                ),
            ]
        )
        product = Product(
            product_id="product-order-1",
            source_i_id="ITEM-S04-1",
            name="测试童帽",
            is_available=True,
            source_modified_at=datetime(2026, 8, 21, 8, 0),
            first_synced_at=datetime(2026, 8, 21, 8, 0),
            last_synced_at=datetime(2026, 8, 21, 8, 0),
        )
        session.add(product)
        session.add(
            ProductVariant(
                variant_id=variant_id,
                product_id=product.product_id,
                source_sku_id="SKU-S04-1",
                properties_value="蓝色 / 120",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=datetime(2026, 8, 21, 8, 0),
                first_synced_at=datetime(2026, 8, 21, 8, 0),
                last_synced_at=datetime(2026, 8, 21, 8, 0),
            )
        )
    return admin_id, factory_a_id, factory_b_id, variant_id


@pytest.fixture(autouse=True)
def clean_order_test_data(test_database_engine: Engine):  # type: ignore[no-untyped-def]
    _clean_order_tables(test_database_engine)
    yield
    _clean_order_tables(test_database_engine)


def test_admin_creates_and_publishes_complete_multi_factory_draft(
    test_database_engine: Engine,
) -> None:
    admin_id, factory_a_id, factory_b_id, variant_id = _seed_order_dependencies(
        test_database_engine
    )
    service = OrderService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )

    draft = service.create_draft(
        actor_id=admin_id,
        order_no=" e81 ",
        order_date=date(2026, 8, 21),
        tracker="松子",
        contract_ship_date=date(2026, 8, 30),
        lines=[
            DraftLineInput(
                variant_id=variant_id,
                order_quantity=100,
                assignments=[
                    AssignmentInput(factory_id=factory_a_id, quantity=40),
                    AssignmentInput(factory_id=factory_b_id, quantity=60),
                ],
            )
        ],
        request_id="req-create-order",
    )

    assert draft.order_no == "E81"
    assert draft.lifecycle == "DRAFT"
    assert draft.version == 1
    assert draft.total_quantity == 100
    assert draft.shipped_quantity == 0

    published = service.publish(
        actor_id=admin_id,
        order_id=draft.order_id,
        version=draft.version,
        request_id="req-publish-order",
        idempotency_key="publish-e81-v1",
    )

    assert published.lifecycle == "PUBLISHED"
    assert published.display_status == "未完成"
    repeated = service.publish(
        actor_id=admin_id,
        order_id=draft.order_id,
        version=draft.version,
        request_id="req-publish-order-repeat",
        idempotency_key="publish-e81-v1",
    )
    assert repeated.order_id == published.order_id
    with Session(test_database_engine) as session:
        assert session.query(OutboxMessage).filter_by(event_type="order_published").count() == 2
        assert session.query(AuditLog).filter_by(action="order.published").count() == 1


def test_draft_edit_preserves_initial_shipped_baseline_and_rejects_lower_quantity(
    test_database_engine: Engine,
) -> None:
    _clean_order_tables(test_database_engine)
    admin_id, factory_a_id, _factory_b_id, variant_id = _seed_order_dependencies(
        test_database_engine
    )
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    service = OrderService(sessions)
    draft = service.create_draft(
        actor_id=admin_id,
        order_no="E-BASELINE",
        order_date=date(2026, 8, 21),
        tracker="松子",
        contract_ship_date=date(2026, 8, 30),
        lines=[DraftLineInput(variant_id, 100, [AssignmentInput(factory_a_id, 100)])],
        request_id="baseline-create",
    )
    with Session(test_database_engine) as session, session.begin():
        assignment = session.query(OrderAssignment).one()
        assignment.initial_shipped_quantity = 40
        session.get(Order, draft.order_id).order_date = None

    preserved = service.save_draft(
        actor_id=admin_id,
        order_id=draft.order_id,
        version=draft.version,
        order_no="E-BASELINE",
        order_date=None,
        tracker="松子",
        contract_ship_date=date(2026, 8, 30),
        lines=[DraftLineInput(variant_id, 100, [AssignmentInput(factory_a_id, 100)])],
        request_id="baseline-preserve",
    )
    assert preserved.shipped_quantity == 40
    assert preserved.pending_quantity == 60
    assert preserved.order_date is None

    with pytest.raises(OrderValidationError, match="initial shipped baseline"):
        service.save_draft(
            actor_id=admin_id,
            order_id=draft.order_id,
            version=preserved.version,
            order_no="E-BASELINE",
            order_date=None,
            tracker="松子",
            contract_ship_date=date(2026, 8, 30),
            lines=[DraftLineInput(variant_id, 30, [AssignmentInput(factory_a_id, 30)])],
            request_id="baseline-lower",
        )
    _clean_order_tables(test_database_engine)


def test_publish_validation_rolls_back_without_outbox_or_state_change(
    test_database_engine: Engine,
) -> None:
    admin_id, factory_a_id, _, variant_id = _seed_order_dependencies(test_database_engine)
    service = OrderService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )
    draft = service.create_draft(
        actor_id=admin_id,
        order_no="S04-INCOMPLETE",
        order_date=date(2026, 8, 21),
        tracker="松子",
        contract_ship_date=date(2026, 8, 30),
        lines=[
            DraftLineInput(
                variant_id,
                50,
                [AssignmentInput(factory_a_id, 20)],
            )
        ],
        request_id="req-incomplete-create",
    )
    with pytest.raises(OrderValidationError):
        service.publish(
            actor_id=admin_id,
            order_id=draft.order_id,
            version=draft.version,
            request_id="req-incomplete-publish",
            idempotency_key="incomplete-publish",
        )
    assert service.get(order_id=draft.order_id).lifecycle == "DRAFT"
    with Session(test_database_engine) as session:
        assert session.query(OutboxMessage).count() == 0
        assert session.query(AuditLog).filter_by(action="order.published").count() == 0


def test_draft_update_merges_duplicates_and_rejects_stale_version(
    test_database_engine: Engine,
) -> None:
    admin_id, factory_a_id, _, variant_id = _seed_order_dependencies(test_database_engine)
    service = OrderService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )
    draft = service.create_draft(
        actor_id=admin_id,
        order_no="S04-EDIT",
        order_date=date(2026, 8, 21),
        tracker="松子",
        contract_ship_date=date(2026, 8, 30),
        lines=[DraftLineInput(variant_id, 10, [])],
        request_id="req-create-edit",
    )

    updated = service.save_draft(
        actor_id=admin_id,
        order_id=draft.order_id,
        version=draft.version,
        order_no=" s04-edit ",
        order_date=date(2026, 8, 22),
        tracker="橄榄",
        contract_ship_date=date(2026, 9, 1),
        lines=[
            DraftLineInput(
                variant_id,
                20,
                [AssignmentInput(factory_a_id, 8)],
            ),
            DraftLineInput(
                variant_id,
                30,
                [AssignmentInput(factory_a_id, 12)],
            ),
        ],
        request_id="req-update-edit",
    )

    assert updated.version == 2
    assert updated.total_quantity == 50
    assert updated.lines[0].assignments[0].assigned_quantity == 20
    assert updated.validation_issues == ["产品 测试童帽 的派工合计必须等于订单数量"]
    with pytest.raises(OrderConflict):
        service.save_draft(
            actor_id=admin_id,
            order_id=draft.order_id,
            version=draft.version,
            order_no="S04-EDIT",
            order_date=date(2026, 8, 22),
            tracker="橄榄",
            contract_ship_date=date(2026, 9, 1),
            lines=[DraftLineInput(variant_id, 50, [])],
            request_id="req-stale-edit",
        )


def test_withdraw_complete_reopen_delete_and_factory_visibility(
    test_database_engine: Engine,
) -> None:
    admin_id, factory_a_id, factory_b_id, variant_id = _seed_order_dependencies(
        test_database_engine
    )
    service = OrderService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: datetime(2026, 9, 2, 8, 0),
    )
    draft = service.create_draft(
        actor_id=admin_id,
        order_no="S04-LIFE",
        order_date=date(2026, 8, 21),
        tracker="松子",
        contract_ship_date=date(2026, 9, 1),
        lines=[
            DraftLineInput(
                variant_id,
                100,
                [
                    AssignmentInput(factory_a_id, 40),
                    AssignmentInput(factory_b_id, 60),
                ],
            )
        ],
        request_id="req-life-create",
    )
    with pytest.raises(OrderNotFound):
        service.get_visible(actor_id="factory-user-a", order_id=draft.order_id)
    published = service.publish(
        actor_id=admin_id,
        order_id=draft.order_id,
        version=draft.version,
        request_id="req-life-publish",
        idempotency_key="life-publish",
    )
    assert published.display_status == "已逾期"
    factory_view = service.get_visible(actor_id="factory-user-a", order_id=draft.order_id)
    assert factory_view.total_quantity == 40
    assert [item.factory_id for item in factory_view.factory_progress] == [factory_a_id]
    assert factory_b_id not in repr(factory_view)

    completed = service.complete(
        actor_id=admin_id,
        order_id=draft.order_id,
        request_id="req-life-complete",
        idempotency_key="life-complete",
    )
    assert completed.display_status == "已完成"
    with pytest.raises(OrderValidationError):
        service.reopen(
            actor_id=admin_id,
            order_id=draft.order_id,
            reason=" ",
            request_id="req-life-reopen-empty",
            idempotency_key="life-reopen-empty",
        )
    reopened = service.reopen(
        actor_id=admin_id,
        order_id=draft.order_id,
        reason="补充核对",
        request_id="req-life-reopen",
        idempotency_key="life-reopen",
    )
    assert reopened.display_status == "已逾期"
    with Session(test_database_engine) as session:
        records = session.query(OrderCompletionRecord).order_by(OrderCompletionRecord.record_id)
        assert [item.action for item in records] == ["COMPLETE", "REOPEN"]

    withdrawn = service.withdraw(
        actor_id=admin_id,
        order_id=draft.order_id,
        request_id="req-life-withdraw",
        idempotency_key="life-withdraw",
    )
    assert withdrawn.lifecycle == "DRAFT"
    with pytest.raises(OrderNotFound):
        service.get_visible(actor_id="factory-user-b", order_id=draft.order_id)
    service.delete(
        actor_id=admin_id,
        order_id=draft.order_id,
        request_id="req-life-delete",
        idempotency_key="life-delete",
    )
    with pytest.raises(OrderNotFound):
        service.get(order_id=draft.order_id)

    with pytest.raises(OrderPermissionDenied):
        service.create_draft(
            actor_id="factory-user-a",
            order_no="NO-PERMISSION",
            order_date=date(2026, 8, 21),
            tracker="松子",
            contract_ship_date=date(2026, 8, 30),
            lines=[DraftLineInput(variant_id, 1, [])],
            request_id="req-no-permission",
        )


def test_display_status_uses_east_eight_business_date(
    test_database_engine: Engine,
) -> None:
    admin_id, _, _, variant_id = _seed_order_dependencies(test_database_engine)
    service = OrderService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: datetime(2026, 8, 21, 16, 30, tzinfo=UTC),
    )
    draft = service.create_draft(
        actor_id=admin_id,
        order_no="S04-TIMEZONE",
        order_date=date(2026, 8, 21),
        tracker="松子",
        contract_ship_date=date(2026, 8, 21),
        lines=[DraftLineInput(variant_id, 1, [])],
        request_id="req-timezone",
    )
    assert draft.display_status == "草稿"
    with Session(test_database_engine) as session, session.begin():
        order = session.get(Order, draft.order_id)
        assert order is not None
        order.lifecycle = "PUBLISHED"
    assert service.get(order_id=draft.order_id).display_status == "已逾期"


def test_execution_guard_blocks_withdraw_delete_and_complete(
    test_database_engine: Engine,
) -> None:
    admin_id, factory_a_id, _, variant_id = _seed_order_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    setup_service = OrderService(sessions)
    draft = setup_service.create_draft(
        actor_id=admin_id,
        order_no="S04-GUARD",
        order_date=date(2026, 8, 21),
        tracker="松子",
        contract_ship_date=date(2026, 8, 30),
        lines=[
            DraftLineInput(
                variant_id,
                10,
                [AssignmentInput(factory_a_id, 10)],
            )
        ],
        request_id="req-guard-create",
    )
    setup_service.publish(
        actor_id=admin_id,
        order_id=draft.order_id,
        version=draft.version,
        request_id="req-guard-publish",
        idempotency_key="guard-publish",
    )
    shipped_service = OrderService(
        sessions, execution_guard=ConfigurableExecutionGuard(shipments=True)
    )
    with pytest.raises(OrderConflict):
        shipped_service.withdraw(
            actor_id=admin_id,
            order_id=draft.order_id,
            request_id="req-guard-withdraw",
            idempotency_key="guard-withdraw",
        )
    with pytest.raises(OrderConflict):
        shipped_service.delete(
            actor_id=admin_id,
            order_id=draft.order_id,
            request_id="req-guard-delete",
            idempotency_key="guard-delete",
        )
    pending_service = OrderService(
        sessions, execution_guard=ConfigurableExecutionGuard(pending_void=True)
    )
    with pytest.raises(OrderConflict):
        pending_service.complete(
            actor_id=admin_id,
            order_id=draft.order_id,
            request_id="req-guard-complete",
            idempotency_key="guard-complete",
        )
    assert setup_service.get(order_id=draft.order_id).lifecycle == "PUBLISHED"
