import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.adapters.vision import (
    MODEL,
    IncomingDiffRecognizer,
    VisionRecognitionError,
    parse_vision_result,
)
from app.db.models import (
    BackgroundJob,
    Factory,
    IncomingDiffBatch,
    IncomingDiffImage,
    OrderAssignment,
    OrderDetail,
    StoredFile,
    User,
)
from app.modules.incoming_differences.service import IncomingDifferenceService

JOB_TYPE = "incoming_diff.recognize"


class IncomingDiffRecognitionService:
    def __init__(
        self, sessions: sessionmaker[Session], *, files: PrivateFileStore,
        recognizer: IncomingDiffRecognizer,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._files = files
        self._recognizer = recognizer
        self._clock = clock
        self._matching = IncomingDifferenceService(sessions)

    def add_image(
        self, *, batch_id: str, actor_id: str, file_id: int, feishu_image_key: str,
        feishu_message_id: str | None = None,
    ) -> IncomingDiffImage:
        with self._sessions() as session, session.begin():
            batch = self._owned_batch(session, batch_id, actor_id)
            if batch.status != "COLLECTING":
                raise ValueError("批次已冻结")
            stored = session.get(StoredFile, file_id)
            if stored is None:
                raise ValueError("图片文件不存在")
            previous = session.scalar(
                select(IncomingDiffImage.batch_id)
                .join(IncomingDiffBatch, IncomingDiffBatch.batch_id == IncomingDiffImage.batch_id)
                .where(
                    IncomingDiffImage.content_sha256 == stored.content_sha256,
                    IncomingDiffBatch.status == "CONFIRMED",
                    IncomingDiffImage.batch_id != batch_id,
                )
                .order_by(IncomingDiffBatch.confirmed_at, IncomingDiffBatch.batch_id)
                .limit(1)
            )
            sequence = session.scalar(select(func.count()).select_from(IncomingDiffImage).where(
                IncomingDiffImage.batch_id == batch_id
            )) or 0
            image = IncomingDiffImage(
                image_id=str(uuid4()), batch_id=batch_id, sort_order=sequence + 1,
                feishu_image_key=feishu_image_key, feishu_message_id=feishu_message_id,
                file_id=file_id, content_sha256=stored.content_sha256,
                ocr_status="PENDING", duplicate_of_batch_id=previous,
                created_at=self._clock().replace(tzinfo=None),
            )
            session.add(image)
            session.flush()
            return image

    def acknowledge_duplicate(self, *, batch_id: str, image_id: str, actor_id: str) -> None:
        with self._sessions() as session, session.begin():
            batch = self._owned_batch(session, batch_id, actor_id)
            if batch.status != "COLLECTING":
                raise ValueError("批次已冻结")
            image = session.get(IncomingDiffImage, image_id)
            if image is None or image.batch_id != batch_id or image.duplicate_of_batch_id is None:
                raise ValueError("没有待确认的重复图片")
            image.duplicate_ack_at = self._clock().replace(tzinfo=None)

    def freeze_and_enqueue(self, *, batch_id: str, actor_id: str) -> int:
        now = self._clock().replace(tzinfo=None)
        with self._sessions() as session, session.begin():
            batch = self._owned_batch(session, batch_id, actor_id)
            if batch.status != "COLLECTING":
                raise ValueError("批次已冻结")
            images = session.scalars(select(IncomingDiffImage).where(
                IncomingDiffImage.batch_id == batch_id
            )).all()
            if not images:
                raise ValueError("批次没有图片")
            if any(image.ocr_status == "FAILED" for image in images):
                raise ValueError("批次含有读取失败的图片")
            if any(image.duplicate_of_batch_id and not image.duplicate_ack_at for image in images):
                raise ValueError("重复图片需管理员明确继续核对")
            batch.status = "RECOGNIZING"
            batch.frozen_at = now
            batch.updated_at = now
            job = BackgroundJob(
                job_type=JOB_TYPE, dedupe_key=batch_id, payload={"batchId": batch_id},
                status="pending", available_at=now, created_at=now, updated_at=now,
            )
            session.add(job)
            session.flush()
            return job.id

    def recognize(self, payload: dict[str, Any]) -> None:
        batch_id = payload.get("batchId")
        if not isinstance(batch_id, str) or not batch_id:
            raise ValueError("invalid_recognition_job")
        with self._sessions() as session:
            batch = session.get(IncomingDiffBatch, batch_id)
            if batch is None or batch.status != "RECOGNIZING":
                raise ValueError("invalid_recognition_batch")
            image_ids = session.scalars(
                select(IncomingDiffImage.image_id).where(
                    IncomingDiffImage.batch_id == batch_id,
                    IncomingDiffImage.ocr_status == "PENDING",
                ).order_by(IncomingDiffImage.sort_order)
            ).all()
        for image_id in image_ids:
            with self._sessions() as session:
                image = session.get(IncomingDiffImage, image_id)
                assert image is not None
                stored = session.get(StoredFile, image.file_id)
                assert stored is not None
                content = self._files.get(object_key=stored.object_key)
                if hashlib.sha256(content).hexdigest() != image.content_sha256:
                    raise VisionRecognitionError("image_hash_mismatch")
                mime_type = stored.mime_type
            parsed = parse_vision_result(
                self._recognizer.recognize(content=content, mime_type=mime_type)
            )
            factory_name = parsed["factoryName"]
            with self._sessions() as session:
                factory_id = session.scalar(select(Factory.factory_id).where(
                    Factory.factory_name == factory_name, Factory.is_enabled.is_(True)
                )) if factory_name else None
            for line in parsed["lines"]:
                spec = (f"{line['color']} / {line['size']}" if line["color"] and line["size"]
                        else line["color"] or None)
                assignment_id = self._matching.match_assignment(
                    factory_id=factory_id, product_code=parsed["productCode"],
                    product_name=parsed["productName"], spec=spec,
                )
                line["orderAssignmentId"] = assignment_id
                line["purchaseOrderId"] = None
                line["purchaseOrderItemId"] = None
                if assignment_id is not None:
                    with self._sessions() as session:
                        assignment = session.get(OrderAssignment, assignment_id)
                        assert assignment is not None and assignment.detail_id is not None
                        detail = session.get(OrderDetail, assignment.detail_id)
                        assert detail is not None
                        line["purchaseOrderId"] = detail.purchase_order_id
                        line["purchaseOrderItemId"] = detail.purchase_order_item_id
            with self._sessions() as session, session.begin():
                image = session.get(IncomingDiffImage, image_id)
                assert image is not None
                image.recognition_payload = parsed
                image.recognition_model = MODEL
                image.recognition_finished_at = self._clock().replace(tzinfo=None)
                image.ocr_status = "SUCCEEDED"
                image.failure_reason = None

    def fail_terminal(self, payload: dict[str, Any], error: Exception) -> None:
        batch_id = payload.get("batchId")
        if not isinstance(batch_id, str):
            return
        reason = (error.args[0] if isinstance(error, VisionRecognitionError)
                  else "recognition_failed")
        if not isinstance(reason, str) or len(reason) > 64:
            reason = "recognition_failed"
        now = self._clock().replace(tzinfo=None)
        with self._sessions() as session, session.begin():
            batch = session.get(IncomingDiffBatch, batch_id)
            if batch is None or batch.status != "RECOGNIZING":
                return
            pending = session.scalars(select(IncomingDiffImage).where(
                IncomingDiffImage.batch_id == batch_id,
                IncomingDiffImage.ocr_status == "PENDING",
            ).order_by(IncomingDiffImage.sort_order)).all()
            for image in pending:
                image.ocr_status = "FAILED"
                image.recognition_model = MODEL
                image.recognition_finished_at = now
                image.failure_reason = reason
            batch.status = "FAILED"
            batch.recognition_error_code = reason
            batch.recognition_error_summary = (
                f"第 {pending[0].sort_order} 张图片识别失败" if pending else "图片识别失败"
            )
            batch.updated_at = now

    @staticmethod
    def _owned_batch(session: Session, batch_id: str, actor_id: str) -> IncomingDiffBatch:
        batch = session.get(IncomingDiffBatch, batch_id)
        actor = session.get(User, actor_id)
        if (batch is None or actor is None or actor.role != "admin"
                or not actor.is_enabled or batch.submitter_id != actor_id):
            raise ValueError("没有权限操作此批次")
        return batch


class IncomingDiffRecognitionWorkerHandlers:
    def __init__(self, service: IncomingDiffRecognitionService) -> None:
        self._service = service

    def handlers(self) -> Mapping[str, Callable[[dict[str, Any]], None]]:
        return {JOB_TYPE: self._service.recognize}

    def terminal_failure_handlers(
        self,
    ) -> Mapping[str, Callable[[dict[str, Any], Exception], None]]:
        return {JOB_TYPE: self._service.fail_terminal}
