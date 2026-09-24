import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    IncomingDiffBatch,
    IncomingDiffImage,
    IncomingDiffWorkbook,
    StoredFile,
    User,
)
from app.modules.incoming_differences.workbook import (
    XLSX_MIME,
    IncomingWorkbookCodec,
    IncomingWorkbookValidationError,
)


class IncomingWorkbookWorkflow:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        file_store: PrivateFileStore,
        codec: IncomingWorkbookCodec,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._sessions = sessions
        self._files = file_store
        self._codec = codec
        self._clock = clock
        self._id_factory = id_factory

    def generate(
        self, *, batch_id: str, actor_id: str, lines: list[dict[str, object]]
    ) -> IncomingDiffWorkbook:
        object_key: str | None = None
        try:
            with self._sessions() as session, session.begin():
                batch = self._batch(session, batch_id, actor_id)
                if batch.current_workbook_id is not None:
                    raise ValueError("批次已有核对表")
                image_files = self._image_files(session, batch_id)
                if {str(line["imageId"]) for line in lines} - set(image_files):
                    raise ValueError("明细来源图片不在本批次")
                images: dict[str, bytes] = {}
                for image_id, stored in image_files.items():
                    content = self._files.get(object_key=stored.object_key)
                    if hashlib.sha256(content).hexdigest() != stored.content_sha256:
                        raise ValueError("来源图片内容校验失败")
                    images[image_id] = content
                now = self._clock()
                content, signature, snapshot = self._codec.generate(
                    batch_id=batch_id, version=1, lines=lines, images=images, generated_at=now
                )
                record, object_key = self._save(
                    session, batch=batch, actor_id=actor_id, version=1,
                    direction="GENERATED", content=content, signature=signature,
                    snapshot=snapshot, now=now,
                )
            return record
        except Exception:
            if object_key is not None:
                self._files.delete(object_key=object_key)
            raise

    def upload(
        self, *, batch_id: str, version: int, actor_id: str, content: bytes
    ) -> IncomingDiffWorkbook:
        object_key: str | None = None
        try:
            with self._sessions() as session, session.begin():
                batch = self._batch(session, batch_id, actor_id)
                previous = session.get(IncomingDiffWorkbook, batch.current_workbook_id)
                if previous is None or previous.batch_id != batch_id or previous.version != version:
                    raise IncomingWorkbookValidationError([
                        {"code": "stale_version", "message": "核对表版本已过期"}
                    ])
                parsed = self._codec.parse(
                    content, batch_id=batch_id, version=version,
                    signature=previous.signature or "", previous_lines=previous.line_snapshot,
                )
                sources = {old["lineToken"]: old for old in previous.line_snapshot}
                for line in parsed:
                    source = sources[line["lineToken"]]
                    if any(line.get(field) != source.get(field) for field in (
                        "sheetName", "productName", "spec", "quantity", "purchaseOrderId"
                    )):
                        line["orderAssignmentId"] = None
                        line["purchaseOrderItemId"] = None
                next_version = version + 1
                now = self._clock()
                saved_content, signature = self._codec.advance(
                    content, batch_id=batch_id, version=next_version,
                    lines=parsed, generated_at=now,
                )
                record, object_key = self._save(
                    session, batch=batch, actor_id=actor_id, version=next_version,
                    direction="UPLOADED", content=saved_content, signature=signature,
                    snapshot=parsed, now=now,
                )
            return record
        except Exception:
            if object_key is not None:
                self._files.delete(object_key=object_key)
            raise

    def _save(
        self, session: Session, *, batch: IncomingDiffBatch, actor_id: str, version: int,
        direction: str, content: bytes, signature: str,
        snapshot: list[dict[str, object]], now: datetime,
    ) -> tuple[IncomingDiffWorkbook, str]:
        workbook_id = self._id_factory()
        object_key = f"incoming-differences/{batch.batch_id}/workbooks/{workbook_id}.xlsx"
        self._files.put(object_key=object_key, content=content, content_type=XLSX_MIME)
        try:
            stored = StoredFile(
                bucket=self._files.bucket, object_key=object_key,
                original_filename=f"{batch.batch_no}_核对表_v{version}.xlsx",
                mime_type=XLSX_MIME, size_bytes=len(content),
                content_sha256=hashlib.sha256(content).hexdigest(), uploaded_by=actor_id,
            )
            session.add(stored)
            session.flush()
            record = IncomingDiffWorkbook(
                workbook_id=workbook_id, batch_id=batch.batch_id, version=version,
                direction=direction, file_id=stored.file_id,
                content_sha256=stored.content_sha256, signature=signature,
                line_snapshot=snapshot, submitted_by=actor_id, submitted_at=now,
            )
            session.add(record)
            session.flush()
            batch.current_workbook_id = workbook_id
            batch.updated_at = now
            return record, object_key
        except Exception:
            self._files.delete(object_key=object_key)
            raise

    @staticmethod
    def _batch(session: Session, batch_id: str, actor_id: str) -> IncomingDiffBatch:
        batch = session.scalar(
            select(IncomingDiffBatch)
            .where(IncomingDiffBatch.batch_id == batch_id)
            .with_for_update()
        )
        actor = session.get(User, actor_id)
        if batch is None or actor is None or not actor.is_enabled or actor.role != "admin":
            raise ValueError("批次不存在或无权限")
        if batch.submitter_id != actor_id or batch.status != "READY":
            raise ValueError("批次状态或提交人无效")
        return batch

    @staticmethod
    def _image_files(session: Session, batch_id: str) -> dict[str, StoredFile]:
        return {
            image.image_id: stored
            for image, stored in session.execute(
                select(IncomingDiffImage, StoredFile)
                .join(StoredFile, IncomingDiffImage.file_id == StoredFile.file_id)
                .where(IncomingDiffImage.batch_id == batch_id)
            ).all()
        }
