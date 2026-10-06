import argparse
import os
import signal
import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import (
    AppCredentialFeishuBusinessNotifier,
    AppCredentialFeishuSender,
    AppCredentialOpsAlertNotifier,
    AppCredentialWechatNotifier,
    DisabledFeishuBusinessNotifier,
    DisabledWechatNotifier,
    FeishuNotificationConfig,
    WechatSubscriptionConfig,
)
from app.adapters.order_source import (
    AppCredentialFeishuOrderSource,
    DisabledFeishuOrderSource,
    FeishuOrderSourceConfig,
)
from app.adapters.private_files import AliyunOssPrivateFileStore, DisabledPrivateFileStore
from app.adapters.product import (
    AppCredentialJstProductSource,
    DisabledJstProductSource,
    DisabledProductImageStore,
    JstProductSourceConfig,
    PrivateProductImageStore,
)
from app.adapters.shipment_writeback import FeishuShipmentWriter
from app.adapters.vision import DisabledIncomingDiffRecognizer, QwenIncomingDiffRecognizer
from app.db.session import create_database_engine
from app.logging import StructuredLogger
from app.modules.incoming_differences.bot import CONFIRM_JOB, REGENERATE_JOB, FeishuBotService
from app.modules.incoming_differences.recognition import (
    IncomingDiffRecognitionService,
    IncomingDiffRecognitionWorkerHandlers,
)
from app.modules.incoming_differences.workbook import IncomingWorkbookCodec
from app.modules.infrastructure import InfrastructureStore, utc_now
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.notifications_audit.worker import NotificationWorkerHandlers
from app.modules.order_import import OrderImportService
from app.modules.order_import.auto_sync import JOB_TYPE, OrderAutoSync
from app.modules.order_import.worker import OrderImportWorkerHandlers
from app.modules.product_sync import ProductImageService, ProductSyncService, ProductWorkerHandlers
from app.modules.shipment_writeback.service import ShipmentWriteback
from app.settings.config import Settings
from app.worker.runtime import JobHandler, TerminalFailureHandler, Worker
from app.worker.supervisor import supervise

ROLE_JOB_TYPES = {
    "sync": frozenset({
        "order_auto_sync", "order_import", "order_import_revalidate",
        "product-sync-initial", "product-sync-incremental", "product-image-cache",
        "shipment_writeback",
    }),
    "incoming": frozenset({
        "incoming_diff.recognize", CONFIRM_JOB, REGENERATE_JOB,
    }),
    "notification": frozenset({"notification_due_scan"}),
}
RoleParts = tuple[
    dict[str, JobHandler], dict[str, TerminalFailureHandler],
    Callable[[], None] | None, list[Callable[[], bool]],
]


def private_files(settings: Settings) -> AliyunOssPrivateFileStore | DisabledPrivateFileStore:
    if all((settings.oss_region, settings.oss_endpoint,
            settings.oss_access_key_id, settings.oss_access_key_secret)):
        return AliyunOssPrivateFileStore(
            endpoint=settings.oss_endpoint, region=settings.oss_region,
            access_key_id=settings.oss_access_key_id,
            access_key_secret=settings.oss_access_key_secret, bucket=settings.oss_bucket,
        )
    return DisabledPrivateFileStore(bucket=settings.oss_bucket)


def feishu_config(settings: Settings) -> FeishuNotificationConfig:
    return FeishuNotificationConfig(
        app_id=settings.feishu_identity_app_id or settings.feishu_order_app_id,
        app_secret=settings.feishu_identity_app_secret or settings.feishu_order_app_secret,
        admin_web_base_url=settings.admin_web_base_url,
        ops_alert_recipient_user_id=settings.ops_alert_recipient_user_id,
    )


def sync_role(settings: Settings, sessions: sessionmaker[Session],
              worker_id: str) -> RoleParts:
    product_source = (
        AppCredentialJstProductSource(JstProductSourceConfig(
            app_key=settings.jst_product_app_key,
            app_secret=settings.jst_product_app_secret,
            initial_sync_begin=datetime.fromisoformat(settings.jst_product_initial_sync_begin),
            endpoint=settings.jst_product_endpoint,
            token_cache_path=Path(settings.jst_product_token_cache_path),
            page_size=settings.jst_product_page_size,
            request_interval_seconds=settings.jst_product_request_interval_seconds,
            retry_attempts=settings.jst_product_retry_attempts,
            retry_base_delay_seconds=settings.jst_product_retry_base_delay_seconds,
        ))
        if all((settings.jst_product_app_key, settings.jst_product_app_secret,
                settings.jst_product_initial_sync_begin)) else DisabledJstProductSource()
    )
    files = private_files(settings)
    image_store = (
        PrivateProductImageStore(files) if isinstance(files, AliyunOssPrivateFileStore)
        else DisabledProductImageStore()
    )
    product_sync = ProductSyncService(sessions, source=product_source)
    product_handlers = ProductWorkerHandlers(
        sync_service=product_sync,
        image_service=ProductImageService(sessions, image_store=image_store),
        worker_id=worker_id,
    )
    order_source = (
        AppCredentialFeishuOrderSource(
            FeishuOrderSourceConfig(
                app_id=settings.feishu_order_app_id,
                app_secret=settings.feishu_order_app_secret,
                app_token=settings.feishu_order_app_token,
                table_id=settings.feishu_order_table_id,
                view_id=settings.feishu_order_view_id,
                field_ids=settings.feishu_order_field_ids,
                incremental_table_scope_confirmed=(
                    settings.feishu_order_incremental_table_scope_confirmed
                ),
            ),
            product_source if isinstance(product_source, AppCredentialJstProductSource) else None,
        )
        if all((settings.feishu_order_app_id, settings.feishu_order_app_secret,
                settings.feishu_order_app_token, settings.feishu_order_table_id,
                settings.feishu_order_view_id, settings.feishu_order_field_ids))
        else DisabledFeishuOrderSource()
    )
    order_handlers = OrderImportWorkerHandlers(
        service=OrderImportService(sessions, product_sync=product_sync), source=order_source
    )
    auto_sync = OrderAutoSync(sessions, source=order_source, product_sync=product_sync)
    writeback = ShipmentWriteback(
        sessions, source_scope=order_source.source_scope,
        target=FeishuShipmentWriter(
            order_source._config,
            total_field_id=settings.shipment_writeback_total_field_id,
            baseline_formula=settings.shipment_writeback_baseline_formula,
        ) if settings.shipment_writeback_enabled
        and isinstance(order_source, AppCredentialFeishuOrderSource) else None,
    )
    handlers = {**product_handlers.handlers(), **order_handlers.handlers(),
                JOB_TYPE: auto_sync.handle, "shipment_writeback": writeback.handle}
    failures = {**order_handlers.terminal_failure_handlers(), JOB_TYPE: auto_sync.fail}
    next_writeback_scan: datetime | None = None

    def ensure_auto_sync() -> None:
        nonlocal next_writeback_scan
        auto_sync.ensure_due()
        current = datetime.now(UTC)
        if settings.shipment_writeback_enabled and (
            next_writeback_scan is None or current >= next_writeback_scan
        ):
            writeback.ensure_due(now=current)
            next_writeback_scan = current + timedelta(minutes=1)

    maintenance = (
        ensure_auto_sync if not isinstance(order_source, DisabledFeishuOrderSource)
        else None
    )
    return handlers, failures, maintenance, []


def incoming_role(settings: Settings, sessions: sessionmaker[Session]) -> RoleParts:
    files = private_files(settings)
    recognizer = (
        QwenIncomingDiffRecognizer(
            api_key=settings.incoming_diff_vision_api_key,
            base_url=settings.incoming_diff_vision_base_url,
        ) if settings.incoming_diff_vision_api_key else DisabledIncomingDiffRecognizer()
    )
    recognition = IncomingDiffRecognitionService(
        sessions, files=files, recognizer=recognizer
    )
    incoming_handlers = IncomingDiffRecognitionWorkerHandlers(recognition)
    handlers: dict[str, JobHandler]
    failures: dict[str, TerminalFailureHandler]
    if settings.feishu_bot_enabled:
        config = feishu_config(settings)
        bot = FeishuBotService(
            sessions, files=files, media=AppCredentialFeishuSender(config, sessions),
            identity_scope=config.resolved_identity_scope,
            codec=IncomingWorkbookCodec(settings), recognition=recognition,
        )
        handlers = {"incoming_diff.recognize": bot.recognition_job,
                    CONFIRM_JOB: bot.confirm_job, REGENERATE_JOB: bot.regenerate_job}
        failures = {"incoming_diff.recognize": bot.recognition_failed}
    else:
        def bot_disabled(_payload: dict[str, object]) -> None:
            raise RuntimeError("feishu_bot_disabled")

        handlers = dict(incoming_handlers.handlers())
        handlers[CONFIRM_JOB] = bot_disabled
        handlers[REGENERATE_JOB] = bot_disabled
        failures = dict(incoming_handlers.terminal_failure_handlers())
    return handlers, failures, None, []


def notification_role(settings: Settings, sessions: sessionmaker[Session],
                      store: InfrastructureStore, worker_id: str,
                      logger: StructuredLogger) -> RoleParts:
    service = NotificationsAuditService(sessions, event_logger=logger)
    notification_handlers = NotificationWorkerHandlers(service=service, store=store)
    service.recover_stale_outbox(before=utc_now() - timedelta(minutes=5))
    last_enqueued_date = None

    def ensure_daily_notification_scan() -> None:
        nonlocal last_enqueued_date
        shanghai_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if shanghai_now.hour < settings.notification_due_scan_hour:
            return
        business_date = shanghai_now.date()
        if business_date != last_enqueued_date:
            notification_handlers.ensure_due_scan_job(business_date=business_date)
            last_enqueued_date = business_date

    config = feishu_config(settings)
    wechat_notifier = (
        AppCredentialWechatNotifier(WechatSubscriptionConfig(
            app_id=settings.wechat_identity_app_id,
            app_secret=settings.wechat_identity_app_secret,
            template_ids=settings.wechat_notification_template_ids,
            miniprogram_state=settings.wechat_notification_miniprogram_state,
        ), sessions) if settings.wechat_notifications_enabled else DisabledWechatNotifier()
    )
    feishu_notifier = (
        AppCredentialFeishuBusinessNotifier(
            config, sessions, file_store=private_files(settings)
        ) if settings.feishu_notifications_enabled or settings.feishu_bot_enabled
        else DisabledFeishuBusinessNotifier()
    )
    ops_notifier = (
        AppCredentialOpsAlertNotifier(config, sessions)
        if settings.ops_alerts_enabled else None
    )
    channels = set()
    if settings.wechat_notifications_enabled:
        channels.add("wechat")
    if settings.feishu_notifications_enabled or settings.feishu_bot_enabled:
        channels.add("feishu")
    sources = [
        lambda: service.consume_next_business_event(worker_id=worker_id),
        lambda: service.deliver_next(
            worker_id=worker_id, wechat_notifier=wechat_notifier,
            feishu_notifier=feishu_notifier, ops_alert_notifier=ops_notifier,
            enabled_channels=channels,
        ),
    ]
    return dict(notification_handlers.handlers()), {}, ensure_daily_notification_scan, sources


def run_role(role: str) -> None:
    settings = Settings()
    worker_id = f"{socket.gethostname()}:{role}:{os.getpid()}"
    logger = StructuredLogger(level=settings.log_level,
                              fields={"role": role, "workerId": worker_id})
    engine = create_database_engine(settings.database_url)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    store = InfrastructureStore(sessions)
    stop_event = Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop_event.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop_event.set())
    logger.event("worker.started", fields={"role": role, "workerId": worker_id})
    try:
        if role == "sync":
            handlers, failures, maintenance, sources = sync_role(settings, sessions, worker_id)
        elif role == "incoming":
            handlers, failures, maintenance, sources = incoming_role(settings, sessions)
        elif role == "notification":
            handlers, failures, maintenance, sources = notification_role(
                settings, sessions, store, worker_id, logger
            )
        else:
            raise ValueError(f"unknown worker role: {role}")
        if frozenset(handlers) != ROLE_JOB_TYPES[role]:
            raise RuntimeError(f"worker handler ownership mismatch: {role}")
        store.recover_stale_jobs(
            before=utc_now() - timedelta(minutes=5), job_types=tuple(handlers)
        )
        Worker(
            store=store, worker_id=worker_id, handlers=handlers,
            terminal_failure_handlers=failures,
            retry_limits={
                job_type: (1 if role == "incoming" and not settings.feishu_bot_enabled
                           and job_type in {CONFIRM_JOB, REGENERATE_JOB} else 3)
                for job_type in handlers
            }
            if role != "notification" else {},
            maintenance=maintenance, work_sources=sources, event_logger=logger,
        ).run(stop_event=stop_event)
    finally:
        engine.dispose()
        logger.event("worker.stopped", fields={"role": role, "workerId": worker_id})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=ROLE_JOB_TYPES)
    args = parser.parse_args()
    if args.role:
        run_role(args.role)
        return 0
    return supervise(tuple(ROLE_JOB_TYPES))


if __name__ == "__main__":
    raise SystemExit(main())
