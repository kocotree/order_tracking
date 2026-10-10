from unittest.mock import Mock

import conftest
import pytest


@pytest.mark.parametrize("database_url", [
    "mysql+pymysql://order_test:secret@127.0.0.1/order_tracking",
    "mysql+pymysql://order_test:secret@127.0.0.1/order_tracking_dev",
    "mysql+pymysql://order_test:secret@db.example.invalid/order_tracking_test",
    "mysql+pymysql://order_test:secret@127.0.0.1/other_test",
    "mysql+pymysql://order_test:secret@127.0.0.1",
    "sqlite:///order_tracking_test",
    "mysql+pymysql://order_test:secret@127.0.0.1/order_tracking_test?host=db.example.invalid",
    "mysql+pymysql://order_test:secret@127.0.0.1/order_tracking_test?database=order_tracking",
    "mysql+pymysql://order_test:secret@127.0.0.1/order_tracking_test?read_default_file=config",
])
def test_unsafe_database_is_rejected_before_migration(
    monkeypatch: pytest.MonkeyPatch, database_url: str,
) -> None:
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "test")
    migrate = Mock()
    connect = Mock(side_effect=AssertionError("unsafe database connection attempted"))
    monkeypatch.setattr(conftest.command, "upgrade", migrate)
    monkeypatch.setattr(conftest, "create_database_engine", connect)

    with pytest.raises(ValueError, match="isolated local MySQL test database") as rejected:
        next(conftest.test_database_engine.__wrapped__(database_url))

    migrate.assert_not_called()
    connect.assert_not_called()
    assert "secret" not in str(rejected.value)

    monkeypatch.setenv("ORDER_TRACKING_TEST_DATABASE_URL", database_url)
    with pytest.raises(ValueError, match="isolated local MySQL test database"):
        conftest.test_database_url.__wrapped__()


@pytest.mark.parametrize("database_url", [
    "mysql+pymysql://order_test:secret@127.0.0.1:3306/order_tracking_test?charset=utf8mb4",
    "mysql+pymysql://order_test:secret@localhost:3308/order_tracking_issue252_test",
    "mysql+pymysql://order_test:secret@[::1]:3308/order_tracking_test",
])
def test_isolated_database_urls_are_preserved(
    monkeypatch: pytest.MonkeyPatch, database_url: str,
) -> None:
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "test")
    monkeypatch.setenv("ORDER_TRACKING_TEST_DATABASE_URL", database_url)
    assert conftest.test_database_url.__wrapped__() == database_url


def test_production_environment_cannot_use_database_fixtures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORDER_TRACKING_APP_ENV", "production")
    monkeypatch.setenv(
        "ORDER_TRACKING_TEST_DATABASE_URL",
        "mysql+pymysql://order_test:secret@127.0.0.1/order_tracking_test",
    )
    with pytest.raises(ValueError, match="isolated local MySQL test database"):
        conftest.test_database_url.__wrapped__()
