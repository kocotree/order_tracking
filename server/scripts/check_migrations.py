import os

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect

from app.db.session import create_database_engine


def migration_state(connection: Connection, scripts: ScriptDirectory) -> str:
    heads = scripts.get_heads()
    current = MigrationContext.configure(connection).get_current_heads()
    if len(heads) != 1 or len(current) > 1:
        raise ValueError("migration_multiple_heads")
    if not current:
        if set(inspect(connection).get_table_names()) - {"alembic_version"}:
            raise ValueError("migration_unversioned_database")
        return "pending"
    ancestors = {item.revision for item in scripts.walk_revisions()}
    if current[0] not in ancestors:
        raise ValueError("migration_incompatible_revision")
    return "current" if current == tuple(heads) else "pending"


def main() -> None:
    engine = create_database_engine(os.environ["ORDER_TRACKING_DATABASE_URL"])
    with engine.connect() as connection:
        print(migration_state(connection, ScriptDirectory.from_config(Config("alembic.ini"))))
    engine.dispose()


if __name__ == "__main__":
    main()
