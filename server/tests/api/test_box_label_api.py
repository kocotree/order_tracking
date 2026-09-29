
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.main import create_app
from app.modules.box_labels import BoxLabelService
from app.modules.box_labels.workbook import BoxLabelWorkbookRenderer
from app.modules.identity_access import IdentityAccessService
from tests.integration.test_contracts import ADMIN_ID, ORDER_ID, _seed_published_order


def test_box_label_api_requires_web_admin_and_csrf(
    test_database_engine: Engine, test_database_url: str
) -> None:
    _seed_published_order(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"box-label-api-token-secret",
        phone_encryption_secret=b"box-label-api-phone-encryption",
        phone_digest_secret=b"box-label-api-phone-digest",
    )
    web = identity.issue_session(user_id=ADMIN_ID, terminal="web")
    mini = identity.issue_session(user_id=ADMIN_ID, terminal="mini")
    service = BoxLabelService(
        sessions,
        renderer=BoxLabelWorkbookRenderer(),
        file_store=FakePrivateFileStore(bucket="box-label-api-test"),
    )
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        box_label_service=service,
    )
    url = f"/api/v1/admin/orders/{ORDER_ID}/box-labels"
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(url).status_code == 401
        client.headers["Authorization"] = f"Bearer {mini.access_token}"
        assert client.get(url).status_code == 401
        client.headers.pop("Authorization")
        client.cookies.set("ot_web_session", web.access_token)
        response = client.get(url)
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1
        group_id = response.json()["items"][0]["groupId"]
        export_url = f"{url}/{group_id}/exports"
        assert client.post(export_url).status_code == 403
        exported = client.post(export_url, headers={"X-CSRF-Token": web.csrf_token or ""})
        assert exported.status_code == 201
        download = client.get(exported.json()["downloadUrl"])
        assert download.status_code == 200
        assert download.content.startswith(b"PK")
        assert ".xlsx" in download.headers["content-disposition"]
