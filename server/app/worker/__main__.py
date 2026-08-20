import signal
import socket
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from app.db.session import create_database_engine
from app.modules.infrastructure import InfrastructureStore
from app.settings.config import Settings
from app.worker.runtime import Worker


def main() -> None:
    settings = Settings()
    engine = create_database_engine(settings.database_url)
    stop_event = Event()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop_event.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop_event.set())
    store = InfrastructureStore(sessionmaker(engine, class_=Session))
    Worker(store=store, worker_id=socket.gethostname(), handlers={}).run(stop_event=stop_event)
    engine.dispose()


if __name__ == "__main__":
    main()
