from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.modules.incoming_differences.bot import FeishuBotService, FeishuCallbackVerifier


def create_feishu_bot_router(
    *, service: FeishuBotService | None, verifier: FeishuCallbackVerifier | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/integrations/feishu", tags=["feishu-bot"])

    async def receive(request: Request, *, card: bool) -> JSONResponse:
        if service is None or verifier is None:
            return JSONResponse(status_code=503, content={"code": "feishu_bot_disabled"})
        body = await request.body()
        try:
            payload = verifier.verify(dict(request.headers), body)
        except ValueError:
            return JSONResponse(status_code=401, content={"code": "invalid_feishu_callback"})
        try:
            result = service.card_action(payload) if card else service.event(payload)
        except Exception:
            service.release_failed_event(payload)
            raise
        return JSONResponse(content=result)

    @router.post("/events")
    async def events(request: Request) -> JSONResponse:
        return await receive(request, card=False)

    @router.post("/card-actions")
    async def card_actions(request: Request) -> JSONResponse:
        return await receive(request, card=True)

    return router
