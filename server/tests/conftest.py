import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

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
