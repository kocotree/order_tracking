import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from scripts.check_migrations import migration_state


def test_migration_states() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        assert migration_state(connection, scripts) == "pending"
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(100))"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:version)"),
                           {"version": scripts.get_current_head()})
        assert migration_state(connection, scripts) == "current"
        connection.execute(text("UPDATE alembic_version SET version_num = :version"),
                           {"version": scripts.get_bases()[0]})
        assert migration_state(connection, scripts) == "pending"
        connection.execute(text("UPDATE alembic_version SET version_num = 'unknown'"))
        with pytest.raises(ValueError, match="incompatible"):
            migration_state(connection, scripts)
        connection.execute(text("INSERT INTO alembic_version VALUES ('other')"))
        with pytest.raises(ValueError, match="multiple_heads"):
            migration_state(connection, scripts)
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(text("CREATE TABLE business (id INT)"))
        with pytest.raises(ValueError, match="unversioned"):
            migration_state(connection, scripts)
