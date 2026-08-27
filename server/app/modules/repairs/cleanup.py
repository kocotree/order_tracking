from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import RepairOrder, RepairPreview, StoredFile


@dataclass(frozen=True)
class RepairPreviewCleanupResult:
    deleted_previews: int
    deleted_files: int


class RepairPreviewCleanupService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        file_store: PrivateFileStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._file_store = file_store
        self._clock = clock

    def run(self) -> RepairPreviewCleanupResult:
        now = self._clock().astimezone(UTC).replace(tzinfo=None)
        with self._session_factory() as session, session.begin():
            previews = session.scalars(
                select(RepairPreview)
                .where(
                    RepairPreview.status.in_(["READY", "INVALID"]),
                    RepairPreview.expires_at <= now,
                )
                .with_for_update()
            ).all()
            if not previews:
                return RepairPreviewCleanupResult(deleted_previews=0, deleted_files=0)

            file_ids = {preview.original_file_id for preview in previews}
            formally_referenced_file_ids = set(
                session.scalars(
                    select(RepairOrder.original_file_id).where(
                        RepairOrder.original_file_id.in_(file_ids)
                    )
                ).all()
            )
            temporary_files = session.scalars(
                select(StoredFile).where(
                    StoredFile.file_id.in_(file_ids - formally_referenced_file_ids)
                )
            ).all()

            for stored_file in temporary_files:
                self._file_store.delete(object_key=stored_file.object_key)
            for preview in previews:
                session.delete(preview)
            session.flush()
            for stored_file in temporary_files:
                session.delete(stored_file)

            return RepairPreviewCleanupResult(
                deleted_previews=len(previews),
                deleted_files=len(temporary_files),
            )
