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

from app.adapters.incoming_decisions import IncomingDecisionParser
from app.adapters.private_files import PrivateFileStore
from app.db.models import (
    ExternalIdentity,
    Factory,
    IdempotencyRecord,
    IncomingDiffBatch,
    IncomingDiffImage,
    IncomingDiffWorkbook,
    OrderDetail,
    OutboxMessage,
    StoredFile,
    User,
)
from app.modules.incoming_differences.imports import IncomingImportWorkflow
from app.modules.incoming_differences.recognition import IncomingDiffRecognitionService
from app.modules.incoming_differences.service import (
    IncomingDifferenceError,
    IncomingDifferenceService,
    IncomingDifferenceValidationError,
)
from app.modules.incoming_differences.workbook import (
    IncomingWorkbookCodec,
    IncomingWorkbookLimits,
    IncomingWorkbookValidationError,
)
from app.modules.incoming_differences.workbook_workflow import IncomingWorkbookWorkflow
from app.modules.infrastructure import InfrastructureStore, utc_now

CONFIRM_JOB = "incoming_diff.confirm"
REGENERATE_JOB = "incoming_diff.regenerate"
DECISION_JOB = "incoming_diff.decision"
MAX_MEDIA_BYTES = 20 * 1024 * 1024
MAX_WORKBOOK_BYTES = IncomingWorkbookLimits().max_source_bytes
DENIED = "当前账号无权提交或确认来货出入，请联系管理员。"


class FeishuBotMedia(Protocol):
    def download_resource(self, message_id: str, file_key: str,
                          resource_type: str) -> bytes: ...

    def read_own_message(self, message_id: str, chat_id: str) -> str: ...


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
            try:
                if timestamp.isascii() and timestamp.isdecimal():
                    sent_at: float = int(timestamp)
                else:
                    parts = timestamp.split()
                    if len(parts) != 5 or not parts[3].isalpha() or not parts[4].startswith("m="):
                        raise ValueError("callback timestamp invalid")
                    parsed = datetime.fromisoformat(f"{parts[0]}T{parts[1]}{parts[2]}")
                    if parsed.tzinfo is None:
                        raise ValueError("callback timestamp invalid")
                    sent_at = parsed.timestamp()
            except (ValueError, OverflowError) as error:
                raise ValueError("callback timestamp invalid") from error
            if abs(self._now().timestamp() - sent_at) > 300:
                raise ValueError("callback timestamp invalid")
            legacy_card = len(signature) == 40
            digest = hashlib.sha1 if legacy_card else hashlib.sha256
            secret = self._token if legacy_card else self._key
            expected = digest((timestamp + nonce + secret).encode() + body).hexdigest()
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
        if signature and len(signature) == 40 and (
            header is not None or not isinstance(payload.get("action"), dict)
            or not isinstance(payload.get("open_id"), str)
        ):
            raise ValueError("callback signature invalid")
        if not signature and payload.get("type") != "url_verification":
            raise ValueError("callback signature invalid")
        return payload


class FeishuBotService:
    def __init__(
        self, sessions: sessionmaker[Session], *, files: PrivateFileStore,
        media: FeishuBotMedia, identity_scope: str, codec: IncomingWorkbookCodec,
        recognition: IncomingDiffRecognitionService,
        decision_parser: IncomingDecisionParser | None = None,
    ) -> None:
        self._sessions = sessions
        self._files = files
        self._media = media
        self._identity_scope = identity_scope
        self._recognition = recognition
        self._workbooks = IncomingWorkbookWorkflow(sessions, file_store=files, codec=codec)
        self._registration = IncomingDifferenceService(sessions)
        self._store = InfrastructureStore(sessions)
        self._imports = IncomingImportWorkflow(sessions, files=files, codec=codec)
        self._decision_parser = decision_parser

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
                message.get("chat_type") != "p2p" or kind not in {"image", "file", "post", "text"}):
            return {}
        try:
            content = json.loads(str(message.get("content", "")))
        except ValueError:
            return {}
        if not isinstance(content, dict):
            return {}
        if kind == "text":
            actor_id = self._actor(open_id, header.get("tenant_key"))
            if actor_id is None:
                self._reply(None, open_id, message_id, DENIED)
                return {}
            text = content.get("text")
            parent_id = message.get("parent_id")
            if not isinstance(text, str) or not text.strip():
                return {}
            if not isinstance(parent_id, str) or not parent_id:
                self._reply(actor_id, open_id, message_id,
                            "请使用回复功能回复本次审核清单，说明重复编号及处理意见。")
                return {}
            self._store.enqueue_job(job_type=DECISION_JOB, dedupe_key=message_id,
                payload={"actorId": actor_id, "openId": open_id, "chatId": chat_id,
                         "messageId": message_id, "parentId": parent_id, "text": text},
                available_at=utc_now())
            return {}
        attachments = (content.get("files") if kind == "post"
                       else [content] if kind == "file" else None)
        if attachments:
            actor_id = self._actor(open_id, header.get("tenant_key"))
            if actor_id is None:
                self._reply(None, open_id, message_id, DENIED)
                return {}
            sent_at = message.get("create_time")
            if (not isinstance(attachments, list)
                    or not all(isinstance(item, dict) for item in attachments)
                    or not isinstance(sent_at, str) or not sent_at.isdecimal()):
                self._reply(actor_id, open_id, message_id, "文件消息缺少完整附件信息，未登记。")
                return {}
            batch_id = self._imports.receive(
                actor_id=actor_id, chat_id=chat_id, open_id=open_id,
                message_id=message_id, sent_at=int(sent_at), attachments=attachments)
            with self._sessions() as session:
                batch = session.get(IncomingDiffBatch, batch_id)
                if batch and batch.status == "VALIDATING":
                    self._reply(actor_id, open_id, f"received:{message_id}",
                        f"导入 {batch.batch_no} 已收到 {len(attachments)} 份文件，正在统一核对。"
                        "本次完整集合替换此前待登记文件，旧确认已失效。", batch_id=batch_id)
            return {}
        if kind == "post":
            blocks = content.get("content")
            if not isinstance(blocks, list):
                return {}
            image_keys = list(dict.fromkeys(
                node["image_key"] for row in blocks if isinstance(row, list)
                for node in row if isinstance(node, dict) and node.get("tag") == "img"
                and isinstance(node.get("image_key"), str) and node["image_key"]
            ))
            if not image_keys:
                return {}
        else:
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
        if kind == "post":
            self._images(actor_id, open_id, chat_id, message_id, image_keys)
        elif kind == "image":
            assert isinstance(file_key, str)
            self._images(actor_id, open_id, chat_id, message_id, [file_key])
        else:
            assert isinstance(file_key, str) and isinstance(filename, str)
            self._uploaded(actor_id, open_id, chat_id, message_id, file_key, filename)
        return {}

    def decision_job(self, payload: dict[str, object]) -> None:
        actor_id, open_id = str(payload["actorId"]), str(payload["openId"])
        message_id, chat_id = str(payload["messageId"]), str(payload["chatId"])
        with self._sessions() as session:
            previous = session.scalar(select(IdempotencyRecord).where(
                IdempotencyRecord.scope == "incoming_diff_decision",
                IdempotencyRecord.idempotency_key == message_id))
            if previous and previous.result:
                self._import_summary(str(previous.result["batchId"]))
                return
        try:
            content = self._media.read_own_message(str(payload["parentId"]), chat_id)
            with self._sessions() as session:
                batches = session.scalars(select(IncomingDiffBatch).where(
                    IncomingDiffBatch.submitter_id == actor_id,
                    IncomingDiffBatch.feishu_chat_id == chat_id,
                    IncomingDiffBatch.status.in_(["NEEDS_DECISION", "READY"]),
                )).all()
                matches = [batch for batch in batches if self._review_marker(batch) in content]
                if len(matches) != 1:
                    raise ValueError("引用的审核清单已失效，请回复最新清单")
                batch = matches[0]
                workbook = session.get(IncomingDiffWorkbook, batch.current_workbook_id)
                assert workbook is not None
                numbers = [line["number"] for line in workbook.line_snapshot
                           if line.get("duplicates")]
                batch_id, revision = batch.batch_id, batch.review_revision
            if self._decision_parser is None:
                raise ValueError("文字处理服务未配置，本次未应用决定")
            decisions = self._decision_parser.parse(text=str(payload["text"]), numbers=numbers)
            self._imports.decide(batch_id=batch_id, actor_id=actor_id, revision=revision,
                                 message_id=message_id, decisions=decisions,
                                 text=str(payload["text"]))
        except (ValueError, IncomingDifferenceError) as error:
            self._reply(actor_id, open_id, f"decision:{message_id}", str(error)[:400])
            return
        self._import_summary(batch_id)

    def decision_failed(self, payload: dict[str, object], error: Exception) -> None:
        self._reply(str(payload["actorId"]), str(payload["openId"]),
                    f"decision:{payload['messageId']}",
                    "文字处理暂时失败，本次未应用决定，请重新回复最新清单。")

    @staticmethod
    def _review_marker(batch: IncomingDiffBatch) -> str:
        return f"审核清单 {batch.batch_no} / {batch.review_revision}。"

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
        if (operation not in {"generate", "confirm", "regenerate", "continue", "select_import"}
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
        if operation == "select_import":
            try:
                self._imports.select_import(batch_id=batch_id, actor_id=actor_id)
            except IncomingDifferenceError as error:
                return self._toast(str(error))
        elif operation == "generate":
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
            revision = value.get("reviewRevision")
            if batch.source_kind == "FILE" and type(revision) is not int:
                return self._toast("审核版本无效，请使用最新清单")
            with self._sessions() as session:
                current_batch = session.get(IncomingDiffBatch, batch_id)
                assert current_batch is not None
                if current_batch.status == "CONFIRMED":
                    try:
                        result = self._registration.confirm(batch_id=batch_id,
                            workbook_version=version, actor_id=actor_id,
                            review_revision=revision if type(revision) is int else None)
                    except IncomingDifferenceError as error:
                        return self._toast(str(error))
                    operator = session.get(User, result.confirmed_by)
                    operator_name = operator.feishu_display_name if operator else "提交人"
                    self._reply(
                        actor_id, open_id, event_id,
                        f"批次 {batch_no} 已于 {result.confirmed_at:%Y-%m-%d %H:%M} "
                        f"由 {operator_name} 确认登记，本次不重复生效。",
                    )
                    return self._toast("已登记")
            self._store.enqueue_job(job_type=CONFIRM_JOB,
                                    dedupe_key=f"{batch_id}:{version}:{revision}:{event_id}",
                                    payload={"batchId": batch_id, "version": version,
                                             "reviewRevision": revision,
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

    def _images(self, actor_id: str, open_id: str, chat_id: str,
                message_id: str, image_keys: list[str]) -> None:
        with self._sessions() as session:
            if session.scalar(select(OutboxMessage.id).where(
                OutboxMessage.dedupe_key == f"incoming-diff-bot:{message_id}",
            )) is not None:
                return
        batch = self._batch(actor_id, chat_id, status="COLLECTING")
        batch_id = (batch.batch_id if batch else
                    self._registration.create_batch(submitter_id=actor_id,
                                                    feishu_chat_id=chat_id,
                                                    feishu_open_id=open_id).batch_id)
        received: dict[str, IncomingDiffImage] = {}
        added = 0
        for image_key in image_keys:
            result = self._image(actor_id, open_id, batch_id, message_id, image_key)
            if result is None:
                return
            image, created = result
            added += int(created and image.image_id not in received)
            received[image.image_id] = image
        with self._sessions() as session:
            total = session.scalar(select(func.count()).select_from(IncomingDiffImage).where(
                IncomingDiffImage.batch_id == batch_id)) or 0
            messages = [f"本次新增 {added} 张图片，本批次累计 {total} 张。"
                        "继续发送，或点击“生成核对表”。"]
            duplicates = len(image_keys) - added
            if duplicates:
                messages.append(f"本批次已收到其中 {duplicates} 张相同图片，已跳过。")
            buttons: list[tuple[str, str, dict[str, object]]] = [("生成核对表", "generate", {})]
            for image in received.values():
                if image.duplicate_of_batch_id and not image.duplicate_ack_at:
                    old = session.get(IncomingDiffBatch, image.duplicate_of_batch_id)
                    old_no = old.batch_no if old else image.duplicate_of_batch_id
                    messages.append(
                        f"第 {image.sort_order} 张图片与批次 {old_no} 的图片内容相同。"
                        "如确认是另一次实际差异，点击对应的“继续核对”。")
                    buttons.append((f"第 {image.sort_order} 张继续核对", "continue",
                                    {"imageId": image.image_id}))
        self._reply(actor_id, open_id, message_id, "\n".join(messages),
                    batch_id=batch_id, buttons=buttons)

    def _image(self, actor_id: str, open_id: str, batch_id: str,
               message_id: str, image_key: str) -> tuple[IncomingDiffImage, bool] | None:
        with self._sessions() as session:
            existing = session.scalar(select(IncomingDiffImage).where(
                IncomingDiffImage.batch_id == batch_id,
                IncomingDiffImage.feishu_message_id == message_id,
                IncomingDiffImage.feishu_image_key == image_key,
            ))
            if existing is not None:
                return existing, True
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
            return None
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
        created = image.file_id == file_id
        if not created:
            with self._sessions() as session, session.begin():
                session.delete(session.get(StoredFile, file_id))
            self._files.delete(object_key=object_key)
        return image, created

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
            if not content or len(content) > MAX_WORKBOOK_BYTES:
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
        batch_id = str(payload["batchId"])
        with self._sessions() as session:
            batch = session.get(IncomingDiffBatch, batch_id)
            if batch is not None and batch.status == "SUPERSEDED":
                return
        self._recognition.recognize(payload)
        with self._sessions() as session, session.begin():
            batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if batch is not None and batch.status == "SUPERSEDED":
                return
            assert batch is not None and batch.status == "RECOGNIZING"
            batch.status = "READY"
            actor_id = batch.submitter_id
        self._generate(batch_id, actor_id)

    def import_job(self, payload: dict[str, object]) -> None:
        batch_id = str(payload["batchId"])
        with self._sessions() as session:
            batch = session.get(IncomingDiffBatch, batch_id)
            if batch is None or batch.status == "SUPERSEDED":
                return
            attachments = batch.attachments or []
            message_id = batch.source_message_id
            status = batch.status
        if status == "VALIDATING":
            if (not 1 <= len(attachments) <= 30 or not message_id
                    or any(not isinstance(item.get("file_key"), str)
                           or not item.get("file_key") or item.get("is_folder")
                           or not str(item.get("file_name", "")).lower().endswith(".xlsx")
                           for item in attachments)
                    or len({item["file_key"] for item in attachments}) != len(attachments)):
                self.import_failed(payload, ValueError("附件须为1至30份不同的Excel文件"))
                return
            contents = []
            for item in attachments:
                content = self._media.download_resource(message_id, item["file_key"], "file")
                if not content or len(content) > MAX_WORKBOOK_BYTES:
                    self.import_failed(payload, ValueError(f"{item['file_name']}：文件大小无效"))
                    return
                contents.append(content)
                if sum(map(len, contents)) > 100 * 1024 * 1024:
                    self.import_failed(payload, ValueError("本次文件总大小超过100MiB"))
                    return
            self._imports.prepare(batch_id=batch_id, contents=contents)
        self._import_summary(batch_id)

    def import_failed(self, payload: dict[str, object], error: Exception) -> None:
        batch_id = str(payload["batchId"])
        with self._sessions() as session, session.begin():
            batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if batch is None or batch.status != "VALIDATING":
                return
            batch.status = "FAILED"
            batch.recognition_error_summary = (
                str(error)[:400] if type(error) is ValueError
                else "附件读取失败，请重新发送完整文件集合")
        self._import_summary(batch_id)

    def _import_summary(self, batch_id: str) -> None:
        with self._sessions() as session:
            batch = session.get(IncomingDiffBatch, batch_id)
            if batch is None or batch.status in {"SUPERSEDED", "CONFIRMED", "VALIDATING"}:
                return
            workbook = session.get(IncomingDiffWorkbook, batch.current_workbook_id) \
                if batch.current_workbook_id else None
            lines = workbook.line_snapshot if workbook else []
            issues = workbook.validation_issues if workbook else []
            names = [str(item.get("file_name", "")) for item in batch.attachments or []]
            if batch.source_kind == "PHOTO":
                names = [f"{batch.batch_no}_核对表.xlsx"]
            summary = [self._review_marker(batch), f"共{len(names)}份文件：",
                       *names, "本次使用以上完整文件集合；此前待登记文件的确认已失效。"]
            buttons: list[tuple[str, str, dict[str, object]]] = []
            if batch.status == "NEEDS_SELECTION":
                summary.append("上传顺序无法确定，请选择本次保留的完整文件集合：")
                candidates = session.scalars(select(IncomingDiffBatch).where(
                    IncomingDiffBatch.submitter_id == batch.submitter_id,
                    IncomingDiffBatch.feishu_chat_id == batch.feishu_chat_id,
                    IncomingDiffBatch.status == "NEEDS_SELECTION")).all()
                for candidate in candidates:
                    summary.append(f"{candidate.batch_no}：" + "、".join(
                        item["file_name"] for item in candidate.attachments or []))
                    buttons.append((f"保留 {candidate.batch_no}", "select_import",
                                    {"batchId": candidate.batch_id}))
            elif batch.status == "FAILED":
                summary.extend(f"{item.get('fileName', '')} / {item.get('sheetName', '')} / "
                               f"第{item.get('rowNumber', '')}行：{item['reason']}"
                               for item in issues or [])
                summary.append(batch.recognition_error_summary
                               or "本次全部未登记，请修正后重传全部文件。")
            else:
                numbered = {line["number"]: line for line in lines}
                for line in lines:
                    if line.get("duplicates"):
                        evidence = []
                        for candidate in line["duplicates"]:
                            if "number" in candidate:
                                other = numbered[candidate["number"]]
                                evidence.append(
                                    f"本次第{other['number']}条（{other['fileName']} / "
                                    f"{other['sheetName']} / 第{other['rowNumber']}行）")
                            else:
                                evidence.append(
                                    f"历史记录 {candidate['recordId']}，"
                                    f"登记于{candidate['registeredAt']} UTC，"
                                    f"初始数量{candidate['initialQuantity']}，"
                                    f"当前数量{candidate['quantity']}")
                        decision = {"skip": "跳过", "register_new": "作为新记录登记"}.get(
                            line.get("decision"), "待决定")
                        summary.append(
                            f"第{line['number']}条：{line['fileName']} / {line['sheetName']} / "
                            f"第{line['rowNumber']}行，{line['productName']} {line['spec']} "
                            f"数量{line['quantity']} 采购单{line['purchaseOrderId']}；"
                            f"疑似重复：{'；'.join(evidence)}；决定：{decision}"
                        )
                selected = [line for line in lines if line.get("decision") != "skip"]
                surplus = sum(int(x["quantity"]) for x in selected if x["quantity"] > 0)
                shortage = -sum(int(x["quantity"]) for x in selected if x["quantity"] < 0)
                summary.append(f"待登记{len(selected)}条，跳过{len(lines) - len(selected)}条；"
                               f"多货{surplus}件，少货{shortage}件。")
                for factory in sorted({str(line["factoryName"]) for line in selected}):
                    count = sum(x["factoryName"] == factory for x in selected)
                    summary.append(f"{factory}：{count}条")
                if batch.status == "NEEDS_DECISION":
                    summary.append("请回复本条清单：第1条跳过，第2条作为新记录登记；"
                                   "或疑似重复的全部跳过／全部作为新记录登记。")
                else:
                    assert workbook is not None
                    buttons = [("确认登记", "confirm", {"version": workbook.version,
                                                       "reviewRevision": batch.review_revision})]
            assert batch.feishu_open_id is not None
            self._reply(batch.submitter_id, batch.feishu_open_id,
                        f"import:{batch_id}:{batch.review_revision}:{batch.status}",
                        "\n".join(summary), batch_id=batch_id, buttons=buttons)

    def recognition_failed(self, payload: dict[str, object], error: Exception) -> None:
        self._recognition.fail_terminal(payload, error)
        batch_id = str(payload["batchId"])
        with self._sessions() as session, session.begin():
            batch = session.get(IncomingDiffBatch, batch_id, with_for_update=True)
            if batch is None or batch.status == "SUPERSEDED":
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
                    spec = f"{line['color'] or ''}{line['size'] or ''}"
                    lines.append({
                        "imageId": image.image_id, "factoryName": parsed.get("factoryName"),
                        "productName": parsed.get("productName"),
                        "productCode": parsed.get("productCode"),
                        "spec": spec, "quantity": line["signedQuantity"],
                        "purchaseOrderId": line.get("purchaseOrderId"),
                        "purchaseOrderItemId": line.get("purchaseOrderItemId"),
                        "orderAssignmentId": line.get("orderAssignmentId"),
                        "detailId": line.get("detailId"),
                        "factoryId": line.get("factoryId"),
                        "variantId": line.get("variantId"),
                    })
            open_id = batch.feishu_open_id
            batch_no = batch.batch_no
        workbook = self._workbooks.generate(batch_id=batch_id, actor_id=actor_id,
                                             lines=lines, regenerate=regenerate)
        pending = sum(not (line.get("detailId") or line.get("orderAssignmentId"))
                      for line in lines)
        self._reply(
            actor_id, open_id, f"generated:{workbook.workbook_id}",
            f"批次 {batch_no} 核对表已生成：共 {len(lines)} 条明细，{pending} 条待确认。"
            "核对无误请点击核对登记；需要修改请下载整理后发送完整文件集合。",
            batch_id=batch_id,
            buttons=[("核对登记", "confirm", {"version": workbook.version}),
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
        revision = payload.get("reviewRevision")
        reply_key = f"{batch_id}:{version}:{revision}"
        try:
            with self._sessions() as session:
                batch = session.get(IncomingDiffBatch, batch_id)
                assert batch is not None
                needs_review = batch.source_kind == "PHOTO" and revision is None
            if needs_review:
                self._imports.review_generated(batch_id=batch_id, actor_id=actor_id,
                                               version=version)
                self._import_summary(batch_id)
                return
            result = self._registration.confirm(batch_id=batch_id, workbook_version=version,
                                                actor_id=actor_id,
                                                review_revision=revision if type(revision) is int
                                                else None)
        except IncomingDifferenceValidationError as error:
            with self._sessions() as session:
                batch = session.get(IncomingDiffBatch, batch_id)
                current = (session.get(IncomingDiffWorkbook, batch.current_workbook_id)
                           if batch and batch.current_workbook_id else None)
                lines = current.line_snapshot if current else []
            self._reply(actor_id, open_id, f"confirm-error:{reply_key}",
                        self._registration_errors(error.issues, lines), batch_id=batch_id)
            return
        except IncomingDifferenceError as error:
            if self._imports.refresh_duplicates(batch_id):
                self._import_summary(batch_id)
                return
            self._reply(actor_id, open_id, f"confirm-error:{reply_key}",
                        str(error)[:400], batch_id=batch_id)
            return
        if result.replayed:
            message = (f"批次 {result.batch_no} 已于 {result.confirmed_at:%Y-%m-%d %H:%M} "
                       "由提交人确认登记，本次不重复生效。")
        else:
            message = (f"批次 {result.batch_no} 已正式登记 {result.record_count} 条来货出入，"
                       f"涉及 {result.factory_count} 个工厂。")
        self._reply(actor_id, open_id, f"confirmed:{reply_key}", message,
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
        if any(line.get("importFileId") for line in lines):
            return "\n".join(
                f"{issue.get('fileName', '')} / {issue.get('sheetName', '')} / "
                f"第{issue.get('rowNumber', '')}行：{issue['reason']}"
                for issue in issues) + "\n本次全部未登记，请修正后重传完整文件集合。"
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
            elif source and source.get("purchaseOrderId") and reason == "未匹配到唯一订单明细":
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
                count = sum(self._registration.match_detail(
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
            if len(message.encode("utf-8")) > 12000:
                digest = hashlib.sha256(message.encode()).hexdigest()
                object_key = f"incoming-differences/{batch_id}/reports/{digest}.txt"
                stored = session.scalar(select(StoredFile).where(
                    StoredFile.bucket == self._files.bucket, StoredFile.object_key == object_key))
                if stored is None:
                    content = message.encode("utf-8")
                    self._files.put(object_key=object_key, content=content,
                                    content_type="text/plain")
                    stored = StoredFile(bucket=self._files.bucket, object_key=object_key,
                        original_filename="来货出入完整审核清单.txt", mime_type="text/plain",
                        size_bytes=len(content), content_sha256=digest, uploaded_by=actor_id)
                    session.add(stored)
                    session.flush()
                file_id = stored.file_id
                message = (message[:1000] + "\n……完整明细请查看随附审核清单。\n" + message[-1000:])
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
