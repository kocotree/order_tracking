import signal
import socket
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.order_source import (
    AppCredentialFeishuOrderSource,
    DisabledFeishuOrderSource,
    FeishuOrderSourceConfig,
)
from app.adapters.product import DisabledJstProductSource, DisabledProductImageStore
from app.db.session import create_database_engine
from app.modules.infrastructure import InfrastructureStore
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
    Worker(
        store=store,
        worker_id=socket.gethostname(),
        handlers={**product_handlers.handlers(), **order_handlers.handlers()},
        terminal_failure_handlers=order_handlers.terminal_failure_handlers(),
        retry_limits={"product-image-cache": 3, "order_import": 3},
    ).run(stop_event=stop_event)
    engine.dispose()


if __name__ == "__main__":
    main()
