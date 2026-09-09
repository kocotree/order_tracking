from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Factory, User
from app.modules.factory_access import FactoryAccessService


def test_admin_options_are_complete_and_lightweight(test_database_engine: Engine) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session)
    with sessions.begin() as session:
        session.add(
            User(user_id="option-admin", role="admin", is_enabled=True, feishu_display_name="测试")
        )
        session.add_all(
            [
                Factory(
                    factory_id=f"opt-{i}",
                    supplier_number=f"A{i:03d}",
                    factory_name=f"工厂{i}",
                    is_enabled=i != 12,
                )
                for i in range(15)
            ]
        )
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_database_engine, "before_cursor_execute", record)
    try:
        rows = FactoryAccessService(sessions).list_admin_factory_options(actor_id="option-admin")
    finally:
        event.remove(test_database_engine, "before_cursor_execute", record)
    assert len(rows) == 15
    assert rows[12] == ("opt-12", "A012", "工厂12")
    assert (
        len(statements) == 2
    )  # admin permission + one projection, no contacts or user-per-factory
