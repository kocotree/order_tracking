import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.adapters.vision import DisabledIncomingDiffRecognizer
from app.db.models import (
    BackgroundJob,
    ExternalIdentity,
    Factory,
    IncomingDiffBatch,
    IncomingDiffWorkbook,
    OrderDetail,
    OutboxMessage,
    User,
)
from app.modules.incoming_differences.bot import FeishuBotService
from app.modules.incoming_differences.imports import IncomingImportWorkflow
from app.modules.incoming_differences.recognition import IncomingDiffRecognitionService
from app.modules.incoming_differences.service import (
    IncomingDifferenceConflict,
    IncomingDifferencePermissionDenied,
    IncomingDifferenceService,
    IncomingDifferenceValidationError,
)
from app.modules.incoming_differences.workbook import HEADERS, IncomingWorkbookCodec
from app.settings.config import Settings
from tests.integration.test_incoming_differences import (
    ADMIN,
    BATCH_ID,
    ORDER_ID,
    _line,
    _seed_batch,
    _seed_masters,
    _seed_order,
)


def document(factory: int, quantity: int) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = f"来货测试工厂{factory}"
    sheet.append(HEADERS)
    sheet.append(["来货测试产品", "红色 / 110" if factory == 1 else "蓝色 / 120",
                  quantity, None, None, f"PO-{factory}"])
    output = BytesIO()
    book.save(output)
    return output.getvalue()


@pytest.fixture
def import_setup(test_database_engine):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        _seed_order(session)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    files = FakePrivateFileStore(bucket="test-import")
    codec = IncomingWorkbookCodec(Settings(database_url="mysql+pymysql://fake@localhost/test"))
    return sessions, files, codec, IncomingImportWorkflow(sessions, files=files, codec=codec)


def receive(workflow, message, *, chat="chat", sent_at=1000, count=1):
    return workflow.receive(actor_id=ADMIN, chat_id=chat, open_id="open", message_id=message,
        sent_at=sent_at, attachments=[{"file_key": str(i), "file_name": f"{i}.xlsx"}
                                    for i in range(count)])


@pytest.mark.parametrize("bad", [b"broken", document(9, 2), document(1, 0)])
def test_any_bad_file_blocks_whole_set(import_setup, bad):
    sessions, _files, _codec, workflow = import_setup
    batch = receive(workflow, "bad", count=2)
    workflow.prepare(batch_id=batch, contents=[document(1, 3), bad])
    with sessions() as session:
        assert session.get(IncomingDiffBatch, batch).status == "FAILED"
        workbook = session.scalar(select(IncomingDiffWorkbook))
        assert workbook.validation_issues[0]["fileName"] == "1.xlsx"
    service = IncomingDifferenceService(sessions)
    with pytest.raises(IncomingDifferenceConflict):
        service.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN, review_revision=0)
    assert service.list_for_order(actor_id=ADMIN, order_id=ORDER_ID) == []


def test_failed_new_upload_invalidates_old_and_late_event_cannot_replace(import_setup):
    sessions, _files, _codec, workflow = import_setup
    old = receive(workflow, "old")
    workflow.prepare(batch_id=old, contents=[document(1, 3)])
    new = receive(workflow, "new", sent_at=2000)
    workflow.prepare(batch_id=new, contents=[b"bad"])
    late = receive(workflow, "late", sent_at=1500)
    with sessions() as session:
        assert session.get(IncomingDiffBatch, old).status == "SUPERSEDED"
        assert session.get(IncomingDiffBatch, late).status == "SUPERSEDED"
        assert session.get(IncomingDiffBatch, new).status == "FAILED"
    with pytest.raises(IncomingDifferenceConflict):
        IncomingDifferenceService(sessions).confirm(
            batch_id=old, workbook_version=1, actor_id=ADMIN, review_revision=0)


def test_concurrent_confirm_replays_and_new_history_requires_review(import_setup):
    sessions, _files, _codec, workflow = import_setup
    first = receive(workflow, "first", chat="one")
    second = receive(workflow, "second", chat="two")
    for batch in [first, second]:
        workflow.prepare(batch_id=batch, contents=[document(1, 3)])
    service = IncomingDifferenceService(sessions)

    def confirm():
        return service.confirm(batch_id=first, workbook_version=1, actor_id=ADMIN,
                               review_revision=0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert sorted(result.replayed for result in results) == [False, True]
    with pytest.raises(IncomingDifferenceConflict):
        service.confirm(batch_id=second, workbook_version=1, actor_id=ADMIN, review_revision=0)
    assert workflow.refresh_duplicates(second)
    workflow.decide(batch_id=second, actor_id=ADMIN, revision=1, message_id="skip",
                    decisions=[{"number": 1, "action": "skip"}])
    result = service.confirm(batch_id=second, workbook_version=1, actor_id=ADMIN, review_revision=2)
    assert result.record_count == result.factory_count == 0
    with sessions() as session:
        assert len(session.scalars(select(OutboxMessage).where(
            OutboxMessage.event_type == "incoming_diff.registered")).all()) == 1


def test_quantity_failure_never_partially_registers_files(import_setup):
    sessions, _files, _codec, workflow = import_setup
    batch = receive(workflow, "quantity", count=2)
    workflow.prepare(batch_id=batch, contents=[document(1, 2), document(2, -100000)])
    service = IncomingDifferenceService(sessions)
    with pytest.raises(IncomingDifferenceValidationError):
        service.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN, review_revision=0)
    assert service.list_for_order(actor_id=ADMIN, order_id=ORDER_ID) == []


def test_text_reply_binds_review_and_never_confirms(import_setup):
    sessions, files, codec, workflow = import_setup
    batch = receive(workflow, "duplicate", count=2)
    workflow.prepare(batch_id=batch, contents=[document(1, 3), document(1, 3)])
    with sessions() as session:
        marker = FeishuBotService._review_marker(session.get(IncomingDiffBatch, batch))

    class Media:
        def read_own_message(self, message_id, chat_id):
            return marker

    class Parser:
        def parse(self, *, text, numbers):
            assert numbers == [1, 2]
            return [{"number": number, "action": "skip"} for number in numbers]

    bot = FeishuBotService(sessions, files=files, media=Media(), identity_scope="test",
        codec=codec, decision_parser=Parser(), recognition=IncomingDiffRecognitionService(
            sessions, files=files, recognizer=DisabledIncomingDiffRecognizer()))
    payload = {"actorId": ADMIN, "openId": "open", "chatId": "chat",
               "messageId": "text", "parentId": "summary", "text": "全部跳过"}
    bot.decision_job(payload)
    bot.decision_job(payload)
    bot.decision_job({**payload, "messageId": "stale-text"})
    with sessions() as session:
        current = session.get(IncomingDiffBatch, batch)
        assert current.review_revision == 1 and current.status == "READY"
        summary = session.scalar(select(OutboxMessage).where(
            OutboxMessage.dedupe_key == f"incoming-diff-bot:import:{batch}:1:READY"))
        assert "本次第2条" in summary.payload["summary"]
        assert "决定：跳过" in summary.payload["summary"]
        stale = session.scalar(select(OutboxMessage).where(
            OutboxMessage.dedupe_key == "incoming-diff-bot:decision:stale-text"))
        assert "已失效" in stale.payload["summary"]
    assert IncomingDifferenceService(sessions).list_for_order(
        actor_id=ADMIN, order_id=ORDER_ID) == []


@pytest.mark.parametrize("keep_first", [False, True])
def test_same_timestamp_requires_explicit_selection(import_setup, keep_first):
    sessions, _files, _codec, workflow = import_setup
    first = receive(workflow, "simultaneous-a")
    workflow.prepare(batch_id=first, contents=[document(1, 1)])
    second = receive(workflow, "simultaneous-b")
    with sessions() as session:
        assert session.get(IncomingDiffBatch, first).status == "NEEDS_SELECTION"
        assert session.get(IncomingDiffBatch, second).status == "NEEDS_SELECTION"
    workflow.select_import(batch_id=first if keep_first else second, actor_id=ADMIN)
    workflow.prepare(batch_id=first, contents=[document(1, 1)])
    workflow.prepare(batch_id=second, contents=[document(1, 2)])
    with sessions() as session:
        assert session.get(IncomingDiffBatch, first).status == (
            "READY" if keep_first else "SUPERSEDED")
        assert session.get(IncomingDiffBatch, second).status == (
            "SUPERSEDED" if keep_first else "READY")


def test_transaction_failure_rolls_back_every_file(import_setup):
    sessions, _files, _codec, workflow = import_setup
    batch = receive(workflow, "transaction", count=2)
    workflow.prepare(batch_id=batch, contents=[document(1, 2), document(2, 3)])
    service = IncomingDifferenceService(sessions)

    def fail_outbox(mapper, connection, target):
        if target.event_type == "incoming_diff.registered":
            raise RuntimeError("injected write failure")

    event.listen(OutboxMessage, "before_insert", fail_outbox)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            service.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN, review_revision=0)
    finally:
        event.remove(OutboxMessage, "before_insert", fail_outbox)
    assert service.list_for_order(actor_id=ADMIN, order_id=ORDER_ID) == []
    assert service.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN,
                           review_revision=0).record_count == 2
    with sessions() as session, session.begin():
        session.get(User, ADMIN).is_enabled = False
    with pytest.raises(IncomingDifferencePermissionDenied):
        service.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN, review_revision=0)


def test_factory_disabled_after_preview_blocks_confirmation(import_setup):
    sessions, _files, _codec, workflow = import_setup
    batch = receive(workflow, "disabled-factory")
    workflow.prepare(batch_id=batch, contents=[document(1, 3)])
    with sessions() as session, session.begin():
        session.scalar(select(Factory).where(
            Factory.factory_name == "来货测试工厂1")).is_enabled = False
    with pytest.raises(IncomingDifferenceValidationError):
        IncomingDifferenceService(sessions).confirm(
            batch_id=batch, workbook_version=1, actor_id=ADMIN, review_revision=0)


def test_old_generated_confirmation_enters_duplicate_review(import_setup):
    sessions, files, codec, _workflow = import_setup
    with sessions() as session, session.begin():
        assignment_id = session.get(OrderDetail, "idf-detail-1").assignment_id
        lines = [{**_line(assignment_id, 2, row_number=row),
                  "factoryName": "来货测试工厂1", "productName": "来货测试产品",
                  "spec": "红色 / 110"}
                 for row in (2, 3)]
        _seed_batch(session, lines=lines)
    bot = FeishuBotService(sessions, files=files, media=object(), identity_scope="test",
        codec=codec, recognition=IncomingDiffRecognitionService(
            sessions, files=files, recognizer=DisabledIncomingDiffRecognizer()))
    bot.confirm_job({"batchId": BATCH_ID, "version": 1, "actorId": ADMIN, "openId": "open"})
    with sessions() as session:
        batch = session.get(IncomingDiffBatch, BATCH_ID)
        assert batch.status == "NEEDS_DECISION"
        assert batch.review_revision == 1
    assert IncomingDifferenceService(sessions).list_for_order(
        actor_id=ADMIN, order_id=ORDER_ID) == []


def test_new_files_supersede_inflight_photo_recognition(import_setup):
    sessions, files, codec, workflow = import_setup
    with sessions() as session, session.begin():
        _seed_batch(session, lines=[], status="RECOGNIZING")
    receive(workflow, "new-files", chat="chat-1")
    bot = FeishuBotService(sessions, files=files, media=object(), identity_scope="test",
        codec=codec, recognition=IncomingDiffRecognitionService(
            sessions, files=files, recognizer=DisabledIncomingDiffRecognizer()))
    bot.recognition_job({"batchId": BATCH_ID})
    bot.recognition_failed({"batchId": BATCH_ID}, ValueError("late failure"))
    with sessions() as session:
        assert session.get(IncomingDiffBatch, BATCH_ID).status == "SUPERSEDED"
        assert session.scalars(select(OutboxMessage)).all() == []


def test_two_free_files_confirm_together(test_database_engine: Engine) -> None:
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        _seed_order(session)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    workflow = IncomingImportWorkflow(
        sessions, files=FakePrivateFileStore(bucket="test-import"),
        codec=IncomingWorkbookCodec(Settings(database_url="mysql+pymysql://fake@localhost/test")),
    )
    batch = workflow.receive(actor_id=ADMIN, chat_id="chat", open_id="open",
                             message_id="files-1", sent_at=1000,
                             attachments=[{"file_key": "a", "file_name": "随意改名.xlsx"},
                                          {"file_key": "b", "file_name": "另一批.xlsx"}])
    workflow.prepare(batch_id=batch, contents=[document(1, -2), document(2, 3)])
    registration = IncomingDifferenceService(sessions)
    assert registration.list_for_order(actor_id=ADMIN, order_id=ORDER_ID) == []
    result = registration.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN,
                                  review_revision=0)
    assert result.record_count == 2
    assert sorted(row.quantity for row in registration.list_for_order(
        actor_id=ADMIN, order_id=ORDER_ID)) == [-2, 3]


def test_duplicates_require_decisions_and_old_review_cannot_confirm(test_database_engine: Engine):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        _seed_order(session)
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    workflow = IncomingImportWorkflow(sessions, files=FakePrivateFileStore(bucket="test-import"),
        codec=IncomingWorkbookCodec(Settings(database_url="mysql+pymysql://fake@localhost/test")))
    batch = workflow.receive(actor_id=ADMIN, chat_id="chat", open_id="open",
        message_id="duplicates", sent_at=1000,
        attachments=[{"file_key": "a", "file_name": "甲.xlsx"},
                     {"file_key": "b", "file_name": "乙.xlsx"}])
    workflow.prepare(batch_id=batch, contents=[document(1, -2), document(1, -2)])
    registration = IncomingDifferenceService(sessions)
    with pytest.raises(IncomingDifferenceConflict):
        registration.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN, review_revision=0)
    workflow.decide(batch_id=batch, actor_id=ADMIN, revision=0, message_id="decision",
                    decisions=[{"number": 1, "action": "skip"},
                               {"number": 2, "action": "register_new"}])
    with pytest.raises(IncomingDifferenceConflict):
        registration.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN, review_revision=0)
    result = registration.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN,
                                  review_revision=1)
    assert result.record_count == 1
    assert registration.confirm(batch_id=batch, workbook_version=1, actor_id=ADMIN,
                                review_revision=1).replayed


def test_real_post_files_shape_creates_one_recoverable_import(test_database_engine: Engine):
    with Session(test_database_engine) as session, session.begin():
        _seed_masters(session)
        _seed_order(session)
        session.add(ExternalIdentity(user_id=ADMIN, platform="feishu", scope="test",
                                      platform_subject="tenant:open"))
    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    files = FakePrivateFileStore(bucket="test-import")

    class Media:
        def download_resource(self, message_id, file_key, resource_type):
            return document(1, -2) if file_key == "a" else document(2, 3)

    bot = FeishuBotService(sessions, files=files, media=Media(), identity_scope="test",
        codec=IncomingWorkbookCodec(Settings(database_url="mysql+pymysql://fake@localhost/test")),
        recognition=IncomingDiffRecognitionService(sessions, files=files,
                                                   recognizer=DisabledIncomingDiffRecognizer()))
    event = {"header": {"event_type": "im.message.receive_v1", "event_id": "event1",
                        "tenant_key": "tenant"},
             "event": {"sender": {"sender_id": {"open_id": "open"}},
                       "message": {"chat_id": "chat", "message_id": "message1",
                                   "chat_type": "p2p", "message_type": "post",
                                   "create_time": "1000", "content": json.dumps({
                                       "content": [[]], "files": [
                                           {"file_key": "a", "file_name": "任意.xlsx"},
                                           {"file_key": "b", "file_name": "合并.xlsx"}]})}}}
    bot.event(event)
    event["header"]["event_id"] = "retry-with-new-event-id"
    bot.event(event)
    with sessions() as session:
        batches = session.scalars(select(IncomingDiffBatch)).all()
        assert len(batches) == 1
        jobs = session.scalars(select(BackgroundJob).where(
            BackgroundJob.job_type == "incoming_diff.import")).all()
        assert len(jobs) == 1
        payload = jobs[0].payload
    bot.import_job(payload)
    with sessions() as session:
        assert session.get(IncomingDiffBatch, batches[0].batch_id).status == "READY"
