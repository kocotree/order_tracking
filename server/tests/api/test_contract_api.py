from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.private_files import FakePrivateFileStore
from app.main import create_app
from app.modules.contracts import ContractService
from app.modules.contracts.workbook import ContractWorkbookRenderer
from app.modules.identity_access import IdentityAccessService
from tests.integration.test_contracts import (
    ADMIN_ID,
    FACTORY_ID,
    ORDER_ID,
    _clean,
    _seed_published_order,
)


def test_contract_api_is_web_admin_only_and_downloads_private_xlsx(
    test_database_engine: Engine,
    test_database_url: str,
) -> None:
    _clean(test_database_engine)
    _seed_published_order(test_database_engine)
    sessions = sessionmaker(test_database_engine, class_=Session, expire_on_commit=False)
    identity = IdentityAccessService(
        sessions,
        token_secret=b"contract-api-token-secret",
        phone_encryption_secret=b"contract-api-phone-encryption",
        phone_digest_secret=b"contract-api-phone-digest",
    )
    web_session = identity.issue_session(user_id=ADMIN_ID, terminal="web")
    mini_session = identity.issue_session(user_id=ADMIN_ID, terminal="mini")
    template = Path(__file__).resolve().parents[2] / "app/templates/processing_contract_v1.xlsx"
    contract_service = ContractService(
        sessions,
        workbook_renderer=ContractWorkbookRenderer(template_path=template),
        file_store=FakePrivateFileStore(bucket="contract-api-test"),
        clock=lambda: datetime(2026, 8, 24, 11, 0, tzinfo=UTC),
    )
    app = create_app(
        database_url=test_database_url,
        identity_service=identity,
        contract_service=contract_service,
    )

    try:
        with TestClient(app, base_url="https://testserver") as anonymous:
            assert (
                anonymous.get(f"/api/v1/admin/orders/{ORDER_ID}/contracts").status_code
                == 401
            )

        with TestClient(app, base_url="https://testserver") as mini:
            mini.headers["Authorization"] = f"Bearer {mini_session.access_token}"
            assert mini.get(f"/api/v1/admin/orders/{ORDER_ID}/contracts").status_code == 401

        with TestClient(app, base_url="https://testserver") as client:
            client.cookies.set("ot_web_session", web_session.access_token)
            client.cookies.set("ot_csrf", web_session.csrf_token or "")
            listed = client.get(f"/api/v1/admin/orders/{ORDER_ID}/contracts")
            assert listed.status_code == 200
            assert listed.json()["items"][0]["eligible"] is True
            exported = client.post(
                f"/api/v1/admin/orders/{ORDER_ID}/contracts/{FACTORY_ID}/exports",
                json={"signingDate": date(2026, 8, 24).isoformat()},
                headers={
                    "X-CSRF-Token": web_session.csrf_token or "",
                    "Idempotency-Key": "contract-api-export",
                },
            )
            assert exported.status_code == 201
            payload = exported.json()
            assert payload["contractNo"] == "20260824-KK-HT"
            assert payload["downloadUrl"].endswith(
                f"/admin/contract-exports/{payload['exportId']}/download"
            )
            downloaded = client.get(payload["downloadUrl"])
            assert downloaded.status_code == 200
            assert downloaded.content.startswith(b"PK")
            assert "attachment" in downloaded.headers["content-disposition"]

        unavailable_service = ContractService(
            sessions,
            workbook_renderer=ContractWorkbookRenderer(template_path=template),
            file_store=FakePrivateFileStore(
                bucket="contract-api-unavailable", fail_put=True
            ),
            clock=lambda: datetime(2026, 8, 24, 11, 5, tzinfo=UTC),
        )
        unavailable_app = create_app(
            database_url=test_database_url,
            identity_service=identity,
            contract_service=unavailable_service,
        )
        with TestClient(unavailable_app, base_url="https://testserver") as client:
            client.cookies.set("ot_web_session", web_session.access_token)
            client.cookies.set("ot_csrf", web_session.csrf_token or "")
            failed = client.post(
                f"/api/v1/admin/orders/{ORDER_ID}/contracts/{FACTORY_ID}/exports",
                json={"signingDate": date(2026, 8, 24).isoformat()},
                headers={
                    "X-CSRF-Token": web_session.csrf_token or "",
                    "Idempotency-Key": "contract-api-store-unavailable",
                },
            )
            assert failed.status_code == 503
            assert failed.json()["code"] == "external_service_unavailable"
    finally:
        _clean(test_database_engine)
