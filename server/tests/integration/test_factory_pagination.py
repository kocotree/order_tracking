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


def test_factory_global_page_filters_and_snapshot_batches(test_database_engine: Engine) -> None:
    from app.db.models import FactoryContact

    sessions = sessionmaker(test_database_engine, class_=Session)
    with sessions.begin() as session:
        session.add(
            User(user_id="page-admin", role="admin", is_enabled=True, feishu_display_name="测试")
        )
        session.add_all(
            [
                Factory(
                    factory_id=f"page-{i}",
                    supplier_number=f"A{i:03d}",
                    factory_name=f"工厂{25 - i}",
                    legal_name="资料" if i % 2 else "",
                    factory_code=f"CODE{i}",
                    address="地址",
                    legal_representative="代表",
                )
                for i in range(25)
            ]
        )
        session.flush()
        session.add_all(
            [
                FactoryContact(
                    factory_id=f"page-{i}",
                    name=f"联系人{25 - i}",
                    phone=f"电话{25 - i}",
                    display_order=j,
                    is_primary=j == 0,
                )
                for i in range(25)
                for j in range(2)
            ]
        )
        session.add(
            User(
                user_id="factory-user",
                role="factory",
                factory_id="page-24",
                is_enabled=True,
                feishu_display_name="工厂用户",
            )
        )
    service = FactoryAccessService(sessions)
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(test_database_engine, "before_cursor_execute", record)
    try:
        page, total = service.page_factories(actor_id="page-admin", page=2, sort_by="factoryName")
    finally:
        event.remove(test_database_engine, "before_cursor_execute", record)
    assert total == 25
    assert [f.factory_name for f in page] == [f"工厂{i}" for i in range(11, 21)]
    assert len(statements) == 4  # permission, global count, page, batched contacts
    assert all(len(f.contacts) == 2 for f in page)
    for field in [
        "supplierNumber",
        "factoryName",
        "legalName",
        "contactName",
        "contactPhone",
        "contractStatus",
        "connectedUsers",
    ]:
        for direction in ["asc", "desc"]:
            result, count = service.page_factories(
                actor_id="page-admin", page_size=100, sort_by=field, sort_order=direction
            )
            assert len(result) == count == 25
            if field in {"factoryName", "contactName", "contactPhone"}:
                expected = list(range(1, 26))
                if direction == "desc":
                    expected.reverse()
                assert [x.factory_name for x in result] == [f"工厂{i}" for i in expected]
    selected, count = service.page_factories(
        actor_id="page-admin", keyword="联系人1", access_status="connected"
    )
    assert count == 1 and selected[0].connected_users == 1
    old = service.list_factories(actor_id="page-admin", contract_status="complete")
    new, count = service.page_factories(
        actor_id="page-admin", contract_status="complete", page_size=100
    )
    assert new == old and count == 12
    assert service.page_factories(actor_id="page-admin", page=99) == ([], 25)


def test_factory_page_measurement(test_database_engine: Engine, test_database_url: str) -> None:
    import time

    from fastapi.testclient import TestClient

    from app.db.models import FactoryContact
    from app.main import create_app
    from app.modules.identity_access import IdentityAccessService

    sessions = sessionmaker(test_database_engine, class_=Session)
    with sessions.begin() as session:
        session.add(
            User(user_id="measure-admin", role="admin", is_enabled=True, feishu_display_name="测试")
        )
    identity = IdentityAccessService(sessions)
    token = identity.issue_session(user_id="measure-admin", terminal="web")
    service = FactoryAccessService(sessions)
    app = create_app(
        database_url=test_database_url, identity_service=identity, factory_service=service
    )
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set("ot_web_session", token.access_token)
        for start, end in [(0, 20), (20, 100)]:
            with sessions.begin() as session:
                session.add_all(
                    [
                        Factory(
                            factory_id=f"measure-{i}",
                            supplier_number=f"M{i:03d}",
                            factory_name=f"工厂{i}",
                        )
                        for i in range(start, end)
                    ]
                )
                session.flush()
                session.add_all(
                    [
                        FactoryContact(
                            factory_id=f"measure-{i}",
                            name="测试联系人",
                            phone="123",
                            display_order=0,
                            is_primary=True,
                        )
                        for i in range(start, end)
                    ]
                )
            measurements = []
            for path in ["/api/v1/admin/factories", "/api/v1/admin/factories/page"]:
                statements = []

                def record(
                    conn, cursor, statement, parameters, context, executemany, sink=statements
                ):
                    sink.append(statement)

                event.listen(test_database_engine, "before_cursor_execute", record)
                try:
                    before = time.perf_counter()
                    response = client.get(path)
                    duration = (time.perf_counter() - before) * 1000
                finally:
                    event.remove(test_database_engine, "before_cursor_execute", record)
                assert response.status_code == 200
                measurements.append((len(statements), len(response.content), round(duration, 2)))
            assert measurements[1][0] < measurements[0][0]
            assert measurements[1][1] < measurements[0][1]
            print(f"FACTORY_MEASURE n={end} old/new (sql,bytes,ms)={measurements}")
