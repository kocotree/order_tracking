from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO

import pytest
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.db.models import (
    IncomingDiffBatch,
    IncomingDiffImage,
    IncomingDiffWorkbook,
    StoredFile,
    User,
)
from app.modules.incoming_differences.workbook import (
    IncomingWorkbookCodec,
    IncomingWorkbookValidationError,
)
from app.modules.incoming_differences.workbook_workflow import IncomingWorkbookWorkflow
from app.settings.config import Settings

NOW = datetime(2026, 9, 24, tzinfo=UTC)


def test_generate_upload_versions_and_private_files(test_database_engine: Engine) -> None:
    picture = BytesIO()
    Image.new("RGB", (200, 100), "blue").save(picture, format="PNG")
    files = FakePrivateFileStore(bucket="incoming-test-private")
    files.put(object_key="images/source.png", content=picture.getvalue(), content_type="image/png")
    with Session(test_database_engine) as session, session.begin():
        session.add(User(
            user_id="workbook-admin", role="admin", is_enabled=True,
            feishu_display_name="核对表测试管理员",
        ))
        session.flush()
        session.add(StoredFile(
            file_id=9701, bucket=files.bucket, object_key="images/source.png",
            original_filename="source.png", mime_type="image/png",
            size_bytes=len(picture.getvalue()),
            content_sha256=sha256(picture.getvalue()).hexdigest(),
            uploaded_by="workbook-admin",
        ))
        session.add(IncomingDiffBatch(
            batch_id="workbook-batch", batch_no="IN20260924-01",
            submitter_id="workbook-admin", status="READY", frozen_at=NOW,
            created_at=NOW, updated_at=NOW,
        ))
        session.flush()
        session.add(IncomingDiffImage(
            image_id="workbook-image", batch_id="workbook-batch", sort_order=1,
            feishu_image_key="source-key", file_id=9701,
            content_sha256=sha256(picture.getvalue()).hexdigest(),
            ocr_status="SUCCEEDED", created_at=NOW,
        ))

    sessions = sessionmaker(test_database_engine, expire_on_commit=False)
    codec = IncomingWorkbookCodec(
        Settings(database_url="mysql+pymysql://fake:fake@localhost/fake")
    )
    workflow = IncomingWorkbookWorkflow(sessions, file_store=files, codec=codec, clock=lambda: NOW)
    generated = workflow.generate(
        batch_id="workbook-batch", actor_id="workbook-admin",
        lines=[{
            "imageId": "workbook-image", "factoryName": "甲工厂",
            "productName": "帽子", "spec": "红 / 110", "quantity": 2,
            "orderAssignmentId": 123, "purchaseOrderItemId": "POI-1",
        }],
    )
    assert generated.version == 1
    with Session(test_database_engine) as session:
        stored = session.get(StoredFile, generated.file_id)
        assert stored is not None
        original = files.get(object_key=stored.object_key)
    book = load_workbook(BytesIO(original))
    book["甲工厂"]["C2"] = 3
    edited = BytesIO()
    book.save(edited)
    uploaded = workflow.upload(
        batch_id="workbook-batch", version=1, actor_id="workbook-admin",
        content=edited.getvalue(),
    )
    assert uploaded.version == 2
    assert uploaded.direction == "UPLOADED"
    assert uploaded.line_snapshot[0]["imageId"] == "workbook-image"
    assert uploaded.line_snapshot[0]["orderAssignmentId"] is None
    with Session(test_database_engine) as session:
        batch = session.get(IncomingDiffBatch, "workbook-batch")
        assert batch is not None
        assert batch.current_workbook_id == uploaded.workbook_id
        assert len(session.scalars(select(IncomingDiffWorkbook)).all()) == 2
        latest = session.get(StoredFile, uploaded.file_id)
        assert latest is not None
        canonical = files.get(object_key=latest.object_key)
    assert codec.parse(
        canonical, batch_id="workbook-batch", version=2,
        signature=uploaded.signature or "", previous_lines=uploaded.line_snapshot,
    )[0]["quantity"] == 3
    with pytest.raises(IncomingWorkbookValidationError) as caught:
        workflow.upload(
            batch_id="workbook-batch", version=1, actor_id="workbook-admin",
            content=edited.getvalue(),
        )
    assert caught.value.issues[0]["code"] == "stale_version"
