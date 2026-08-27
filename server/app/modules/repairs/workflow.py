from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import RepairPreview, RepairPreviewLine, StoredFile
from app.modules.repairs.preview import RepairPreviewService, RepairPreviewView
from app.modules.repairs.workbook import InspectionWorkbookParser

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class RepairWorkflowValidationError(ValueError):
    pass


class RepairWorkflowService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        file_store: PrivateFileStore,
        parser: InspectionWorkbookParser | None = None,
        preview_service: RepairPreviewService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._sessions = session_factory
        self._file_store = file_store
        self._parser = parser or InspectionWorkbookParser()
        self._previews = preview_service or RepairPreviewService(session_factory, clock=clock)
        self._clock = clock
        self._id_factory = id_factory

    def create_preview(
        self,
        *,
        content: bytes,
        filename: str,
        mime_type: str,
        uploaded_by: str,
        replaces_preview_id: str | None = None,
    ) -> RepairPreviewView:
        if Path(filename).suffix.lower() != ".xlsx" or mime_type != XLSX_MIME:
            raise RepairWorkflowValidationError("只支持标准 .xlsx 质检文件")
        snapshot = self._parser.parse(content)
        digest = sha256(content).hexdigest()
        upload_id = self._id_factory()
        original_key = f"repairs/previews/{upload_id}/source.xlsx"
        self._file_store.put(
            object_key=original_key,
            content=content,
            content_type=XLSX_MIME,
        )
        original_file_id: int | None = None
        created_preview_id: str | None = None
        created_object_keys = [original_key]
        try:
            with self._sessions() as session, session.begin():
                original = StoredFile(
                    bucket=self._file_store.bucket,
                    object_key=original_key,
                    original_filename=filename,
                    mime_type=XLSX_MIME,
                    size_bytes=len(content),
                    content_sha256=digest,
                    uploaded_by=uploaded_by,
                )
                session.add(original)
                session.flush()
                original_file_id = original.file_id
            preview = self._previews.create(
                snapshot=snapshot,
                original_file_id=original_file_id,
                source_sha256=digest,
                uploaded_by=uploaded_by,
                replaces_preview_id=replaces_preview_id,
            )
            created_preview_id = preview.preview_id
            return self._previews.get(preview.preview_id)
        except Exception:
            for object_key in reversed(created_object_keys):
                self._file_store.delete(object_key=object_key)
            if original_file_id is not None:
                with self._sessions() as session, session.begin():
                    if created_preview_id is not None:
                        session.execute(
                            delete(RepairPreviewLine).where(
                                RepairPreviewLine.preview_id == created_preview_id
                            )
                        )
                        session.execute(
                            delete(RepairPreview).where(
                                RepairPreview.preview_id == created_preview_id
                            )
                        )
                    original_record = session.get(StoredFile, original_file_id)
                    if original_record is not None:
                        session.delete(original_record)
            raise
