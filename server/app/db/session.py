from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 1},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, class_=Session, expire_on_commit=False)


@contextmanager
def transactional_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session, session.begin():
        yield session
