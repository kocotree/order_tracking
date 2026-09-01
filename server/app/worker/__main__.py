import signal
import socket
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import (
    AppCredentialFeishuBusinessNotifier,
    AppCredentialOpsAlertNotifier,
    AppCredentialWechatNotifier,
    DisabledFeishuBusinessNotifier,
    DisabledWechatNotifier,
    FeishuBusinessNotifier,
    FeishuNotificationConfig,
    OpsAlertNotifier,
    WechatNotifier,
    WechatSubscriptionConfig,
)
from app.adapters.order_source import (
    AppCredentialFeishuOrderSource,
    DisabledFeishuOrderSource,
    FeishuOrderSourceConfig,
)
from app.adapters.private_files import AliyunOssPrivateFileStore
from app.adapters.product import (
    AppCredentialJstProductSource,
    DisabledJstProductSource,
    DisabledProductImageStore,
    JstProductSourceConfig,
    PrivateProductImageStore,
)
from app.db.session import create_database_engine
from app.modules.infrastructure import InfrastructureStore, utc_now
from app.modules.notifications_audit import NotificationsAuditService
from app.modules.notifications_audit.worker import NotificationWorkerHandlers
from app.modules.order_import import OrderImportService
from app.modules.order_import.worker import OrderImportWorkerHandlers
from app.modules.product_sync import ProductImageService, ProductSyncService, ProductWorkerHandlers
from app.settings.config import Settings
from app.worker.runtime import Worker


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    stop_event = Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop_event.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop_event.set())
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    store = InfrastructureStore(sessions)
    product_source = (
        AppCredentialJstProductSource(
            JstProductSourceConfig(
                app_key=settings.jst_product_app_key,
                app_secret=settings.jst_product_app_secret,
                initial_sync_begin=datetime.fromisoformat(
                    settings.jst_product_initial_sync_begin
                ),
                endpoint=settings.jst_product_endpoint,
                token_cache_path=Path(settings.jst_product_token_cache_path),
                page_size=settings.jst_product_page_size,
                request_interval_seconds=(
                    settings.jst_product_request_interval_seconds
                ),
                retry_attempts=settings.jst_product_retry_attempts,
                retry_base_delay_seconds=(
                    settings.jst_product_retry_base_delay_seconds
                ),
            )
        )
        if all(
            (
                settings.jst_product_app_key,
                settings.jst_product_app_secret,
                settings.jst_product_initial_sync_begin,
            )
        )
        else DisabledJstProductSource()
    )
    product_image_store = (
        PrivateProductImageStore(
            AliyunOssPrivateFileStore(
                endpoint=settings.oss_endpoint,
                region=settings.oss_region,
                access_key_id=settings.oss_access_key_id,
                access_key_secret=settings.oss_access_key_secret,
                bucket=settings.oss_bucket,
            )
        )
        if all(
            (
                settings.oss_region,
                settings.oss_endpoint,
                settings.oss_access_key_id,
                settings.oss_access_key_secret,
            )
        )
        else DisabledProductImageStore()
    )
    product_handlers = ProductWorkerHandlers(
        sync_service=ProductSyncService(sessions, source=product_source),
        image_service=ProductImageService(sessions, image_store=product_image_store),
        worker_id=socket.gethostname(),
    )
    order_source = (
        AppCredentialFeishuOrderSource(
            FeishuOrderSourceConfig(
                app_id=settings.feishu_order_app_id,
                app_secret=settings.feishu_order_app_secret,
                app_token=settings.feishu_order_app_token,
                table_id=settings.feishu_order_table_id,
                view_id=settings.feishu_order_view_id,
            )
        )
        if all(
            [
                settings.feishu_order_app_id,
                settings.feishu_order_app_secret,
                settings.feishu_order_app_token,
                settings.feishu_order_table_id,
                settings.feishu_order_view_id,
            ]
        )
        else DisabledFeishuOrderSource()
    )
    order_handlers = OrderImportWorkerHandlers(
        service=OrderImportService(sessions), source=order_source
    )
    notification_service = NotificationsAuditService(sessions)
    wechat_notifier: WechatNotifier = (
        AppCredentialWechatNotifier(
            WechatSubscriptionConfig(
                app_id=settings.wechat_identity_app_id,
                app_secret=settings.wechat_identity_app_secret,
                template_ids=settings.wechat_notification_template_ids,
                miniprogram_state=settings.wechat_notification_miniprogram_state,
            ),
            sessions,
        )
        if settings.wechat_notifications_enabled
        else DisabledWechatNotifier()
    )
    feishu_app_id = settings.feishu_identity_app_id or settings.feishu_order_app_id
    feishu_app_secret = (
        settings.feishu_identity_app_secret or settings.feishu_order_app_secret
    )
    feishu_notification_config = FeishuNotificationConfig(
        app_id=feishu_app_id,
        app_secret=feishu_app_secret,
        admin_web_base_url=settings.admin_web_base_url,
        ops_alert_recipient_user_id=settings.ops_alert_recipient_user_id,
    )
    feishu_notifier: FeishuBusinessNotifier = (
        AppCredentialFeishuBusinessNotifier(feishu_notification_config, sessions)
        if settings.feishu_notifications_enabled
        else DisabledFeishuBusinessNotifier()
    )
    ops_alert_notifier: OpsAlertNotifier | None = (
        AppCredentialOpsAlertNotifier(feishu_notification_config, sessions)
        if settings.ops_alerts_enabled
        else None
    )
    enabled_delivery_channels: set[str] = set()
    if settings.wechat_notifications_enabled:
        enabled_delivery_channels.add("wechat")
    if settings.feishu_notifications_enabled:
        enabled_delivery_channels.add("feishu")
    notification_handlers = NotificationWorkerHandlers(
        service=notification_service,
        store=store,
    )
    notification_service.recover_stale_outbox(before=utc_now() - timedelta(minutes=5))
    last_enqueued_date = None

    def ensure_daily_notification_scan() -> None:
        nonlocal last_enqueued_date
        shanghai_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        if shanghai_now.hour < settings.notification_due_scan_hour:
            return
        business_date = shanghai_now.date()
        if business_date == last_enqueued_date:
            return
        notification_handlers.ensure_due_scan_job(business_date=business_date)
        last_enqueued_date = business_date

    worker_id = socket.gethostname()
    Worker(
        store=store,
        worker_id=worker_id,
        handlers={
            **product_handlers.handlers(),
            **order_handlers.handlers(),
            **notification_handlers.handlers(),
        },
        terminal_failure_handlers=order_handlers.terminal_failure_handlers(),
        retry_limits={"product-image-cache": 3, "order_import": 3},
        maintenance=ensure_daily_notification_scan,
        work_sources=[
            lambda: notification_service.consume_next_business_event(worker_id=worker_id),
            lambda: notification_service.deliver_next(
                worker_id=worker_id,
                wechat_notifier=wechat_notifier,
                feishu_notifier=feishu_notifier,
                ops_alert_notifier=ops_alert_notifier,
                enabled_channels=enabled_delivery_channels,
            ),
        ],
    ).run(stop_event=stop_event)
    engine.dispose()


if __name__ == "__main__":
    main()
