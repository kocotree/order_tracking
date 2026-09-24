import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from typing import Protocol
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    ExternalIdentity,
    Factory,
    IncomingDiffBatch,
    IncomingDiffImage,
    IncomingDiffWorkbook,
    OrderDetail,
    OutboxMessage,
    StoredFile,
    User,
)
from app.modules.incoming_differences.recognition import IncomingDiffRecognitionService
from app.modules.incoming_differences.service import (
    IncomingDifferenceError,
    IncomingDifferenceService,
    IncomingDifferenceValidationError,
)
from app.modules.incoming_differences.workbook import (
    IncomingWorkbookCodec,
    IncomingWorkbookValidationError,
)
from app.modules.incoming_differences.workbook_workflow import IncomingWorkbookWorkflow
from app.modules.infrastructure import InfrastructureStore, utc_now

CONFIRM_JOB = "incoming_diff.confirm"
REGENERATE_JOB = "incoming_diff.regenerate"
MAX_MEDIA_BYTES = 20 * 1024 * 1024
DENIED = "当前账号无权提交或确认来货出入，请联系管理员。"


class FeishuBotMedia(Protocol):
    def download_resource(self, message_id: str, file_key: str,
                          resource_type: str) -> bytes: ...


class FeishuCallbackVerifier:
    def __init__(self, encrypt_key: str, verification_token: str, *,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._key = encrypt_key
        self._token = verification_token
        self._now = now

    def verify(self, headers: dict[str, str], body: bytes) -> dict[str, object]:
        timestamp = headers.get("x-lark-request-timestamp", "")
        nonce = headers.get("x-lark-request-nonce", "")
        signature = headers.get("x-lark-signature", "")
        if signature:
            if not timestamp.isdecimal() or abs(self._now().timestamp() - int(timestamp)) > 300:
                raise ValueError("callback timestamp invalid")
            expected = hashlib.sha256((timestamp + nonce + self._key).encode() + body).hexdigest()
            if not nonce or not hmac.compare_digest(expected, signature):
                raise ValueError("callback signature invalid")
        try:
            wrapper = json.loads(body)
            if not isinstance(wrapper, dict):
                raise ValueError("callback decrypt invalid")
            if "encrypt" not in wrapper and signature:
                payload = wrapper
            else:
                if not isinstance(wrapper.get("encrypt"), str):
                    raise ValueError("callback decrypt invalid")
                encrypted = base64.b64decode(wrapper["encrypt"], validate=True)
                if len(encrypted) < 32 or (len(encrypted) - 16) % 16:
                    raise ValueError("callback decrypt invalid")
                decryptor = Cipher(
                    algorithms.AES(hashlib.sha256(self._key.encode()).digest()),
                    modes.CBC(encrypted[:16]),
                ).decryptor()
                padded = decryptor.update(encrypted[16:]) + decryptor.finalize()
                unpadder = padding.PKCS7(128).unpadder()
                payload = json.loads(unpadder.update(padded) + unpadder.finalize())
            if not isinstance(payload, dict):
                raise ValueError("callback decrypt invalid")
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError("callback decrypt invalid") from error
        header = payload.get("header")
        if header is not None and not isinstance(header, dict):
            raise ValueError("callback verification token invalid")
        token = payload.get("token") or (header or {}).get("token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            raise ValueError("callback verification token invalid")
        if not signature and payload.get("type") != "url_verification":
            raise ValueError("callback signature invalid")
        return payload


class FeishuBotService:
    def __init__(
        self, sessions: sessionmaker[Session], *, files: PrivateFileStore,
        media: FeishuBotMedia, identity_scope: str, codec: IncomingWorkbookCodec,
        recognition: IncomingDiffRecognitionService,
    ) -> None:
        self._sessions = sessions
        self._files = files
        self._media = media
        self._identity_scope = identity_scope
        self._recognition = recognition
        self._workbooks = IncomingWorkbookWorkflow(sessions, file_store=files, codec=codec)
        self._registration = IncomingDifferenceService(sessions)
        self._store = InfrastructureStore(sessions)

    def event(self, payload: dict[str, object]) -> dict[str, object]:
        header = payload.get("header")
        event = payload.get("event")
        if not isinstance(header, dict) or not isinstance(event, dict):
            return {}
        if header.get("event_type") != "im.message.receive_v1":
            return {}
        sender = event.get("sender")
        message = event.get("message")
        if not isinstance(sender, dict) or not isinstance(message, dict):
            return {}
        sender_id = sender.get("sender_id")
        open_id = sender_id.get("open_id") if isinstance(sender_id, dict) else None
        chat_id = message.get("chat_id")
        message_id = message.get("message_id")
        kind = message.get("message_type")
        if (not isinstance(open_id, str) or not open_id or
                not isinstance(chat_id, str) or not chat_id or
                not isinstance(message_id, str) or not message_id or
                message.get("chat_type") != "p2p" or kind not in {"image", "file"}):
            return {}
        try:
            content = json.loads(str(message.get("content", "")))
        except ValueError:
            return {}
        if not isinstance(content, dict):
            return {}
        file_key = content.get("image_key" if kind == "image" else "file_key")
        filename = content.get("file_name") if kind == "file" else None
        if (not isinstance(file_key, str) or not file_key or
                (kind == "file" and (not isinstance(filename, str) or
                 not filename.endswith(".xlsx")))):
            return {}
        event_id = header.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            return {}
        if not self._store.reserve_idempotency(scope="feishu_event", key=event_id):
            return {}
        actor_id = self._actor(open_id, header.get("tenant_key"))
        if actor_id is None:
            self._reply(None, open_id, message_id, DENIED)
            return {}
        if kind == "image":
            self._image(actor_id, open_id, chat_id, message_id, file_key)
        else:
            assert isinstance(filename, str)
            self._uploaded(actor_id, open_id, chat_id, message_id, file_key, filename)
        return {}

    def release_failed_event(self, payload: dict[str, object]) -> None:
        header = payload.get("header", payload)
        if isinstance(header, dict) and isinstance(header.get("event_id"), str):
            self._store.release_idempotency(scope="feishu_event", key=header["event_id"])

    def card_action(self, payload: dict[str, object]) -> dict[str, object]:
        header = payload.get("header", payload)
        event = payload.get("event", payload)
        if not isinstance(header, dict) or not isinstance(event, dict):
            return {}
        if header.get("event_type") != "card.action.trigger":
            return {}
        operator = event.get("operator")
        action = event.get("action")
        open_id = operator.get("open_id") if isinstance(operator, dict) else None
        value = action.get("value") if isinstance(action, dict) else None
        if not isinstance(open_id, str) or not isinstance(value, dict):
            return {}
        operation = value.get("action")
        batch_id = value.get("batchId")
        if (operation not in {"generate", "confirm", "regenerate", "continue"}
                or not isinstance(batch_id, str)):
            return {}
        event_id = header.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            return {}
        if not self._store.reserve_idempotency(scope="feishu_event", key=event_id):
            return self._toast("正在处理")
        tenant_key = operator.get("tenant_key") if isinstance(operator, dict) else None
        actor_id = self._actor(open_id, tenant_key or header.get("tenant_key"))
        if actor_id is None:
            self._reply(None, open_id, event_id, DENIED)
            return self._toast(DENIED)
        with self._sessions() as session:
            batch = session.get(IncomingDiffBatch, batch_id)
            if batch is None:
                return self._toast("批次不存在")
            if batch.submitter_id != actor_id:
                owner = session.get(User, batch.submitter_id)
                owner_name = owner.feishu_display_name if owner else "提交人"
                self._reply(actor_id, open_id, event_id,
                            f"批次 {batch.batch_no} 由 {owner_name} 提交，只能由提交人确认。")
                return self._toast("只能操作本人批次")
            batch_no = batch.batch_no
        if operation == "generate":
            try:
                self._recognition.freeze_and_enqueue(batch_id=batch_id, actor_id=actor_id)
            except ValueError:
                return self._toast("批次无法生成核对表")
            with self._sessions() as session:
                count = session.scalar(select(func.count()).select_from(IncomingDiffImage).where(
                    IncomingDiffImage.batch_id == batch_id)) or 0
            self._reply(actor_id, open_id, event_id,
                        f"已冻结本批次 {count} 张图片，正在识别，请稍候。", batch_id=batch_id)
        elif operation == "continue":
            image_id = value.get("imageId")
            if not isinstance(image_id, str):
                return self._toast("图片不存在")
            self._recognition.acknowledge_duplicate(batch_id=batch_id, image_id=image_id,
                                                     actor_id=actor_id)
        elif operation == "regenerate":
            self._store.enqueue_job(
                job_type=REGENERATE_JOB, dedupe_key=event_id,
                payload={"batchId": batch_id, "actorId": actor_id},
                available_at=utc_now(),
            )
        else:
            version = value.get("version")
            if not isinstance(version, int) or isinstance(version, bool):
                return self._toast("核对表版本无效")
            with self._sessions() as session:
                current_batch = session.get(IncomingDiffBatch, batch_id)
                assert current_batch is not None
                if current_batch.status == "CONFIRMED":
                    result = self._registration.confirm(batch_id=batch_id,
                                                        workbook_version=version, actor_id=actor_id)
                    operator = session.get(User, result.confirmed_by)
                    operator_name = operator.feishu_display_name if operator else "提交人"
                    self._reply(
                        actor_id, open_id, event_id,
                        f"批次 {batch_no} 已于 {result.confirmed_at:%Y-%m-%d %H:%M} "
                        f"由 {operator_name} 确认登记，本次不重复生效。",
                    )
                    return self._toast("已登记")
            self._store.enqueue_job(job_type=CONFIRM_JOB, dedupe_key=f"{batch_id}:{version}",
                                    payload={"batchId": batch_id, "version": version,
                                             "actorId": actor_id, "openId": open_id},
                                    available_at=utc_now())
        return self._toast("正在处理")

    def _actor(self, open_id: str, tenant_key: object) -> str | None:
        if not isinstance(tenant_key, str) or not tenant_key:
            return None
        with self._sessions() as session:
            return session.scalar(
                select(User.user_id)
                .join(ExternalIdentity, ExternalIdentity.user_id == User.user_id)
                .where(ExternalIdentity.platform == "feishu",
                       ExternalIdentity.scope == self._identity_scope,
                       ExternalIdentity.platform_subject == f"{tenant_key}:{open_id}",
                       User.role == "admin", User.is_enabled.is_(True))
            )

    def _batch(self, actor_id: str, chat_id: str, *, status: str) -> IncomingDiffBatch | None:
        with self._sessions() as session:
            return session.scalar(select(IncomingDiffBatch).where(
                IncomingDiffBatch.submitter_id == actor_id,
                IncomingDiffBatch.feishu_chat_id == chat_id,
                IncomingDiffBatch.status == status,
            ).order_by(
                IncomingDiffBatch.created_at.desc(), IncomingDiffBatch.batch_id.desc()
            ).limit(1))

    def _image(self, actor_id: str, open_id: str, chat_id: str,
               message_id: str, image_key: str) -> None:
        with self._sessions() as session:
            if session.scalar(select(IncomingDiffImage.image_id).where(
                IncomingDiffImage.feishu_message_id == message_id,
            )) is not None:
                return
        batch = self._batch(actor_id, chat_id, status="COLLECTING")
        batch_id = (batch.batch_id if batch else
                    self._registration.create_batch(submitter_id=actor_id,
                                                    feishu_chat_id=chat_id,
                                                    feishu_open_id=open_id).batch_id)
        object_key = f"incoming-differences/{batch_id}/images/{uuid4()}"
        try:
            content = self._media.download_resource(message_id, image_key, "image")
            if not content or len(content) > MAX_MEDIA_BYTES:
                raise ValueError("image_size_invalid")
            with Image.open(BytesIO(content)) as picture:
                if picture.format not in {"JPEG", "PNG"}:
                    raise ValueError("image_type_invalid")
                mime_type = "image/jpeg" if picture.format == "JPEG" else "image/png"
                picture.verify()
        except (httpx.HTTPError, ValueError, UnidentifiedImageError, OSError):
            with self._sessions() as session, session.begin():
                current = session.get(IncomingDiffBatch, batch_id)
                assert current is not None
                count = session.scalar(select(func.count()).select_from(IncomingDiffImage).where(
                    IncomingDiffImage.batch_id == batch_id)) or 0
                session.add(IncomingDiffImage(
                    image_id=str(uuid4()), batch_id=batch_id, sort_order=count + 1,
                    feishu_image_key=image_key, feishu_message_id=message_id,
                    file_id=None, content_sha256=hashlib.sha256(b"").hexdigest(),
                    ocr_status="FAILED", failure_reason="download_failed", created_at=utc_now()))
                current.status = "FAILED"
            self._reply(
                actor_id, open_id, message_id,
                f"第 {count + 1} 张图片无法识别（图片读取失败），"
                "本批次未生成核对表。请重拍后重新发送。",
                batch_id=batch_id,
            )
            return
        self._files.put(object_key=object_key, content=content, content_type=mime_type)
        with self._sessions() as session, session.begin():
            stored = StoredFile(bucket=self._files.bucket, object_key=object_key,
                                original_filename="feishu-image", mime_type=mime_type,
                                size_bytes=len(content),
                                content_sha256=hashlib.sha256(content).hexdigest(),
                                uploaded_by=actor_id)
            session.add(stored)
            session.flush()
            file_id = stored.file_id
        try:
            image = self._recognition.add_image(batch_id=batch_id, actor_id=actor_id,
                                                file_id=file_id, feishu_image_key=image_key,
                                                feishu_message_id=message_id)
        except Exception:
            with self._sessions() as session, session.begin():
                cleanup_file = session.get(StoredFile, file_id)
                if cleanup_file is not None:
                    session.delete(cleanup_file)
            self._files.delete(object_key=object_key)
            raise
        if image.duplicate_of_batch_id:
            with self._sessions() as session:
                old = session.get(IncomingDiffBatch, image.duplicate_of_batch_id)
                old_no = old.batch_no if old else image.duplicate_of_batch_id
            self._reply(
                actor_id, open_id, message_id,
                f"第 {image.sort_order} 张图片与批次 {old_no} 的图片内容相同。"
                "如确认是另一次实际差异，点击“继续核对”；否则请移除该图片。",
                batch_id=batch_id,
                buttons=[("继续核对", "continue", {"imageId": image.image_id})],
            )
        else:
            self._reply(actor_id, open_id, message_id,
                        f"已收到第 {image.sort_order} 张图片。继续发送，或点击“生成核对表”。",
                        batch_id=batch_id, buttons=[("生成核对表", "generate", {})])

    def _uploaded(self, actor_id: str, open_id: str, chat_id: str,
                  message_id: str, file_key: str, filename: str) -> None:
        with self._sessions() as session:
            batches = session.scalars(select(IncomingDiffBatch).where(
                IncomingDiffBatch.submitter_id == actor_id,
                IncomingDiffBatch.feishu_chat_id == chat_id,
                IncomingDiffBatch.status == "READY",
            )).all()
            batch = next((item for item in batches if filename.startswith(
                f"{item.batch_no}_核对表_v")), None)
            if batch is None or batch.current_workbook_id is None:
                return
            workbook = session.get(IncomingDiffWorkbook, batch.current_workbook_id)
            assert workbook is not None
            version = workbook.version
        try:
            content = self._media.download_resource(message_id, file_key, "file")
            if not content or len(content) > MAX_MEDIA_BYTES:
                raise ValueError("workbook_size_invalid")
            uploaded = self._workbooks.upload(batch_id=batch.batch_id, version=version,
                                              actor_id=actor_id, content=content)
        except IncomingWorkbookValidationError as error:
            self._reply(actor_id, open_id, message_id,
                        self._workbook_errors(batch.batch_no, error.issues),
                        batch_id=batch.batch_id,
                        buttons=[("重新生成", "regenerate", {})])
            return
        except (httpx.HTTPError, ValueError):
            self._reply(
                actor_id, open_id, message_id,
                f"这份核对表不是批次 {batch.batch_no} 的最新有效版本（校验失败），已拒绝。"
                "请使用最新版本重新修改，或点击“重新生成”。",
                batch_id=batch.batch_id, buttons=[("重新生成", "regenerate", {})],
            )
            return
        self._reply(actor_id, open_id, message_id,
                    f"已收到修改后的核对表，校验通过，本批次最新版本为 V{uploaded.version}。",
                    batch_id=batch.batch_id,
                    buttons=[("确认登记", "confirm", {"version": uploaded.version})])

    def recognition_job(self, payload: dict[str, object]) -> None:
        self._recognition.recognize(payload)
        batch_id = str(payload["batchId"])
        with self._sessions() as session, session.begin():
            batch = session.get(IncomingDiffBatch, batch_id)
            assert batch is not None and batch.status == "RECOGNIZING"
            batch.status = "READY"
            actor_id = batch.submitter_id
        self._generate(batch_id, actor_id)

    def recognition_failed(self, payload: dict[str, object], error: Exception) -> None:
        self._recognition.fail_terminal(payload, error)
        batch_id = str(payload["batchId"])
        with self._sessions() as session, session.begin():
            batch = session.get(IncomingDiffBatch, batch_id)
            if batch is None:
                return
            batch.status = "FAILED"
            if batch.feishu_open_id:
                failed = session.scalar(select(IncomingDiffImage.sort_order).where(
                    IncomingDiffImage.batch_id == batch_id,
                    IncomingDiffImage.ocr_status == "FAILED",
                ).order_by(IncomingDiffImage.sort_order).limit(1)) or 1
                self._queue(session, batch.submitter_id, batch.feishu_open_id,
                            f"recognition-failed:{batch_id}",
                            f"第 {failed} 张图片无法识别（识别失败），"
                            "本批次未生成核对表。请重拍后重新发送。",
                            batch_id=batch_id)

    def _generate(self, batch_id: str, actor_id: str, *, regenerate: bool = False) -> None:
        with self._sessions() as session:
            batch = session.get(IncomingDiffBatch, batch_id)
            assert batch is not None and batch.feishu_open_id is not None
            images = session.scalars(select(IncomingDiffImage).where(
                IncomingDiffImage.batch_id == batch_id
            ).order_by(IncomingDiffImage.sort_order)).all()
            lines: list[dict[str, object]] = []
            for image in images:
                parsed = image.recognition_payload
                if image.ocr_status != "SUCCEEDED" or not isinstance(parsed, dict):
                    raise ValueError("image_recognition_incomplete")
                for line in parsed["lines"]:
                    spec = (f"{line['color']} / {line['size']}"
                            if line["color"] and line["size"] else line["color"] or "")
                    lines.append({
                        "imageId": image.image_id, "factoryName": parsed.get("factoryName"),
                        "productName": parsed.get("productName"),
                        "productCode": parsed.get("productCode"),
                        "spec": spec, "quantity": line["signedQuantity"],
                        "purchaseOrderId": line.get("purchaseOrderId"),
                        "purchaseOrderItemId": line.get("purchaseOrderItemId"),
                        "orderAssignmentId": line.get("orderAssignmentId"),
                    })
            open_id = batch.feishu_open_id
            batch_no = batch.batch_no
        workbook = self._workbooks.generate(batch_id=batch_id, actor_id=actor_id,
                                             lines=lines, regenerate=regenerate)
        pending = sum(not line.get("orderAssignmentId") for line in lines)
        self._reply(
            actor_id, open_id, f"generated:{workbook.workbook_id}",
            f"批次 {batch_no} 核对表已生成：共 {len(lines)} 条明细，{pending} 条待确认。"
            "核对无误可直接确认；需要修改请下载后重新发送本表。",
            batch_id=batch_id,
            buttons=[("确认登记", "confirm", {"version": workbook.version}),
                     ("重新生成", "regenerate", {})], file_id=workbook.file_id,
        )
        unknown_factory = sum(not line.get("factoryName") for line in lines)
        problems: list[str] = []
        if unknown_factory:
            problems.append(
                f"{unknown_factory} 条明细无法确定工厂，已放入“待确认”Sheet。"
                "请把它们移动到对应工厂 Sheet 后重新发送本表。"
            )
        for line in workbook.line_snapshot:
            missing = "、".join(name for name, field in (("名称", "productName"),
                               ("规格", "spec")) if not line.get(field))
            if missing:
                problems.append(
                    f"{line['sheetName']} 第 {line['rowNumber']} 行缺少 {missing}，"
                    "已标记待确认。系统不会替你猜测，请补全后重新发送。"
                )
        if problems:
            summary = "\n".join(problems[:10])
            if len(problems) > 10:
                summary += f"\n另有 {len(problems) - 10} 条错误未展示。"
            self._reply(
                actor_id, open_id, f"factory-pending:{workbook.workbook_id}",
                summary, batch_id=batch_id,
            )

    def confirm_job(self, payload: dict[str, object]) -> None:
        batch_id = str(payload["batchId"])
        raw_version = payload["version"]
        if not isinstance(raw_version, int) or isinstance(raw_version, bool):
            raise ValueError("invalid_confirm_job")
        version = raw_version
        actor_id = str(payload["actorId"])
        open_id = str(payload["openId"])
        try:
            result = self._registration.confirm(batch_id=batch_id, workbook_version=version,
                                                actor_id=actor_id)
        except IncomingDifferenceValidationError as error:
            with self._sessions() as session:
                batch = session.get(IncomingDiffBatch, batch_id)
                current = (session.get(IncomingDiffWorkbook, batch.current_workbook_id)
                           if batch and batch.current_workbook_id else None)
                lines = current.line_snapshot if current else []
            self._reply(actor_id, open_id, f"confirm-error:{batch_id}:{version}",
                        self._registration_errors(error.issues, lines), batch_id=batch_id)
            return
        except IncomingDifferenceError as error:
            self._reply(actor_id, open_id, f"confirm-error:{batch_id}:{version}",
                        str(error)[:400], batch_id=batch_id)
            return
        if result.replayed:
            message = (f"批次 {result.batch_no} 已于 {result.confirmed_at:%Y-%m-%d %H:%M} "
                       "由提交人确认登记，本次不重复生效。")
        else:
            message = (f"批次 {result.batch_no} 已正式登记 {result.record_count} 条来货出入，"
                       f"已通知 {result.factory_count} 个工厂。")
        self._reply(actor_id, open_id, f"confirmed:{batch_id}:{version}", message,
                    batch_id=batch_id)

    def regenerate_job(self, payload: dict[str, object]) -> None:
        self._generate(str(payload["batchId"]), str(payload["actorId"]), regenerate=True)

    @staticmethod
    def _workbook_errors(batch_no: str, issues: list[dict[str, str | int]]) -> str:
        messages: list[str] = []
        for issue in issues[:10]:
            sheet = issue.get("sheet", "核对表")
            row = issue.get("row", 0)
            code = issue.get("code")
            reason = issue.get("message", "校验失败")
            if code == "missing_token":
                messages.append(
                    f"{sheet} 第 {row} 行是手工新增的，没有来源图片标识，本批次未登记。"
                    "漏识别的明细请重新拍照发送，不要在表里加行。"
                )
            elif code == "required_field":
                messages.append(
                    f"{sheet} 第 {row} 行缺少 {issue.get('field', '名称或规格')}，已标记待确认。"
                    "系统不会替你猜测，请补全后重新发送。"
                )
            else:
                messages.append(
                    f"这份核对表不是批次 {batch_no} 的最新有效版本（{reason}），已拒绝。"
                    "请使用最新版本重新修改，或点击“重新生成”。"
                )
        if len(issues) > 10:
            messages.append(f"另有 {len(issues) - 10} 条错误未展示。")
        return "\n".join(messages)

    def _registration_errors(
        self, issues: list[dict[str, object]], lines: list[dict[str, object]]
    ) -> str:
        messages: list[str] = []
        for issue in issues[:10]:
            sheet = issue.get("sheetName", "核对表")
            row = issue.get("rowNumber", 0)
            reason = str(issue.get("reason", "校验失败"))
            source = next((line for line in lines if line.get("sheetName") == sheet
                           and line.get("rowNumber") == row), None)
            if "小于 0" in reason:
                raw_quantity = source.get("quantity") if source else None
                quantity = abs(raw_quantity) if isinstance(raw_quantity, int) else 0
                messages.append(
                    f"{sheet} 第 {row} 行少 {quantity} 件会使该规格已发数量小于 0，"
                    "本批次未登记。"
                )
            elif source and source.get("purchaseOrderId") and reason == "未匹配到唯一派工":
                po = str(source["purchaseOrderId"])
                with self._sessions() as session:
                    factory_id = session.scalar(select(Factory.factory_id).where(
                        Factory.factory_name == sheet, Factory.is_enabled.is_(True),
                    ))
                    suborders = set(session.scalars(select(
                        OrderDetail.purchase_order_item_id
                    ).where(OrderDetail.purchase_order_id == po,
                            OrderDetail.purchase_order_item_id.is_not(None))).all())
                # ponytail: 错误路径逐个复用现有匹配器；子单量变大时再合并查询。
                count = sum(self._registration.match_assignment(
                    factory_id=factory_id,
                    product_code=(str(source["productCode"])
                                  if source.get("productCode") else None),
                    product_name=str(source.get("productName") or ""),
                    spec=str(source.get("spec") or ""), purchase_order_id=po,
                    purchase_order_item_id=suborder,
                ) is not None for suborder in suborders if suborder)
                if count > 1:
                    messages.append(
                        f"{sheet} 第 {row} 行的采购单号 {po} 存在 {count} 个符合条件的子单，"
                        "无法确定归属。请补充或修正后重新发送。"
                    )
                    continue
                messages.append(
                    f"{sheet} 第 {row} 行未能唯一匹配订单明细，本批次未登记。"
                )
            else:
                messages.append(
                    f"{sheet} 第 {row} 行未能唯一匹配订单明细，本批次未登记。"
                )
        if len(issues) > 10:
            messages.append(f"另有 {len(issues) - 10} 条错误未展示。")
        return "\n".join(messages) or "本批次没有可登记的明细，未登记。"

    def _reply(self, actor_id: str | None, open_id: str, key: str, message: str, *,
               batch_id: str = "", buttons: list[tuple[str, str, dict[str, object]]] | None = None,
               file_id: int | None = None) -> None:
        with self._sessions() as session, session.begin():
            self._queue(session, actor_id, open_id, key, message, batch_id=batch_id,
                        buttons=buttons, file_id=file_id)

    @staticmethod
    def _queue(session: Session, actor_id: str | None, open_id: str, key: str,
               message: str, *, batch_id: str = "",
               buttons: list[tuple[str, str, dict[str, object]]] | None = None,
               file_id: int | None = None) -> None:
        dedupe_key = f"incoming-diff-bot:{key}"
        if session.scalar(select(OutboxMessage.id).where(OutboxMessage.dedupe_key == dedupe_key)):
            return
        session.add(OutboxMessage(
            event_type="incoming_diff.bot_reply", aggregate_type="incoming_diff_batch",
            aggregate_id=batch_id or key[:100], dedupe_key=dedupe_key,
            payload={"templateKey": "incoming_diff_bot", "title": "来货出入",
                     "summary": message, "targetType": "incoming_diff_batch",
                     "targetId": batch_id, "targetPath": "", "templateData": {},
                     "recipientOpenId": open_id,
                     "buttons": [{"text": text, "action": action,
                                  "value": {"batchId": batch_id, **value}}
                                 for text, action, value in buttons or []],
                     "fileId": file_id},
            message_kind="delivery", channel="feishu", recipient_id=actor_id,
            available_at=utc_now()))

    @staticmethod
    def _toast(message: str) -> dict[str, object]:
        return {"toast": {"type": "info", "content": message}}
