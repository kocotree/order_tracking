import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from app.db.session import create_database_engine


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return os.environ["ORDER_TRACKING_TEST_DATABASE_URL"]


@pytest.fixture(scope="session")
def test_database_engine(test_database_url: str) -> Engine:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", test_database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(test_database_url)
    yield engine
    engine.dispose()


def _truncate_business_tables(engine: Engine) -> None:
    table_names = [
        table_name
        for table_name in inspect(engine).get_table_names()
        if table_name != "alembic_version"
    ]
    preparer = engine.dialect.identifier_preparer
    with engine.begin() as connection:
        connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            for table_name in table_names:
                quoted_table_name = preparer.quote(table_name)
                connection.execute(text(f"TRUNCATE TABLE {quoted_table_name}"))
        finally:
            connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture(autouse=True)
def isolate_database_test(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    database_fixture_names = {"test_database_engine", "test_database_url"}
    if database_fixture_names.isdisjoint(request.fixturenames):
        yield
        return

    engine = request.getfixturevalue("test_database_engine")
    _truncate_business_tables(engine)
    try:
        yield
    finally:
        _truncate_business_tables(engine)
