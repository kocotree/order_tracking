from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Factory, FactoryApplication, User
from app.main import create_app
from app.modules.factory_access import FactoryAccessService
from app.modules.identity_access import IdentityAccessService


def test_people_pages_filter_sort_count_and_permissions(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    sessions = sessionmaker(test_database_engine, class_=Session)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"test-token",
        phone_encryption_secret=b"test-phone",
        phone_digest_secret=b"test-digest",
    )
    with sessions.begin() as session:
        session.add_all(
            [
                User(
                    user_id="super",
                    role="admin",
                    is_super_admin=True,
                    is_enabled=True,
                    feishu_display_name="Super",
                ),
                User(
                    user_id="ordinary",
                    role="admin",
                    is_super_admin=False,
                    is_enabled=True,
                    feishu_display_name="Ordinary",
                ),
                Factory(
                    factory_id="f1", supplier_number="F1", factory_name="Alpha", factory_code="AA"
                ),
                Factory(
                    factory_id="f2", supplier_number="F2", factory_name="Beta", factory_code="BB"
                ),
            ]
        )
        session.flush()
        for index in range(23):
            session.add(
                User(
                    user_id=f"u{index:02}",
                    role="factory",
                    is_enabled=True,
                    feishu_display_name=f"Worker {index:02}",
                    factory_id="f1" if index < 12 else "f2",
                    factory_position="owner",
                )
            )
            session.add(
                User(
                    user_id=f"a{index:02}",
                    role="admin",
                    is_enabled=True,
                    feishu_display_name=f"Admin {index:02}",
                )
            )
        session.flush()
        for index in range(23):
            session.add(
                FactoryApplication(
                    application_id=f"app{index:02}",
                    user_id=f"u{index:02}",
                    real_name=f"Worker {index:02}",
                    phone_encrypted="test",
                    phone_digest=f"digest{index}",
                    phone_masked="138****0000",
                    position="owner",
                    requested_factory_id="f1",
                    status="pending" if index < 12 else "rejected",
                    submitted_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        factory_service=FactoryAccessService(sessions),
    )
    sql: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):  # type: ignore[no-untyped-def]
        sql.append(statement)

    event.listen(test_database_engine, "before_cursor_execute", capture)
    try:
        with TestClient(app, base_url="https://testserver") as client:
            client.cookies.set(
                "ot_web_session",
                identity.issue_session(user_id="super", terminal="web").access_token,
            )
            for role, total in [("factory", 23), ("admin", 25)]:
                result = client.get(
                    "/api/v1/admin/users",
                    params={
                        "role": role,
                        "page": 2,
                        "pageSize": 10,
                        "sortBy": "displayName",
                        "sortOrder": "asc",
                    },
                )
                assert result.status_code == 200
                data = result.json()
                assert data["total"] == total and len(data["items"]) == 10
                assert data["items"][0]["displayName"] == (
                    "Worker 10" if role == "factory" else "Admin 10"
                )
            filtered = client.get(
                "/api/v1/admin/users?role=factory&factoryId=f1&page=2&pageSize=10"
            ).json()
            assert filtered["total"] == 12 and len(filtered["items"]) == 2
            descending = client.get(
                "/api/v1/admin/users?role=factory&page=1&sortBy=displayName&sortOrder=desc"
            ).json()
            assert descending["items"][0]["displayName"] == "Worker 22"
            applications = client.get(
                "/api/v1/admin/factory-applications?status=pending&page=2&pageSize=10&sortBy=realName"
            ).json()
            assert applications["total"] == 12 and len(applications["items"]) == 2
            assert applications["items"][0]["realName"] == "Worker 10"
            outside = client.get("/api/v1/admin/users?role=factory&page=99").json()
            assert outside["items"] == [] and outside["total"] == 23
            assert client.get("/api/v1/admin/users?page=0").status_code == 422
            assert client.get("/api/v1/admin/factory-applications?pageSize=101").status_code == 422
            assert client.get("/api/v1/admin/users?sortBy=unknown").status_code == 422
            client.cookies.set(
                "ot_web_session",
                identity.issue_session(user_id="ordinary", terminal="web").access_token,
            )
            assert client.get("/api/v1/admin/users?role=admin&page=2").status_code == 403
            assert client.get("/api/v1/admin/users?role=factory&page=2").status_code == 200
            assert client.get("/api/v1/admin/factory-applications?page=2").status_code == 200
        assert any("LIMIT" in query and "factory_applications" in query for query in sql)
        assert any("LIMIT" in query and "users" in query for query in sql)
    finally:
        event.remove(test_database_engine, "before_cursor_execute", capture)
