from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from io import BytesIO
from threading import Barrier

import pytest
from openpyxl import Workbook
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.db.models import User
from app.modules.repairs.confirmation import RepairConfirmationService
from app.modules.repairs.periods import RepairPeriodService, period_bounds
from app.modules.repairs.returns import (
    RepairReturnConflict,
    RepairReturnLineInput,
    RepairReturnNotFound,
)
from app.modules.repairs.workflow import (
    XLSX_MIME,
    RepairWorkflowService,
    RepairWorkflowValidationError,
)
from tests.integration.test_repair_returns import seed_return_repair


@pytest.mark.parametrize(
    ("day", "start", "end", "label"),
    [
        ("2026-01-31", "2025-08-01", "2026-01-31", "2025.8-2026.1"),
        ("2026-02-01", "2026-02-01", "2026-07-31", "2026.2-2026.7"),
        ("2026-07-31", "2026-02-01", "2026-07-31", "2026.2-2026.7"),
        ("2026-08-01", "2026-08-01", "2027-01-31", "2026.8-2027.1"),
    ],
)
def test_period_boundaries(day, start, end, label):
    assert period_bounds(date.fromisoformat(day)) == (
        date.fromisoformat(start),
        date.fromisoformat(end),
        label,
    )


def workbook(quantity):
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(
        ["编号", "厂家名称", "商品编码", "款式编码", "商品名称", "颜色/规格", "数量", "箱数"]
    )
    sheet.append(
        [
            "RETURN",
            "返修测试工厂",
            "RETURN-SKU",
            "RETURN-PRODUCT",
            "返修测试产品",
            "返修规格",
            quantity,
            "1",
        ]
    )
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_two_sheets_one_period_and_fifo_return(test_database_engine):
    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine)
    workflow = RepairWorkflowService(
        sessions, file_store=FakePrivateFileStore(bucket="period-test")
    )
    confirm = RepairConfirmationService(sessions, clock=lambda: datetime(2026, 9, 9, tzinfo=UTC))
    originals = []
    for quantity in [30, 20]:
        preview = workflow.create_preview(
            content=workbook(quantity),
            filename="质检.xlsx",
            mime_type=XLSX_MIME,
            uploaded_by="return-admin",
        )
        originals.append(
            confirm.confirm(
                preview_id=preview.preview_id,
                confirmed_by="return-admin",
                idempotency_key=f"create-{quantity}",
            )
        )
    periods = RepairPeriodService(sessions)
    rows, total = periods.page(factory_id="return-factory")
    assert total == 1
    detail = periods.get(rows[0]["repair_id"])
    assert detail.repair_no == "2026.8-2027.1"
    assert detail.warehouse_return_quantity == 50
    assert [f.filename for f in detail.attachments] == ["2026-09-09-01.xlsx", "2026-09-09-02.xlsx"]
    result = periods.submit(
        repair_id=detail.repair_id,
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="cross-sheet",
        lines=[RepairReturnLineInput("return-variant", 35, 5)],
    )
    assert result.returned_quantity == 40
    assert len(result.return_batches) == 1
    assert result.specs[0].pending_quantity == 10
    assert [confirm.get(x.repair_id).returned_quantity for x in originals] == [30, 10]
    assert [confirm.get(x.repair_id).scrapped_quantity for x in originals] == [0, 5]


def create_period_case(engine):
    seed_return_repair(engine)
    sessions = sessionmaker(engine)
    workflow = RepairWorkflowService(
        sessions, file_store=FakePrivateFileStore(bucket="period-test")
    )
    confirm = RepairConfirmationService(sessions)
    for qty in [30, 20]:
        p = workflow.create_preview(
            content=workbook(qty),
            filename="质检.xlsx",
            mime_type=XLSX_MIME,
            uploaded_by="return-admin",
        )
        confirm.confirm(
            preview_id=p.preview_id, confirmed_by="return-admin", idempotency_key=f"create-{qty}"
        )
    service = RepairPeriodService(sessions)
    return service, service.page()[0][0]["repair_id"]


def test_period_draft_replay_overflow_and_whole_archive(test_database_engine):
    service, pid = create_period_case(test_database_engine)
    args = dict(repair_id=pid, factory_id="return-factory", user_id="return-factory-user")
    entries = [{"variantId": "return-variant", "selected": True, "repaired": "35", "scrapped": "5"}]
    saved = service.save_draft(**args, version=0, entries=entries)
    assert service.get_draft(**args) == saved
    request = dict(
        repair_id=pid,
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key=saved.submission_key,
        draft_version=saved.version,
        lines=[RepairReturnLineInput("return-variant", 35, 5)],
    )
    with pytest.raises(RepairReturnConflict):
        service.submit(**{**request, "lines": [RepairReturnLineInput("return-variant", 51, 0)]})
    assert service.get_draft(**args) == saved
    assert service.submit(**request).returned_quantity == 40
    assert service.submit(**request).returned_quantity == 40
    assert service.get_draft(**args).entries == []
    with pytest.raises(RepairReturnConflict):
        service.archive(repair_id=pid, archived_by="return-admin", idempotency_key="archive")
    service.submit(
        **{
            **request,
            "idempotency_key": "finish",
            "draft_version": None,
            "lines": [RepairReturnLineInput("return-variant", 10, 0)],
        }
    )
    archived = service.archive(repair_id=pid, archived_by="return-admin", idempotency_key="archive")
    assert (
        service.archive(repair_id=pid, archived_by="return-admin", idempotency_key="archive")
        == archived
    )
    assert service.page()[1] == 0
    with pytest.raises(RepairReturnNotFound):
        service.get(pid)


def test_concurrent_period_returns_cannot_overdraw(test_database_engine):
    service, pid = create_period_case(test_database_engine)
    barrier = Barrier(2)

    def submit(key):
        barrier.wait()
        try:
            service.submit(
                repair_id=pid,
                factory_id="return-factory",
                submitted_by="return-factory-user",
                idempotency_key=key,
                lines=[RepairReturnLineInput("return-variant", 40, 0)],
            )
            return "success"
        except RepairReturnConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(submit, ["a", "b"])) == ["conflict", "success"]
    assert service.get(pid).returned_quantity == 40
    assert len(service.get(pid).return_batches) == 1


def test_period_permissions_and_drafts_are_user_isolated(test_database_engine):
    service, pid = create_period_case(test_database_engine)
    with Session(test_database_engine) as session, session.begin():
        session.add(
            User(
                user_id="other-worker",
                feishu_display_name="另一工厂用户",
                role="factory",
                factory_id="return-factory",
                is_enabled=True,
                is_super_admin=False,
            )
        )
    entries = [{"variantId": "return-variant", "selected": True, "repaired": "2", "scrapped": ""}]
    args = dict(repair_id=pid, factory_id="return-factory", user_id="return-factory-user")
    service.save_draft(**args, version=0, entries=entries)
    assert service.get_draft(**{**args, "user_id": "other-worker"}).entries == []
    with pytest.raises(RepairReturnConflict):
        service.save_draft(**args, version=0, entries=[])
    with pytest.raises(RepairReturnNotFound):
        service.get_draft(**{**args, "factory_id": "wrong"})
    with pytest.raises(RepairReturnNotFound):
        service.submit(
            repair_id=pid,
            factory_id="wrong",
            submitted_by="return-factory-user",
            idempotency_key="wrong",
            lines=[RepairReturnLineInput("return-variant", 1, 0)],
        )


def test_duplicate_file_and_archived_period_reject_new_upload(test_database_engine):
    service, pid = create_period_case(test_database_engine)
    sessions = sessionmaker(test_database_engine)
    flow = RepairWorkflowService(sessions, file_store=FakePrivateFileStore(bucket="period-test"))
    # Use exact source bytes, not just equal names.
    content = workbook(60)
    p = flow.create_preview(
        content=content, filename="同名.xlsx", mime_type=XLSX_MIME, uploaded_by="return-admin"
    )
    confirm = RepairConfirmationService(sessions)
    confirm.confirm(
        preview_id=p.preview_id, confirmed_by="return-admin", idempotency_key="additional"
    )
    with pytest.raises(RepairWorkflowValidationError, match="该文件已创建"):
        flow.create_preview(
            content=content, filename="改名.xlsx", mime_type=XLSX_MIME, uploaded_by="return-admin"
        )
    service.submit(
        repair_id=pid,
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="all",
        lines=[RepairReturnLineInput("return-variant", 110, 0)],
    )
    service.archive(repair_id=pid, archived_by="return-admin", idempotency_key="archive")
    new = flow.create_preview(
        content=workbook(3), filename="同名.xlsx", mime_type=XLSX_MIME, uploaded_by="return-admin"
    )
    with pytest.raises(RepairReturnConflict, match="已归档"):
        confirm.confirm(
            preview_id=new.preview_id, confirmed_by="return-admin", idempotency_key="after-archive"
        )
    assert service.page()[1] == 0


def test_period_does_not_borrow_from_another_half_year(test_database_engine):
    service, pid = create_period_case(test_database_engine)
    sessions = sessionmaker(test_database_engine)
    # Preview creation and confirmation both use the later clock.
    from app.modules.repairs.preview import RepairPreviewService

    flow = RepairWorkflowService(
        sessions,
        file_store=FakePrivateFileStore(bucket="period-test"),
        preview_service=RepairPreviewService(
            sessions, clock=lambda: datetime(2027, 2, 1, tzinfo=UTC)
        ),
    )
    p = flow.create_preview(
        content=workbook(4), filename="next.xlsx", mime_type=XLSX_MIME, uploaded_by="return-admin"
    )
    RepairConfirmationService(sessions, clock=lambda: datetime(2027, 2, 1, tzinfo=UTC)).confirm(
        preview_id=p.preview_id, confirmed_by="return-admin", idempotency_key="next-period"
    )
    assert service.page()[1] == 2
    page, total = service.page(page=2, page_size=1, sort_by="warehouseReturnQuantity")
    assert total == 2 and page[0]["warehouse_return_quantity"] == 50
    assert service.page(period="2027.2-2027.7")[0][0]["warehouse_return_quantity"] == 4
    assert service.page(keyword="%")[1] == 0
    assert service.page(status="COMPLETED")[1] == 0
    assert service.page(sort_by="factoryName")[1] == 2
    with pytest.raises(RepairReturnConflict):
        service.submit(
            repair_id=pid,
            factory_id="return-factory",
            submitted_by="return-factory-user",
            idempotency_key="overflow",
            lines=[RepairReturnLineInput("return-variant", 51, 0)],
        )
    assert service.get(pid).returned_quantity == 0


def test_period_migration_preserves_existing_source_and_return_facts(
    test_database_engine, test_database_url
):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.modules.repairs.returns import RepairReturnService

    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine)
    RepairReturnService(sessions).submit(
        repair_id="return-repair",
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="old-return",
        lines=[RepairReturnLineInput("return-variant", 3, 2)],
    )
    with test_database_engine.connect() as connection:
        original_lines = connection.execute(text("SELECT * FROM repair_inspection_lines")).all()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.downgrade(config, "20260909_0032")
    try:
        command.upgrade(config, "head")
        service = RepairPeriodService(sessions)
        rows, total = service.page()
        assert total == 1
        detail = service.get(rows[0]["repair_id"])
        assert detail.warehouse_return_quantity == 12
        assert detail.returned_quantity == 5
        assert len(detail.return_batches) == 1
        assert sum(line.returned_quantity for line in detail.return_batches[0].lines) == 5
        with test_database_engine.connect() as connection:
            assert (
                connection.execute(text("SELECT * FROM repair_inspection_lines")).all()
                == original_lines
            )
    finally:
        command.upgrade(config, "head")


def test_cross_sheet_notification_uses_one_full_batch(test_database_engine):
    from sqlalchemy import select

    from app.adapters.notifications import FakeFeishuBusinessNotifier, FakeWechatNotifier
    from app.db.models import OutboxMessage
    from app.modules.notifications_audit import NotificationsAuditService

    service, pid = create_period_case(test_database_engine)
    sessions = sessionmaker(test_database_engine)
    with sessions() as session, session.begin():
        for event in session.scalars(select(OutboxMessage)):
            event.status = "completed"
        session.get(User, "return-admin").feishu_display_name = "王心玲&煎饼"
    service.submit(
        repair_id=pid,
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="notice",
        lines=[RepairReturnLineInput("return-variant", 35, 5)],
    )
    notices = NotificationsAuditService(sessions)
    now = datetime.now(UTC).replace(tzinfo=None)
    assert notices.consume_next_business_event(worker_id="test", now=now)
    assert not notices.consume_next_business_event(worker_id="test", now=now)
    feishu, wechat = FakeFeishuBusinessNotifier(), FakeWechatNotifier()
    while notices.deliver_next(
        worker_id="test", feishu_notifier=feishu, wechat_notifier=wechat, now=now
    ):
        pass
    assert len(feishu.sent) == 1
    assert feishu.sent[0].target_path == f"/repairs/{pid}"
    assert feishu.sent[0].card_rows[0]["returnedQuantity"] == "40"
    assert feishu.sent[0].card_rows[0]["scrappedQuantity"] == "5"


def test_period_api_role_boundaries_and_web_history_omission(
    test_database_engine, test_database_url
):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.modules.identity_access import IdentityAccessService

    service, pid = create_period_case(test_database_engine)
    service.submit(
        repair_id=pid,
        factory_id="return-factory",
        submitted_by="return-factory-user",
        idempotency_key="api-batch",
        lines=[RepairReturnLineInput("return-variant", 35, 5)],
    )
    identity = IdentityAccessService(
        sessionmaker(test_database_engine),
        token_secret=b"period-test-token",
        phone_encryption_secret=b"period-test-encryption",
        phone_digest_secret=b"period-test-digest",
    )
    app = create_app(database_url=test_database_url, identity_service=identity)
    worker = identity.issue_session(user_id="return-factory-user", terminal="mini")
    admin = identity.issue_session(user_id="return-admin", terminal="web")
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/admin/repair-periods").status_code == 401
        header = {"Authorization": f"Bearer {worker.access_token}"}
        assert client.get("/api/v1/admin/repair-periods", headers=header).status_code == 403
        listed = client.get("/api/v1/factory/repair-periods", headers=header).json()
        assert listed["total"] == 1 and listed["items"][0]["repairId"] == pid
        detail = client.get(f"/api/v1/factory/repairs/{pid}", headers=header).json()
        assert len(detail["returnBatches"]) == 1 and len(detail["attachments"]) == 2
        client.cookies.set("ot_web_session", admin.access_token)
        web = client.get(f"/api/v1/admin/repairs/{pid}").json()
        assert web["returnBatches"] == [] and web["lines"] == []
        assert web["specs"][0]["returnedQuantity"] == 40
        assert len(web["attachments"]) == 2
        assert client.get("/api/v1/admin/repair-periods/options").json()["items"]


def test_factory_cycle_filters_across_twenty_item_boundary(test_database_engine):
    seed_return_repair(test_database_engine)
    sessions = sessionmaker(test_database_engine)
    workflow = RepairWorkflowService(sessions, file_store=FakePrivateFileStore(bucket="page-test"))
    for index in range(23):
        preview = workflow.create_preview(
            content=workbook(index + 1),
            filename="period.xlsx",
            mime_type=XLSX_MIME,
            uploaded_by="return-admin",
        )
        confirm = RepairConfirmationService(
            sessions, clock=lambda index=index: datetime(2000 + index, 9, 1, tzinfo=UTC)
        )
        confirm.confirm(
            preview_id=preview.preview_id,
            confirmed_by="return-admin",
            idempotency_key=f"page-{index}",
        )
    service = RepairPeriodService(sessions)
    first, total = service.page(factory_id="return-factory", page=1, page_size=20)
    second, _ = service.page(factory_id="return-factory", page=2, page_size=20)
    assert total == 23 and len(first) == 20 and len(second) == 3
    assert len({row["repair_id"] for row in first + second}) == 23
    assert service.page(factory_id="return-factory", keyword="2000.8")[1] == 1
    assert service.page(factory_id="return-factory", status="INCOMPLETE")[1] == 23
    assert service.page(factory_id="return-factory", status="COMPLETED")[1] == 0
    assert service.page(factory_id="different-factory")[1] == 0
    assert service.page(factory_id="return-factory", page=3, page_size=20) == ([], 23)
