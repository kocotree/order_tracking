import signal
import socket
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from app.adapters.product import DisabledJstProductSource, DisabledProductImageStore
from app.db.session import create_database_engine
from app.modules.infrastructure import InfrastructureStore
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
    handlers = ProductWorkerHandlers(
        sync_service=ProductSyncService(sessions, source=DisabledJstProductSource()),
        image_service=ProductImageService(sessions, image_store=DisabledProductImageStore()),
        worker_id=socket.gethostname(),
    )
    Worker(
        store=store,
        worker_id=socket.gethostname(),
        handlers=handlers.handlers(),
        retry_limits={"product-image-cache": 3},
    ).run(stop_event=stop_event)
    engine.dispose()


if __name__ == "__main__":
    main()
