import signal
import socket
from datetime import datetime, timedelta
from threading import Event
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.notifications import (
    AppCredentialWechatNotifier,
    DisabledFeishuBusinessNotifier,
    DisabledOpsAlertNotifier,
    DisabledWechatNotifier,
    WechatNotifier,
    WechatSubscriptionConfig,
)
from app.adapters.order_source import (
    AppCredentialFeishuOrderSource,
    DisabledFeishuOrderSource,
    FeishuOrderSourceConfig,
)
from app.adapters.product import DisabledJstProductSource, DisabledProductImageStore
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
    product_handlers = ProductWorkerHandlers(
        sync_service=ProductSyncService(sessions, source=DisabledJstProductSource()),
        image_service=ProductImageService(sessions, image_store=DisabledProductImageStore()),
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
                feishu_notifier=DisabledFeishuBusinessNotifier(),
                ops_alert_notifier=DisabledOpsAlertNotifier(),
            ),
        ],
    ).run(stop_event=stop_event)
    engine.dispose()


if __name__ == "__main__":
    main()
