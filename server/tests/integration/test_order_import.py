from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import FakeFeishuOrderSource
from app.db.models import (
    AuditLog,
    BackgroundJob,
    Factory,
    Order,
    OrderAssignment,
    OrderImportCandidate,
    OrderImportCandidateLine,
    OrderImportRun,
    OrderImportSourceRecord,
    OrderImportValidationIssue,
    OrderLine,
    Product,
    ProductVariant,
    User,
    UserSession,
)
from app.main import create_app
from app.modules.identity_access import IdentityAccessService
from app.modules.infrastructure import InfrastructureStore
from app.modules.order_import import OrderImportService, SourceOrderRow
from app.modules.order_import.worker import OrderImportWorkerHandlers
from app.modules.orders import OrderService
from app.worker.runtime import Worker


def _clean_import_data(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        imported_order_ids = list(
            session.scalars(select(Order.order_id).where(Order.source == "feishu"))
        )
        imported_line_ids = (
            list(
                session.scalars(
                    select(OrderLine.order_line_id).where(
                        OrderLine.order_id.in_(imported_order_ids)
                    )
                )
            )
            if imported_order_ids
            else []
        )
        if imported_line_ids:
            session.execute(
                delete(OrderAssignment).where(OrderAssignment.order_line_id.in_(imported_line_ids))
            )
        if imported_order_ids:
            session.execute(delete(OrderLine).where(OrderLine.order_id.in_(imported_order_ids)))
        session.execute(delete(OrderImportValidationIssue))
        session.execute(delete(OrderImportCandidateLine))
        session.execute(delete(OrderImportCandidate))
        if imported_order_ids:
            session.execute(delete(Order).where(Order.order_id.in_(imported_order_ids)))
        session.execute(delete(OrderImportSourceRecord))
        session.execute(delete(BackgroundJob).where(BackgroundJob.job_type == "order_import"))
        session.execute(
            delete(AuditLog).where(
                AuditLog.action.in_(["order.imported_from_feishu", "order.draft_created"])
                | AuditLog.action.like("order_import.%")
            )
        )
        session.execute(delete(OrderImportRun))
        session.execute(
            delete(ProductVariant).where(
                ProductVariant.variant_id.in_(["variant-import", "variant-import-2"])
            )
        )
        session.execute(delete(Product).where(Product.product_id == "product-import"))
        session.execute(
            delete(UserSession).where(
                UserSession.user_id.in_(["admin-order-import", "factory-import-user"])
            )
        )
        session.execute(
            delete(User).where(User.user_id.in_(["admin-order-import", "factory-import-user"]))
        )
        session.execute(delete(Factory).where(Factory.factory_id == "factory-import"))


def _seed_import_dependencies(engine: Engine) -> None:
    with Session(engine) as session, session.begin():
        factory = Factory(
            factory_id="factory-import",
            supplier_number="S05",
            factory_name="测试工厂",
            factory_code="S05",
            is_enabled=True,
        )
        session.add(factory)
        session.flush()
        session.add_all(
            [
                User(
                    user_id="admin-order-import",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name="松子",
                ),
                User(
                    user_id="factory-import-user",
                    role="factory",
                    is_enabled=True,
                    feishu_display_name="测试工厂用户",
                    factory_id=factory.factory_id,
                    factory_position="owner",
                ),
            ]
        )
        product = Product(
            product_id="product-import",
            source_i_id="ITEM-S05",
            name="测试童帽",
            is_available=True,
            source_modified_at=datetime(2026, 8, 22, 8, 0),
            first_synced_at=datetime(2026, 8, 22, 8, 0),
            last_synced_at=datetime(2026, 8, 22, 8, 0),
        )
        session.add(product)
        session.add(
            ProductVariant(
                variant_id="variant-import",
                product_id=product.product_id,
                source_sku_id="6970000000001",
                properties_value="蓝色 / 120",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=datetime(2026, 8, 22, 8, 0),
                first_synced_at=datetime(2026, 8, 22, 8, 0),
                last_synced_at=datetime(2026, 8, 22, 8, 0),
            )
        )


def test_two_admin_requests_reuse_one_active_import_run(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
    )

    first = service.create_or_reuse_run(
        actor_id="admin-order-import",
        request_id="request-import-1",
        idempotency_key="fetch-orders-1",
    )
    repeated = service.create_or_reuse_run(
        actor_id="admin-order-import",
        request_id="request-import-2",
        idempotency_key="fetch-orders-2",
    )

    assert repeated.run_id == first.run_id
    assert repeated.status == "PENDING"
    with Session(test_database_engine) as session:
        assert session.query(OrderImportRun).count() == 1

    _clean_import_data(test_database_engine)


def test_ready_candidate_imports_atomic_feishu_draft(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    )
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="run-confirm")
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                "rec-confirm",
                "E103",
                "6970000000001",
                "测试童帽",
                "蓝色 / 120",
                "童帽春夏",
                "测试工厂",
                100,
                0,
                100,
                "松子",
                date(2026, 8, 22),
                date(2026, 8, 30),
                {},
            )
        ],
    )
    with Session(test_database_engine) as session:
        candidate = session.query(OrderImportCandidate).filter_by(order_no="E103").one()
        candidate_id = candidate.candidate_id

    order_id = service.confirm_candidate(
        actor_id="admin-order-import", candidate_id=candidate_id, request_id="confirm"
    )

    with Session(test_database_engine) as session:
        order = session.get(Order, order_id)
        candidate = session.get(OrderImportCandidate, candidate_id)
        assert order is not None
        assert (order.source, order.lifecycle, order.version) == ("feishu", "DRAFT", 1)
        assert candidate is not None
        assert candidate.status == "IMPORTED"
        assert candidate.imported_order_id == order_id
        assert session.query(OrderLine).filter_by(order_id=order_id).one().order_quantity == 100
        assert (
            session.query(AuditLog).filter_by(action="order_import.candidate_imported").count() == 1
        )


def test_partial_shipment_threshold_imports_whole_order_and_saves_history_baseline(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            ProductVariant(
                variant_id="variant-import-2",
                product_id="product-import",
                source_sku_id="6970000000002",
                properties_value="蓝色 / 130",
                source_category="童帽春夏",
                source_enabled=1,
                is_available=True,
                source_modified_at=datetime(2026, 8, 22, 8, 0),
                first_synced_at=datetime(2026, 8, 22, 8, 0),
                last_synced_at=datetime(2026, 8, 22, 8, 0),
            )
        )
    service = OrderImportService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: datetime(2026, 8, 25, 9, 0, tzinfo=UTC),
    )
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="threshold-run")
    rows = [
        SourceOrderRow(
            "lt",
            "E-LT",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            100,
            49,
            51,
            "松子",
            None,
            date(2026, 8, 30),
            {},
        ),
        SourceOrderRow(
            "eq",
            "E-EQ",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            100,
            50,
            50,
            "松子",
            date(2026, 8, 22),
            date(2026, 8, 30),
            {},
        ),
        SourceOrderRow(
            "gt",
            "E-GT",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            100,
            60,
            40,
            "松子",
            date(2026, 8, 22),
            date(2026, 8, 30),
            {},
        ),
        SourceOrderRow(
            "mix-high",
            "E-MIX",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            100,
            80,
            20,
            "松子",
            date(2026, 8, 21),
            date(2026, 8, 30),
            {},
        ),
        SourceOrderRow(
            "mix-low",
            "E-MIX",
            "6970000000002",
            "测试童帽",
            "蓝色 / 130",
            "童帽春夏",
            "测试工厂",
            100,
            20,
            80,
            "松子",
            None,
            date(2026, 8, 30),
            {},
        ),
    ]

    service.process_run(run_id=run.run_id, rows=rows, pages_read=1)

    with Session(test_database_engine) as session:
        candidates = {item.order_no: item for item in session.query(OrderImportCandidate).all()}
        assert set(candidates) == {"E-LT", "E-MIX"}
        assert candidates["E-LT"].validation_state == "READY"
        assert candidates["E-LT"].order_date is None
        mixed = candidates["E-MIX"]
        assert mixed.validation_state == "READY"
        assert mixed.order_date == date(2026, 8, 21)
        assert mixed.shipped_quantity == 100
        assert mixed.pending_quantity == 100
        mixed_id = mixed.candidate_id

    order_id = service.confirm_candidate(
        actor_id="admin-order-import", candidate_id=mixed_id, request_id="confirm-mixed"
    )

    with Session(test_database_engine) as session:
        order = session.get(Order, order_id)
        assignments = list(
            session.scalars(
                select(OrderAssignment)
                .join(OrderLine, OrderLine.order_line_id == OrderAssignment.order_line_id)
                .where(OrderLine.order_id == order_id)
                .order_by(OrderAssignment.order_assignment_id)
            )
        )
        assert order is not None
        assert [item.initial_shipped_quantity for item in assignments] == [80, 20]
        order_service = OrderService(
            sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
        )
        logs = order_service.list_audit_logs(actor_id="admin-order-import", order_id=order_id)
        assert logs[0].operator_name == "松子"
        assert logs[0].content == ("从飞书导入订单：订单数量 200，初始已发数量 100，未发数量 100。")

    snapshot = order_service.get(order_id=order_id, today=date(2026, 8, 25))
    assert snapshot.shipped_quantity == 100
    assert snapshot.pending_quantity == 100
    assert snapshot.progress_percent == 50
    assert [line.shipped_quantity for line in snapshot.lines] == [80, 20]

    with Session(test_database_engine) as session:
        empty_date_candidate_id = session.scalar(
            select(OrderImportCandidate.candidate_id).where(OrderImportCandidate.order_no == "E-LT")
        )
    empty_date_order_id = service.confirm_candidate(
        actor_id="admin-order-import",
        candidate_id=str(empty_date_candidate_id),
        request_id="confirm-empty-date",
    )
    with Session(test_database_engine) as session:
        assert session.get(Order, empty_date_order_id).order_date is None
    _clean_import_data(test_database_engine)


def test_run_aggregates_eligible_partial_candidate_and_excludes_finished_order(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(
        sessionmaker(test_database_engine, class_=Session, expire_on_commit=False),
        clock=lambda: datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
    )
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="run")
    rows = [
        SourceOrderRow(
            "rec-ready",
            "E100",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            100,
            0,
            100,
            "松子",
            date(2026, 8, 22),
            date(2026, 8, 30),
            {},
        ),
        SourceOrderRow(
            "rec-shipped",
            "E101",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            80,
            20,
            60,
            "松子",
            date(2026, 8, 22),
            date(2026, 8, 30),
            {},
        ),
        SourceOrderRow(
            "rec-finished",
            "E102",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            50,
            50,
            0,
            "松子",
            date(2026, 8, 22),
            date(2026, 8, 30),
            {},
        ),
        SourceOrderRow(
            "rec-missing-order",
            None,
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            50,
            0,
            50,
            "松子",
            date(2026, 8, 22),
            date(2026, 8, 30),
            {},
        ),
    ]

    result = service.process_run(run_id=run.run_id, rows=rows, pages_read=2)

    assert result.status == "SUCCEEDED"
    assert result.failed_records == 1
    with Session(test_database_engine) as session:
        candidates = {item.order_no: item for item in session.query(OrderImportCandidate).all()}
        assert set(candidates) == {"E100", "E101"}
        assert candidates["E100"].validation_state == "READY"
        assert candidates["E101"].validation_state == "READY"
        assert candidates["E101"].shipped_quantity == 20
        line = (
            session.query(OrderImportCandidateLine)
            .filter_by(candidate_id=candidates["E100"].candidate_id)
            .one()
        )
        assert line.matched_variant_id == "variant-import"
        assert line.matched_factory_id == "factory-import"
        assert session.query(OrderImportSourceRecord).count() == 4

    refresh = service.create_or_reuse_run(
        actor_id="admin-order-import", request_id="run-refresh-threshold"
    )
    service.process_run(
        run_id=refresh.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                "rec-shipped",
                "E101",
                "6970000000001",
                "测试童帽",
                "蓝色 / 120",
                "童帽春夏",
                "测试工厂",
                80,
                40,
                40,
                "松子",
                date(2026, 8, 22),
                date(2026, 8, 30),
                {},
            )
        ],
    )
    with Session(test_database_engine) as session:
        assert (
            session.scalar(
                select(OrderImportCandidate).where(OrderImportCandidate.order_no == "E101")
            )
            is None
        )

    _clean_import_data(test_database_engine)


def test_worker_reads_fake_pages_and_http_requires_admin_web_session(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    service = OrderImportService(sessions)
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="worker-run")
    row = SourceOrderRow(
        "rec-worker",
        "E104",
        "6970000000001",
        "测试童帽",
        "蓝色 / 120",
        "童帽春夏",
        "测试工厂",
        100,
        0,
        100,
        "松子",
        date(2026, 8, 22),
        date(2026, 8, 30),
        {},
    )
    handler = OrderImportWorkerHandlers(
        service=service,
        source=FakeFeishuOrderSource([[row], []]),
    ).handlers()["order_import"]
    handler({"runId": run.run_id})
    assert service.get_run(actor_id="admin-order-import", run_id=run.run_id).pages_read == 2

    identity = IdentityAccessService(
        sessions,
        token_secret=b"order-import-api-token",
        phone_encryption_secret=b"order-import-api-phone",
        phone_digest_secret=b"order-import-api-digest",
    )
    admin_session = identity.issue_session(user_id="admin-order-import", terminal="web")
    factory_session = identity.issue_session(user_id="factory-import-user", terminal="web")
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        order_import_service=service,
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/admin/import-candidates").status_code == 401
        client.cookies.set("ot_web_session", factory_session.access_token)
        assert client.get("/api/v1/admin/import-candidates").status_code == 403
        client.cookies.set("ot_web_session", admin_session.access_token)
        listed = client.get("/api/v1/admin/import-candidates")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["orderNo"] == "E104"
        latest = client.get("/api/v1/admin/import-runs/latest")
        assert latest.status_code == 200
        assert latest.json()["status"] == "SUCCEEDED"
        missing_key = client.post(
            "/api/v1/admin/import-runs",
            headers={"X-CSRF-Token": admin_session.csrf_token or ""},
        )
        assert missing_key.status_code == 422
        created = client.post(
            "/api/v1/admin/import-runs",
            headers={
                "X-CSRF-Token": admin_session.csrf_token or "",
                "Idempotency-Key": "http-import-run-1",
            },
        )
        assert created.status_code == 202
        assert created.json()["requestId"]

    _clean_import_data(test_database_engine)


def test_worker_retries_before_releasing_failed_import_run(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    started_at = datetime(2026, 8, 22, 9, 0)
    service = OrderImportService(sessions, clock=lambda: started_at)
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="retry-run")
    order_handlers = OrderImportWorkerHandlers(
        service=service,
        source=FakeFeishuOrderSource([[]], fail_on_page=1),
    )
    worker = Worker(
        store=InfrastructureStore(sessions),
        worker_id="order-import-test-worker",
        handlers=order_handlers.handlers(),
        terminal_failure_handlers=order_handlers.terminal_failure_handlers(),
        retry_limits={"order_import": 3},
        retry_delay_seconds=30,
    )
    assert worker.run_once(now=started_at)
    assert service.get_run(actor_id="admin-order-import", run_id=run.run_id).status == "PENDING"
    assert worker.run_once(now=started_at + timedelta(seconds=31))
    assert service.get_run(actor_id="admin-order-import", run_id=run.run_id).status == "PENDING"
    assert worker.run_once(now=started_at + timedelta(seconds=62))
    failed = service.get_run(actor_id="admin-order-import", run_id=run.run_id)
    assert failed.status == "FAILED"

    next_run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="after-retry")
    assert next_run.run_id != run.run_id

    _clean_import_data(test_database_engine)
