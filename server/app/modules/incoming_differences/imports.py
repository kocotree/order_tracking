import hashlib
from copy import deepcopy
from io import BytesIO
from typing import Any
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    AuditLog,
    BackgroundJob,
    Factory,
    IdempotencyRecord,
    IncomingDiffBatch,
    IncomingDiffImportFile,
    IncomingDiffWorkbook,
    OrderAssignment,
    OrderDetail,
    StoredFile,
    User,
)
from app.modules.incoming_differences.duplicates import duplicate_evidence
from app.modules.incoming_differences.service import (
    IncomingDifferenceConflict,
    IncomingDifferencePermissionDenied,
    IncomingDifferenceService,
)
from app.modules.incoming_differences.workbook import (
    XLSX_MIME,
    IncomingWorkbookCodec,
    IncomingWorkbookValidationError,
)
from app.modules.infrastructure import utc_now

IMPORT_JOB = "incoming_diff.import"


class IncomingImportWorkflow:
    def __init__(self, sessions: sessionmaker[Session], *, files: PrivateFileStore,
                 codec: IncomingWorkbookCodec) -> None:
        self._sessions = sessions
        self._files = files
        self._codec = codec
        self._matching = IncomingDifferenceService(sessions)

    def receive(self, *, actor_id: str, chat_id: str, open_id: str, message_id: str,
                sent_at: int, attachments: list[dict[str, Any]]) -> str:
        now = utc_now()
        with self._sessions() as session, session.begin():
            actor = session.get(User, actor_id, with_for_update=True)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise IncomingDifferencePermissionDenied("只有已启用管理员可以导入")
            previous = session.scalar(select(IncomingDiffBatch).where(
                IncomingDiffBatch.source_message_id == message_id))
            if previous:
                if previous.submitter_id != actor_id or previous.feishu_chat_id != chat_id:
                    raise IncomingDifferencePermissionDenied("消息归属不一致")
                return previous.batch_id
            active = session.scalars(select(IncomingDiffBatch).where(
                IncomingDiffBatch.submitter_id == actor_id,
                IncomingDiffBatch.feishu_chat_id == chat_id,
                IncomingDiffBatch.status.not_in(["COLLECTING", "RECOGNIZING"]),
            ).order_by(IncomingDiffBatch.batch_id).with_for_update()).all()
            status = "VALIDATING"
            newest = max((old.source_sent_at or 0 for old in active), default=0)
            if sent_at < newest:
                status = "SUPERSEDED"
            elif sent_at == newest:
                status = "NEEDS_SELECTION"
            if status != "SUPERSEDED":
                for old in active:
                    if old.status not in {"CONFIRMED", "SUPERSEDED"}:
                        old.status = ("NEEDS_SELECTION" if status == "NEEDS_SELECTION"
                                      and old.source_kind == "FILE" else "SUPERSEDED")
                        old.review_revision += 1
            batch_id = str(uuid4())
            batch = IncomingDiffBatch(
                batch_id=batch_id, batch_no="IF" + uuid4().hex[:30],
                submitter_id=actor_id, feishu_chat_id=chat_id, feishu_open_id=open_id,
                source_kind="FILE", source_message_id=message_id, source_sent_at=sent_at,
                attachments=attachments, review_revision=0, status=status,
                created_at=now, updated_at=now,
            )
            session.add(batch)
            session.flush()
            session.add(BackgroundJob(job_type=IMPORT_JOB, dedupe_key=message_id,
                                      payload={"batchId": batch_id}, available_at=now))
            return batch_id

    def select_import(self, *, batch_id: str, actor_id: str) -> None:
        with self._sessions() as session, session.begin():
            actor = session.get(User, actor_id, with_for_update=True)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise IncomingDifferencePermissionDenied("只有已启用管理员可以选择导入")
            batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if (batch is None or batch.submitter_id != actor_id
                    or batch.status != "NEEDS_SELECTION"):
                raise IncomingDifferenceConflict("待选择的文件集合已失效")
            others = session.scalars(select(IncomingDiffBatch).where(
                IncomingDiffBatch.submitter_id == actor_id,
                IncomingDiffBatch.feishu_chat_id == batch.feishu_chat_id,
                IncomingDiffBatch.status == "NEEDS_SELECTION").with_for_update()).all()
            for other in others:
                other.status = "SUPERSEDED"
                other.review_revision += 1
            batch.status = "VALIDATING"
            if batch.current_workbook_id:
                workbook = session.get(IncomingDiffWorkbook, batch.current_workbook_id)
                assert workbook is not None
                batch.status = "FAILED" if workbook.validation_issues else "READY"
                if not workbook.validation_issues and any(
                    line.get("duplicates") and not line.get("decision")
                    for line in workbook.line_snapshot
                ):
                    batch.status = "NEEDS_DECISION"
            session.add(BackgroundJob(job_type=IMPORT_JOB,
                dedupe_key=f"{batch_id}:selected:{batch.review_revision}",
                payload={"batchId": batch_id}, available_at=utc_now()))

    def prepare(self, *, batch_id: str, contents: list[bytes]) -> None:
        object_keys: list[str] = []
        try:
            with self._sessions() as session, session.begin():
                batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
                if batch is None or batch.status != "VALIDATING":
                    return
                attachments = batch.attachments or []
                if not 1 <= len(attachments) <= 30 or len(contents) != len(attachments):
                    raise ValueError("附件数量无效或文件未收齐")
                if sum(map(len, contents)) > 100 * 1024 * 1024:
                    raise ValueError("本次全部文件大小超过100MiB")
                workbook = IncomingDiffWorkbook(
                    workbook_id=str(uuid4()), batch_id=batch_id, version=1, direction="IMPORTED",
                    file_id=None, content_sha256=hashlib.sha256(b"".join(
                        hashlib.sha256(content).digest() for content in contents)).hexdigest(),
                    line_snapshot=[], submitted_by=batch.submitter_id, submitted_at=utc_now(),
                )
                session.add(workbook)
                session.flush()
                lines: list[dict[str, Any]] = []
                issues: list[dict[str, Any]] = []
                uncompressed = 0
                for position, (attachment, content) in enumerate(
                    zip(attachments, contents, strict=True), 1
                ):
                    filename = str(attachment.get("file_name") or "")
                    if (not filename.lower().endswith(".xlsx") or len(filename) > 255
                            or attachment.get("is_folder") or not content
                            or len(content) > 20 * 1024 * 1024):
                        issues.append({"fileName": filename, "reason": "文件格式或大小无效"})
                        continue
                    file_id = str(uuid4())
                    object_key = f"incoming-differences/{batch_id}/imports/{file_id}.xlsx"
                    self._files.put(object_key=object_key, content=content, content_type=XLSX_MIME)
                    object_keys.append(object_key)
                    stored = StoredFile(
                        bucket=self._files.bucket, object_key=object_key,
                        original_filename=filename,
                        mime_type=XLSX_MIME, size_bytes=len(content),
                        content_sha256=hashlib.sha256(content).hexdigest(),
                        uploaded_by=batch.submitter_id,
                    )
                    session.add(stored)
                    session.flush()
                    session.add(IncomingDiffImportFile(
                        import_file_id=file_id, workbook_id=workbook.workbook_id,
                        file_id=stored.file_id, position=position,
                    ))
                    try:
                        with ZipFile(BytesIO(content)) as archive:
                            uncompressed += sum(entry.file_size for entry in archive.infolist())
                        if uncompressed > 100 * 1024 * 1024:
                            raise ValueError("本次全部文件解压大小超过100MiB")
                        parsed = self._codec.parse_import(content)
                    except BadZipFile:
                        issues.append({"fileName": filename, "reason": "Excel文件损坏"})
                        continue
                    except IncomingWorkbookValidationError as error:
                        issues.extend({"fileName": filename, "sheetName": item.get("sheet"),
                                       "rowNumber": item.get("row"), "reason": item["message"]}
                                      for item in error.issues)
                        continue
                    if len(lines) + len(parsed) > 5000:
                        raise ValueError("本次全部文件总行数超过5000行")
                    for line in parsed:
                        factory_id = session.scalar(select(Factory.factory_id).where(
                            Factory.factory_name == line["factoryName"],
                            Factory.is_enabled.is_(True)))
                        detail_id = self._matching.match_detail(
                            factory_id=factory_id, product_name=str(line["productName"]),
                            spec=str(line["spec"]),
                            purchase_order_id=str(line["purchaseOrderId"] or "") or None,
                        )
                        detail = session.get(OrderDetail, detail_id) if detail_id else None
                        line.update({"fileName": filename, "importFileId": file_id,
                                     "number": len(lines) + 1, "detailId": detail_id,
                                     "factoryId": factory_id,
                                     "variantId": detail.matched_variant_id if detail else None,
                                     "purchaseOrderItemId": (
                                         detail.purchase_order_item_id if detail else None)})
                        if detail:
                            line["purchaseOrderId"] = detail.purchase_order_id
                        else:
                            issues.append({**line, "reason": "未匹配到唯一订单明细"})
                        lines.append(line)
                if not issues:
                    evidence = duplicate_evidence(session, lines)
                    for entry in lines:
                        entry["duplicates"] = evidence.get(entry["number"], [])
                workbook.line_snapshot = lines
                workbook.validation_issues = issues
                batch.current_workbook_id = workbook.workbook_id
                batch.status = "FAILED" if issues else "READY"
                if not issues and any(line.get("duplicates") for line in lines):
                    batch.status = "NEEDS_DECISION"
                batch.updated_at = utc_now()
        except Exception:
            for object_key in object_keys:
                self._files.delete(object_key=object_key)
            raise

    def review_generated(self, *, batch_id: str, actor_id: str, version: int) -> None:
        with self._sessions() as session, session.begin():
            actor = session.get(User, actor_id, with_for_update=True)
            if actor is None or not actor.is_enabled or actor.role != "admin":
                raise IncomingDifferencePermissionDenied("只有已启用管理员可以核对登记")
            batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if (batch is None or batch.submitter_id != actor_id or batch.source_kind != "PHOTO"
                    or batch.status not in {"READY", "NEEDS_DECISION"}):
                raise IncomingDifferenceConflict("图片批次已失效，请使用最新文件清单")
            workbook = session.get(IncomingDiffWorkbook, batch.current_workbook_id)
            if workbook is None or workbook.version != version:
                raise IncomingDifferenceConflict("核对表已过期")
            lines = deepcopy(workbook.line_snapshot)
            if lines and all("number" in line for line in lines):
                return
            for number, line in enumerate(lines, 1):
                line.update(number=number, fileName=f"{batch.batch_no}_核对表.xlsx")
                if not line.get("detailId") and line.get("orderAssignmentId"):
                    assignment = session.get(OrderAssignment, line["orderAssignmentId"])
                    line["detailId"] = assignment.detail_id if assignment else None
            evidence = duplicate_evidence(session, lines)
            for line in lines:
                line["duplicates"] = evidence.get(line["number"], [])
            workbook.line_snapshot = lines
            batch.review_revision += 1
            batch.status = "NEEDS_DECISION" if evidence else "READY"

    def refresh_duplicates(self, batch_id: str) -> bool:
        with self._sessions() as session, session.begin():
            batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if batch is None or batch.status not in {"READY", "NEEDS_DECISION"}:
                return False
            workbook = session.get(IncomingDiffWorkbook, batch.current_workbook_id)
            if workbook is None or not all("number" in line for line in workbook.line_snapshot):
                return False
            lines = deepcopy(workbook.line_snapshot)
            evidence = duplicate_evidence(session, lines)
            changed = False
            for line in lines:
                candidates = evidence.get(line["number"], [])
                if candidates != line.get("duplicates", []):
                    line["duplicates"] = candidates
                    line.pop("decision", None)
                    changed = True
            if changed:
                workbook.line_snapshot = lines
                batch.review_revision += 1
                batch.status = "NEEDS_DECISION" if any(
                    line.get("duplicates") and not line.get("decision")
                    for line in lines) else "READY"
            return changed

    def decide(self, *, batch_id: str, actor_id: str, revision: int, message_id: str,
               decisions: list[dict[str, Any]], text: str = "") -> None:
        with self._sessions() as session, session.begin():
            actor = session.get(User, actor_id)
            batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if (actor is None or not actor.is_enabled or actor.role != "admin" or batch is None
                    or batch.submitter_id != actor_id):
                raise IncomingDifferencePermissionDenied("只能处理本人的导入")
            prior = session.scalar(select(IdempotencyRecord).where(
                IdempotencyRecord.scope == "incoming_diff_decision",
                IdempotencyRecord.idempotency_key == message_id))
            if prior:
                if not prior.result or prior.result.get("batchId") != batch_id:
                    raise IncomingDifferenceConflict("决定消息归属不一致")
                return
            if batch.status not in {"NEEDS_DECISION", "READY"} or batch.review_revision != revision:
                raise IncomingDifferenceConflict("重复清单已过期，请回复最新清单")
            workbook = session.get(IncomingDiffWorkbook, batch.current_workbook_id)
            assert workbook is not None
            lines = deepcopy(workbook.line_snapshot)
            eligible = {line["number"]: line for line in lines if line.get("duplicates")}
            seen: set[int] = set()
            if not decisions:
                raise ValueError("没有明确的重复处理决定")
            for decision in decisions:
                number = decision.get("number")
                action = decision.get("action")
                if (set(decision) != {"number", "action"} or type(number) is not int
                        or number not in eligible or number in seen
                        or action not in {"skip", "register_new"}):
                    raise ValueError("重复编号、动作无效或相互冲突")
                seen.add(number)
                eligible[number]["decision"] = action
            workbook.line_snapshot = lines
            batch.review_revision += 1
            batch.status = "NEEDS_DECISION" if any(
                not line.get("decision") for line in eligible.values()) else "READY"
            session.add(AuditLog(
                request_id=message_id[:64], action="incoming_diff_decided",
                target_type="incoming_diff_batch", target_id=batch_id, actor_id=actor_id,
                source_terminal="feishu-bot",
                changes={"revision": revision, "decisions": decisions, "text": text,
                         "model": "qwen3.5-flash", "promptVersion": "incoming-decisions-v1"},
            ))
            session.add(IdempotencyRecord(
                scope="incoming_diff_decision", idempotency_key=message_id,
                status="completed", result={"batchId": batch_id}))
