from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, select
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
    OrderImportSourceCursor,
    OrderImportSourceRecord,
    OrderImportValidationIssue,
    OrderLine,
    Product,
    ProductVariant,
    User,
    UserSession,
)
from app.main import create_app
from app.modules.factory_access import FactoryAccessService
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
        session.execute(delete(OrderImportSourceCursor))
        session.execute(
            delete(BackgroundJob).where(
                BackgroundJob.job_type.in_(["order_import", "order_import_revalidate"])
            )
        )
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


def test_factory_user_enable_enqueues_local_revalidation_job(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with Session(test_database_engine) as session, session.begin():
        factory_user = session.get(User, "factory-import-user")
        assert factory_user is not None
        factory_user.is_enabled = False

    order_import = OrderImportService(sessions)
    run = order_import.create_or_reuse_run(
        actor_id="admin-order-import",
        request_id="run-factory-user-trigger",
    )
    order_import.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                "rec-factory-user-trigger",
                "E-FACTORY-TRIGGER",
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
    with Session(test_database_engine) as session, session.begin():
        session.execute(delete(BackgroundJob).where(BackgroundJob.job_type == "order_import"))

    FactoryAccessService(sessions).set_factory_user_enabled(
        actor_id="admin-order-import",
        target_user_id="factory-import-user",
        enabled=True,
        expected_version=1,
        request_id="enable-factory-user",
    )

    with Session(test_database_engine) as session:
        job = session.scalar(
            select(BackgroundJob).where(BackgroundJob.job_type == "order_import_revalidate")
        )
        assert job is not None
        assert job.payload["factoryNames"] == ["测试工厂"]
        assert job.status == "pending"

    handlers = OrderImportWorkerHandlers(
        service=order_import,
        source=FakeFeishuOrderSource([]),
    )
    worker = Worker(
        store=InfrastructureStore(sessions),
        worker_id="candidate-revalidation-worker",
        handlers=handlers.handlers(),
        retry_limits={"order_import_revalidate": 3},
    )
    assert worker.run_once()

    with Session(test_database_engine) as session:
        candidate = session.scalar(
            select(OrderImportCandidate).where(OrderImportCandidate.order_no == "E-FACTORY-TRIGGER")
        )
        assert candidate is not None
        assert candidate.validation_state == "READY"
        assert (
            session.scalar(
                select(BackgroundJob.status).where(
                    BackgroundJob.job_type == "order_import_revalidate"
                )
            )
            == "completed"
        )

    FactoryAccessService(sessions).set_factory_user_enabled(
        actor_id="admin-order-import",
        target_user_id="factory-import-user",
        enabled=False,
        expected_version=2,
        request_id="disable-last-factory-user",
    )
    assert worker.run_once()
    with Session(test_database_engine) as session:
        candidate = session.scalar(
            select(OrderImportCandidate).where(OrderImportCandidate.order_no == "E-FACTORY-TRIGGER")
        )
        assert candidate is not None
        assert candidate.validation_state == "INVALID"
        assert candidate.validation_issues == ["FACTORY_HAS_NO_ENABLED_USER"]

    _clean_import_data(test_database_engine)


def test_pending_candidate_revalidates_from_saved_snapshot_after_factory_user_enabled(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    with Session(test_database_engine) as session, session.begin():
        factory_user = session.get(User, "factory-import-user")
        assert factory_user is not None
        factory_user.is_enabled = False

    service = OrderImportService(
        sessions,
        clock=lambda: datetime(2026, 8, 22, 9, 0, tzinfo=UTC),
    )
    run = service.create_or_reuse_run(
        actor_id="admin-order-import",
        request_id="run-needs-factory-user",
    )
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                "rec-needs-factory-user",
                "E-REVALIDATE",
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
    with Session(test_database_engine) as session, session.begin():
        candidate = session.scalar(
            select(OrderImportCandidate).where(OrderImportCandidate.order_no == "E-REVALIDATE")
        )
        assert candidate is not None
        assert candidate.validation_issues == ["FACTORY_HAS_NO_ENABLED_USER"]
        factory_user = session.get(User, "factory-import-user")
        assert factory_user is not None
        factory_user.is_enabled = True

    result = service.revalidate_pending_candidates(
        factory_names=["测试工厂"],
        reason="factory_user_enabled",
        request_id="revalidate-factory-user",
    )

    assert result.checked_candidates == 1
    assert result.updated_candidates == 1
    with Session(test_database_engine) as session:
        candidate = session.scalar(
            select(OrderImportCandidate).where(OrderImportCandidate.order_no == "E-REVALIDATE")
        )
        assert candidate is not None
        assert candidate.validation_state == "READY"
        assert candidate.validation_issues == []

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


def test_worker_processes_each_page_without_replaying_previous_rows(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    service = OrderImportService(sessions)
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="worker-pages-once")
    rows = [
        SourceOrderRow(
            f"rec-worker-{index}",
            f"E10{index}",
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
        for index in (5, 6)
    ]

    handler = OrderImportWorkerHandlers(
        service=service,
        source=FakeFeishuOrderSource([[rows[0]], [rows[1]]]),
    ).handlers()["order_import"]
    handler({"runId": run.run_id})

    completed = service.get_run(actor_id="admin-order-import", run_id=run.run_id)
    assert completed.records_read == 2
    assert completed.candidates_created == 2
    assert completed.candidates_updated == 0

    _clean_import_data(test_database_engine)


def test_worker_processes_duplicate_record_only_once_per_run(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    service = OrderImportService(sessions)
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="worker-duplicate")
    first = SourceOrderRow(
        "rec-duplicate",
        "E110",
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
        {"version": 1},
        source_modified_at=datetime(2026, 9, 4, 1, 0),
    )
    duplicate = SourceOrderRow(
        **{
            **first.__dict__,
            "order_quantity": 120,
            "pending_quantity": 120,
            "raw_fields": {"version": 2},
            "source_modified_at": datetime(2026, 9, 4, 2, 0),
        }
    )

    OrderImportWorkerHandlers(
        service=service,
        source=FakeFeishuOrderSource([[first], [duplicate]]),
    ).handlers()["order_import"]({"runId": run.run_id})

    completed = service.get_run(actor_id="admin-order-import", run_id=run.run_id)
    with Session(test_database_engine) as session:
        candidate = session.query(OrderImportCandidate).filter_by(order_no="E110").one()
        assert candidate.total_quantity == 100
    assert completed.candidates_created == 1
    assert completed.candidates_updated == 0
    assert completed.skipped_records == 1

    _clean_import_data(test_database_engine)


def test_successful_watermark_is_reused_and_failed_run_does_not_advance_it(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    service = OrderImportService(sessions)
    first_modified = datetime(2026, 9, 4, 1, 0)
    later_modified = datetime(2026, 9, 4, 2, 0)
    first_row = SourceOrderRow(
        "rec-watermark",
        "E107",
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
        {"version": 1},
        source_modified_at=first_modified,
    )
    first_source = FakeFeishuOrderSource([[first_row]])
    first_run = service.create_or_reuse_run(
        actor_id="admin-order-import", request_id="watermark-first"
    )
    OrderImportWorkerHandlers(service=service, source=first_source).handlers()["order_import"](
        {"runId": first_run.run_id}
    )

    assert first_source.modified_since_requests == [None]
    assert service.successful_watermark(first_source.source_scope) == first_modified

    changed_row = SourceOrderRow(
        **{
            **first_row.__dict__,
            "order_quantity": 120,
            "pending_quantity": 120,
            "raw_fields": {"version": 2},
            "source_modified_at": later_modified,
        }
    )
    failing_source = FakeFeishuOrderSource([[changed_row], []], fail_on_page=2)
    failed_run = service.create_or_reuse_run(
        actor_id="admin-order-import", request_id="watermark-failed"
    )
    handler = OrderImportWorkerHandlers(service=service, source=failing_source)
    try:
        handler.handlers()["order_import"]({"runId": failed_run.run_id})
    except Exception as error:
        handler.terminal_failure_handlers()["order_import"]({"runId": failed_run.run_id}, error)
    else:
        raise AssertionError("the fake source should fail on its second page")

    assert failing_source.modified_since_requests == [first_modified]
    assert service.successful_watermark(failing_source.source_scope) == first_modified
    latest_after_failure = service.latest_run(actor_id="admin-order-import")
    assert latest_after_failure is not None
    assert latest_after_failure.run_id == first_run.run_id
    with Session(test_database_engine) as session:
        unchanged = session.query(OrderImportCandidate).filter_by(order_no="E107").one()
        assert unchanged.total_quantity == 100

    retry_source = FakeFeishuOrderSource([[changed_row]])
    retry_run = service.create_or_reuse_run(
        actor_id="admin-order-import", request_id="watermark-retry"
    )
    OrderImportWorkerHandlers(service=service, source=retry_source).handlers()["order_import"](
        {"runId": retry_run.run_id}
    )
    retried = service.get_run(actor_id="admin-order-import", run_id=retry_run.run_id)
    assert retry_source.modified_since_requests == [first_modified]
    assert service.successful_watermark(retry_source.source_scope) == later_modified
    assert retried.candidates_updated == 1
    assert retried.skipped_records == 0

    _clean_import_data(test_database_engine)


def test_incremental_change_rebuilds_pending_candidate_from_saved_order_rows(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    service = OrderImportService(sessions)
    first_modified = datetime(2026, 9, 4, 1, 0)
    original_rows = [
        SourceOrderRow(
            f"rec-group-{index}",
            "E108",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            quantity,
            0,
            quantity,
            "松子",
            date(2026, 8, 22),
            date(2026, 8, 30),
            {"version": 1, "line": index},
            source_modified_at=first_modified,
        )
        for index, quantity in ((1, 40), (2, 60))
    ]
    first_run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="group-first")
    OrderImportWorkerHandlers(
        service=service, source=FakeFeishuOrderSource([original_rows])
    ).handlers()["order_import"]({"runId": first_run.run_id})

    changed = SourceOrderRow(
        **{
            **original_rows[0].__dict__,
            "order_quantity": 50,
            "pending_quantity": 50,
            "raw_fields": {"version": 2, "line": 1},
            "source_modified_at": datetime(2026, 9, 4, 2, 0),
        }
    )
    second_run = service.create_or_reuse_run(
        actor_id="admin-order-import", request_id="group-second"
    )
    OrderImportWorkerHandlers(
        service=service, source=FakeFeishuOrderSource([[changed]])
    ).handlers()["order_import"]({"runId": second_run.run_id})

    with Session(test_database_engine) as session:
        candidate = session.query(OrderImportCandidate).filter_by(order_no="E108").one()
        assert candidate.source_record_count == 2
        assert candidate.total_quantity == 110
        assert (
            session.query(OrderImportCandidateLine)
            .filter_by(candidate_id=candidate.candidate_id)
            .count()
            == 2
        )

    _clean_import_data(test_database_engine)


def test_incremental_change_does_not_overwrite_imported_source_snapshot(
    test_database_engine: Engine,
) -> None:
    _clean_import_data(test_database_engine)
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    service = OrderImportService(sessions)
    original = SourceOrderRow(
        "rec-frozen",
        "E109",
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
        {"version": 1},
        source_modified_at=datetime(2026, 9, 4, 1, 0),
    )
    first_run = service.create_or_reuse_run(
        actor_id="admin-order-import", request_id="frozen-first"
    )
    source = FakeFeishuOrderSource([[original]])
    OrderImportWorkerHandlers(service=service, source=source).handlers()["order_import"](
        {"runId": first_run.run_id}
    )
    with Session(test_database_engine) as session:
        candidate_id = (
            session.query(OrderImportCandidate).filter_by(order_no="E109").one().candidate_id
        )
    order_id = service.confirm_candidate(
        actor_id="admin-order-import", candidate_id=candidate_id, request_id="frozen-confirm"
    )

    changed = SourceOrderRow(
        **{
            **original.__dict__,
            "order_quantity": 999,
            "pending_quantity": 999,
            "raw_fields": {"version": 2},
            "source_modified_at": datetime(2026, 9, 4, 2, 0),
        }
    )
    second_run = service.create_or_reuse_run(
        actor_id="admin-order-import", request_id="frozen-second"
    )
    OrderImportWorkerHandlers(
        service=service, source=FakeFeishuOrderSource([[changed]])
    ).handlers()["order_import"]({"runId": second_run.run_id})

    with Session(test_database_engine) as session:
        source_record = (
            session.query(OrderImportSourceRecord).filter_by(source_record_id="rec-frozen").one()
        )
        order_line = session.query(OrderLine).filter_by(order_id=order_id).one()
        assert source_record.raw_fields == {"version": 1}
        assert source_record.source_modified_at == datetime(2026, 9, 4, 1, 0)
        assert order_line.order_quantity == 100

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


def test_detail_dates_convert_once_preserve_override_and_block_missing(
    test_database_engine: Engine,
) -> None:
    from dataclasses import replace

    import pytest

    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    service = OrderImportService(sessions)
    row = SourceOrderRow(
        "date-row",
        "438#",
        "6970000000001",
        "测试童帽",
        "蓝色 / 120",
        "童帽春夏",
        "测试工厂",
        100,
        0,
        100,
        "松子",
        None,
        date(2026, 12, 31),
        {},
    )
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="date-run")
    service.process_run(run_id=run.run_id, pages_read=1, rows=[row], source_scope="date-test")
    candidates, _ = service.list_candidates(actor_id="admin-order-import")
    candidate = candidates[0]
    assert candidate.contract_ship_dates == [date(2026, 12, 27)]
    assert candidate.lines[0].contract_ship_date == date(2026, 12, 27)
    saved = service.save_candidate_date(
        actor_id="admin-order-import",
        candidate_id=candidate.candidate_id,
        candidate_line_id=candidate.lines[0].candidate_line_id,
        version=candidate.version,
        contract_ship_date=date(2027, 1, 2),
        request_id="save-date",
    )
    with pytest.raises(ValueError, match="version"):
        service.save_candidate_date(
            actor_id="admin-order-import",
            candidate_id=candidate.candidate_id,
            candidate_line_id=candidate.lines[0].candidate_line_id,
            version=candidate.version,
            contract_ship_date=date(2027, 1, 3),
            request_id="stale-date",
        )
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="date-run-2")
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[replace(row, contract_ship_date=None)],
        source_scope="date-test",
    )
    refreshed = service.get_candidate(
        actor_id="admin-order-import", candidate_id=saved.candidate_id
    )
    assert refreshed.lines[0].contract_ship_date == date(2027, 1, 2)
    cleared = service.save_candidate_date(
        actor_id="admin-order-import",
        candidate_id=saved.candidate_id,
        candidate_line_id=refreshed.lines[0].candidate_line_id,
        version=refreshed.version,
        contract_ship_date=None,
        request_id="clear-date",
    )
    assert "INCONSISTENT_CONTRACT_SHIP_DATE" not in cleared.validation_issues
    with pytest.raises(ValueError, match="合同出货时间"):
        service.confirm_candidate(
            actor_id="admin-order-import",
            candidate_id=cleared.candidate_id,
            request_id="confirm-empty",
        )


def test_same_sku_factory_conflicts_blank_then_import_one_assignment(
    test_database_engine: Engine,
) -> None:
    from dataclasses import replace

    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    service = OrderImportService(sessions)
    row = SourceOrderRow(
        "conflict-1",
        "CONFLICT-DATE",
        "6970000000001",
        "测试童帽",
        "蓝色 / 120",
        "童帽春夏",
        "测试工厂",
        100,
        0,
        100,
        "松子",
        None,
        date(2026, 12, 31),
        {},
    )
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="conflict-run")
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[row, replace(row, record_id="conflict-2", contract_ship_date=date(2027, 1, 1))],
    )
    candidate = service.list_candidates(actor_id="admin-order-import")[0][0]
    assert candidate.validation_issues == []
    assert all(line.contract_ship_date is None for line in candidate.lines)
    saved = service.save_candidate_date(
        actor_id="admin-order-import",
        candidate_id=candidate.candidate_id,
        candidate_line_id=candidate.lines[0].candidate_line_id,
        version=candidate.version,
        contract_ship_date=date(2027, 1, 2),
        request_id="resolve-conflict",
    )
    assert all(line.contract_ship_date == date(2027, 1, 2) for line in saved.lines)
    order_id = service.confirm_candidate(
        actor_id="admin-order-import",
        candidate_id=candidate.candidate_id,
        version=saved.version,
        request_id="import-conflict",
    )
    order = OrderService(sessions).get(order_id=order_id)
    assert order.contract_ship_dates == [date(2027, 1, 2)]
    assert len(order.lines) == 1 and len(order.lines[0].assignments) == 1
    assert order.lines[0].assignments[0].assigned_quantity == 200
    assert order.lines[0].assignments[0].contract_ship_date == date(2027, 1, 2)


def test_candidate_date_api_authorization_version_and_import_lock(
    test_database_engine: Engine, test_database_url: str
) -> None:
    _seed_import_dependencies(test_database_engine)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    service = OrderImportService(sessions)
    row = SourceOrderRow(
        "api-date",
        "API-DATE",
        "6970000000001",
        "测试童帽",
        "蓝色 / 120",
        "童帽春夏",
        "测试工厂",
        100,
        0,
        100,
        "松子",
        None,
        None,
        {},
    )
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="api-date-run")
    service.process_run(run_id=run.run_id, pages_read=1, rows=[row])
    candidate = service.list_candidates(actor_id="admin-order-import")[0][0]
    identity = IdentityAccessService(
        sessions,
        token_secret=b"date-api-token",
        phone_encryption_secret=b"date-api-phone",
        phone_digest_secret=b"date-api-digest",
    )
    admin = identity.issue_session(user_id="admin-order-import", terminal="web")
    factory = identity.issue_session(user_id="factory-import-user", terminal="web")
    url = (
        f"/api/v1/admin/import-candidates/{candidate.candidate_id}/lines/"
        f"{candidate.lines[0].candidate_line_id}/date"
    )
    payload = {"version": candidate.version, "contractShipDate": "2027-01-02"}
    app = create_app(
        database_url=test_database_url, identity_service=identity, order_import_service=service
    )
    with TestClient(app, base_url="https://testserver") as client:
        assert client.patch(url, json=payload).status_code == 401
        client.cookies.set("ot_web_session", factory.access_token)
        assert (
            client.patch(
                url, json=payload, headers={"X-CSRF-Token": factory.csrf_token}
            ).status_code
            == 403
        )
        client.cookies.set("ot_web_session", admin.access_token)
        assert client.patch(url, json=payload).status_code == 403
        saved = client.patch(url, json=payload, headers={"X-CSRF-Token": admin.csrf_token})
        assert saved.status_code == 200
        assert saved.json()["contractShipDates"] == ["2027-01-02"]
        assert (
            client.patch(url, json=payload, headers={"X-CSRF-Token": admin.csrf_token}).status_code
            == 409
        )
        confirm_url = f"/api/v1/admin/import-candidates/{candidate.candidate_id}/confirm"
        headers = {
            "X-CSRF-Token": admin.csrf_token,
            "Idempotency-Key": "api-date-import",
            "X-Candidate-Version": str(candidate.version),
        }
        assert client.post(confirm_url, headers=headers).status_code == 409
        headers["X-Candidate-Version"] = str(saved.json()["version"])
        assert client.post(confirm_url, headers=headers).status_code == 200
        payload["version"] = saved.json()["version"]
        assert (
            client.patch(url, json=payload, headers={"X-CSRF-Token": admin.csrf_token}).status_code
            == 409
        )


def test_contract_date_conversion_crosses_year_month_and_weekend(
    test_database_engine: Engine,
) -> None:
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(sessionmaker(test_database_engine, expire_on_commit=False))
    cases = [
        (date(2027, 1, 2), date(2026, 12, 29)),
        (date(2026, 3, 1), date(2026, 2, 25)),
        (date(2028, 3, 1), date(2028, 2, 26)),
        (date(2026, 9, 7), date(2026, 9, 3)),
    ]
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="calendar")
    rows = [
        SourceOrderRow(
            f"calendar-{index}",
            f"CAL-{index}",
            "6970000000001",
            "测试童帽",
            "蓝色 / 120",
            "童帽春夏",
            "测试工厂",
            100,
            0,
            100,
            "松子",
            None,
            original,
            {},
        )
        for index, (original, _) in enumerate(cases)
    ]
    service.process_run(run_id=run.run_id, pages_read=1, rows=rows)
    candidates, count = service.list_candidates(
        actor_id="admin-order-import", sort_by="orderNo", sort_order="asc"
    )
    assert count == 4
    assert [item.lines[0].contract_ship_date for item in candidates] == [
        expected for _, expected in cases
    ]
    assert [item.lines[0].source_contract_ship_date for item in candidates] == [
        original for original, _ in cases
    ]


@pytest.mark.parametrize("size", [20, 100])
@pytest.mark.parametrize("sort_by", ["default", "productName", "factory"])
def test_candidate_page_query_count_is_bounded(
    test_database_engine: Engine, size: int, sort_by: str
) -> None:
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(sessionmaker(test_database_engine, expire_on_commit=False))
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="performance")
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                f"perf-{index}",
                f"PERF-{index:03}",
                "6970000000001",
                f"测试童帽{index:03}",
                "蓝色 / 120",
                "童帽春夏",
                f"测试工厂{index:03}",
                100,
                0,
                100,
                "松子",
                None,
                date(2026, 9, 20),
                {},
            )
            for index in range(size)
        ],
    )
    statements: list[str] = []

    def record_sql(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(test_database_engine, "before_cursor_execute", record_sql)
    try:
        items, total = service.list_candidates(
            actor_id="admin-order-import", page=2, page_size=10, sort_by=sort_by
        )
    finally:
        event.remove(test_database_engine, "before_cursor_execute", record_sql)
    assert total == size
    assert [item.order_no for item in items] == [f"PERF-{index:03}" for index in range(10, 20)]
    assert all(len(item.lines) == 1 for item in items)
    print(f"sort={sort_by}, candidate count={size}, SQL statements={len(statements)}")
    assert len(statements) <= 4


def test_candidate_filters_and_all_sorts_match_legacy_pages(test_database_engine: Engine) -> None:
    """Use the unchanged detail API plus the legacy Python rules as a migration oracle."""
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(sessionmaker(test_database_engine, expire_on_commit=False))
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="page-equivalence")
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                f"equivalence-{index}-{part}",
                f"EQ-{index:03}",
                "6970000000001",
                ["Alpha", "alpha", "Álpha", "童帽", None][index % 5],
                "蓝色 100%_\\ / 120" if part == 0 else "红色",
                "童帽春夏",
                ["甲厂", "乙厂", None][(index + part) % 3],
                100,
                0,
                100,
                "松子",
                None,
                date(2026, 9, 20),
                {},
            )
            for index in range(36)
            for part in range(2)
        ],
    )
    with Session(test_database_engine) as session, session.begin():
        rows = list(
            session.scalars(select(OrderImportCandidate).order_by(OrderImportCandidate.order_no))
        )
        for index, row in enumerate(rows):
            row.status = "PENDING" if index < 24 else "IMPORTED"
            row.category = ["服装", "帽子", "服装、帽子", None][index % 4]
            row.tracker = ["松子", "烧麦", None][index % 3]
            row.validation_state = "READY" if index % 2 else "INVALID"
            row.order_date = date(2026, 9, index % 6 + 1) if index % 3 else None
            row.updated_at = datetime(2026, 9, 8) + timedelta(seconds=index)
        rows[-1].status = "EXCLUDED"
        session.execute(
            delete(OrderImportCandidateLine).where(
                OrderImportCandidateLine.candidate_id == rows[0].candidate_id
            )
        )
        ids = [row.candidate_id for row in rows if row.status != "EXCLUDED"]
    snapshots = [
        service.get_candidate(actor_id="admin-order-import", candidate_id=id_) for id_ in ids
    ]
    snapshots.sort(key=lambda item: item.updated_at, reverse=True)
    sort_keys = {
        "default": lambda item: (
            item.validation_state != "READY",
            -(item.order_date.toordinal() if item.order_date else 0),
            item.order_no,
        ),
        "orderNo": lambda item: item.order_no,
        "productName": lambda item: "、".join(line.product_name or "" for line in item.lines),
        "category": lambda item: item.category or "",
        "tracker": lambda item: item.tracker or "",
        "factory": lambda item: "、".join(line.factory_name or "" for line in item.lines),
        "validationState": lambda item: item.validation_state,
        "updatedAt": lambda item: item.updated_at,
    }
    for status in ["PENDING", "IMPORTED"]:
        for field, key in sort_keys.items():
            for direction in ["asc", "desc"]:
                expected = sorted(
                    [item for item in snapshots if item.status == status],
                    key=key,
                    reverse=direction == "desc",
                )
                for page in [1, 2, 4]:
                    actual, total = service.list_candidates(
                        actor_id="admin-order-import",
                        status=status,
                        sort_by=field,
                        sort_order=direction,
                        page=page,
                        page_size=10,
                    )
                    assert total == len(expected)
                    assert actual == expected[(page - 1) * 10 : page * 10], (
                        status,
                        field,
                        direction,
                        page,
                    )
    cases = [
        {"keyword": "  ALPHA  "},
        {"keyword": "100%_\\"},
        {"keyword": "EQ-02"},
        {"keyword": "álpha"},
        {"keyword": "not-found"},
        {"category": "帽子"},
        {"category": "服"},
        {"category": "服装、帽子"},
        {"validation_state": "ready"},
        {"trackers": ["松子", "烧麦"]},
        {"factory_names": ["甲厂", "乙厂"]},
        {"validation_state": "READY"},
        {
            "category": "帽子",
            "factory_names": ["甲厂", "乙厂"],
            "trackers": ["松子", "烧麦"],
            "validation_state": "READY",
        },
    ]
    for filters in cases:
        expected = [item for item in snapshots if item.status == "PENDING"]
        if "keyword" in filters:
            keyword = filters["keyword"].strip().casefold()
            expected = [
                item
                for item in expected
                if any(
                    keyword in (value or "").casefold()
                    for value in [
                        item.order_no,
                        *[line.product_name for line in item.lines],
                        *[line.properties_value for line in item.lines],
                    ]
                )
            ]
        if "category" in filters:
            expected = [
                item
                for item in expected
                if filters["category"] in (item.category or "").split("、")
            ]
        if "trackers" in filters:
            expected = [item for item in expected if item.tracker in filters["trackers"]]
        if "factory_names" in filters:
            expected = [
                item
                for item in expected
                if any(line.factory_name in filters["factory_names"] for line in item.lines)
            ]
        if "validation_state" in filters:
            expected = [
                item for item in expected if item.validation_state == filters["validation_state"]
            ]
        expected.sort(key=sort_keys["default"])
        for page in [1, 2]:
            actual, total = service.list_candidates(
                actor_id="admin-order-import", page=page, page_size=10, **filters
            )
            assert total == len(expected), filters
            assert actual == expected[(page - 1) * 10 : page * 10], filters


def test_candidate_search_preserves_unicode_casefold(test_database_engine: Engine) -> None:
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(sessionmaker(test_database_engine, expire_on_commit=False))
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="casefold")
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                "unicode",
                "UNICODE",
                "6970000000001",
                "Straße ﬃ ς İ",
                "蓝色",
                "童帽春夏",
                "测试工厂",
                100,
                0,
                100,
                "松子",
                None,
                date(2026, 9, 20),
                {},
            ),
        ],
    )
    for keyword in ["STRASSE", "s", "ffi", "fi", "Σ", "i\u0307"]:
        items, total = service.list_candidates(actor_id="admin-order-import", keyword=keyword)
        assert total == 1, keyword
        assert items[0].order_no == "UNICODE"


@pytest.mark.parametrize("sort_by", ["productName", "factory"])
def test_candidate_sort_uses_full_ordered_line_string(
    test_database_engine: Engine, sort_by: str
) -> None:
    _seed_import_dependencies(test_database_engine)
    service = OrderImportService(sessionmaker(test_database_engine, expire_on_commit=False))
    run = service.create_or_reuse_run(actor_id="admin-order-import", request_id="long-sort")
    service.process_run(
        run_id=run.run_id,
        pages_read=1,
        rows=[
            SourceOrderRow(
                f"long-{suffix}-{index:03}",
                f"LONG-{suffix}",
                "6970000000001",
                "x" * 90 if index < 49 else suffix,
                "蓝色",
                "童帽春夏",
                "x" * 90 if index < 49 else suffix,
                100,
                0,
                100,
                "松子",
                None,
                date(2026, 9, 20),
                {},
            )
            for suffix in ["Z", "A"]
            for index in range(50)
        ],
    )
    for direction, expected in [("asc", "LONG-A"), ("desc", "LONG-Z")]:
        items, total = service.list_candidates(
            actor_id="admin-order-import", sort_by=sort_by, sort_order=direction, page_size=1
        )
        assert total == 2
        assert items[0].order_no == expected
        assert len(items[0].lines) == 50
