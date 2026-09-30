import asyncio
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from app.api.identity import create_identity_router
from app.api.repairs import create_repair_router
from app.api.shipments import create_shipment_router


@pytest.mark.parametrize("kind", ["repair", "shipment", "avatar"])
def test_upload_authentication_and_processing_run_outside_event_loop(kind: str) -> None:
    loop_thread = get_ident()
    threads: list[int] = []
    identity = Mock()
    business = Mock()

    def authenticate(**kwargs):
        threads.append(get_ident())
        return SimpleNamespace(user_id="user", role="admin" if kind == "repair" else "factory",
                               factory_id="factory")

    def process(**kwargs):
        threads.append(get_ident())
        assert kwargs["content"] == b"upload-content"
        raise HTTPException(status_code=418, detail="test processing reached")

    identity.authenticate_session.side_effect = authenticate
    app = FastAPI()

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = "upload-test"
        return await call_next(request)

    if kind == "repair":
        business.create_preview.side_effect = process
        router = create_repair_router(
            workflow=business, previews=Mock(), confirmations=Mock(), returns=Mock(),
            identity=identity, file_store=Mock(), session_factory=Mock(),
        )
        path, field, expected = "/api/v1/admin/repair-previews", "file", 409
    elif kind == "shipment":
        business.upload_file.side_effect = process
        router = create_shipment_router(service=business, identity=identity)
        path, field, expected = "/api/v1/factory/shipments/drafts/draft/files", "file", 418
    else:
        identity.replace_mini_avatar.side_effect = process
        router = create_identity_router(identity)
        path, field, expected = "/api/v1/mini/me/avatar", "avatar", 418
    app.include_router(router)

    async def upload():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://testserver",
            cookies={"ot_web_session": "session"},
        ) as client:
            return await client.post(
                path, files={field: ("upload.bin", b"upload-content")},
                headers={"Authorization": "Bearer session", "Idempotency-Key": "upload",
                         "X-CSRF-Token": "csrf"},
            )

    assert asyncio.run(upload()).status_code == expected
    assert len(threads) == 2
    assert all(thread != loop_thread for thread in threads)
