from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.adapters.identity import ExternalIdentityUnavailable, FeishuProfile
from app.adapters.wechat import WechatProfile, WechatUnavailable

LOCAL_DEMO_FEISHU_SCOPE = "local-demo/feishu"
LOCAL_DEMO_WECHAT_SCOPE = "local-demo/wechat"
LOCAL_DEMO_PHONE = "10000000000"
LOCAL_DEMO_SUPER_PHONE = "10000000001"


class LocalDemoFeishuIdentity:
    _profiles = {
        "ordinary": FeishuProfile(
            subject="local-demo-ordinary",
            display_name="演示普通管理员",
            phone=LOCAL_DEMO_PHONE,
        ),
        "super": FeishuProfile(
            subject="local-demo-super",
            display_name="演示最高管理员",
            phone=LOCAL_DEMO_SUPER_PHONE,
        ),
    }

    @property
    def scope(self) -> str:
        return LOCAL_DEMO_FEISHU_SCOPE

    def authorization_url(self, *, state: str) -> str:
        return f"/api/v1/local-demo/feishu-authorize?{urlencode({'state': state})}"

    def exchange_code(self, *, code: str) -> FeishuProfile:
        try:
            return self._profiles[code]
        except KeyError as error:
            raise ExternalIdentityUnavailable("local demo identity is unavailable") from error


class LocalDemoWechatIdentity:
    @property
    def scope(self) -> str:
        return LOCAL_DEMO_WECHAT_SCOPE

    def exchange_login_code(self, *, code: str) -> WechatProfile:
        if not code:
            raise WechatUnavailable("local demo login code is missing")
        return WechatProfile(subject="local-demo-wechat-applicant")

    def exchange_phone_code(self, *, code: str) -> str:
        if not code:
            raise WechatUnavailable("local demo phone code is missing")
        return LOCAL_DEMO_PHONE


def create_local_demo_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/local-demo", include_in_schema=False)

    @router.get("/feishu-authorize", response_model=None)
    def authorize_feishu_identity(
        state: str,
        identity: str | None = Query(default=None),
    ) -> Response:
        if identity is not None:
            if identity not in {"ordinary", "super"}:
                raise HTTPException(status_code=422)
            callback_query = urlencode({"state": state, "code": identity})
            return RedirectResponse(
                f"/api/v1/auth/feishu/callback?{callback_query}",
                status_code=303,
            )

        ordinary_query = urlencode({"state": state, "identity": "ordinary"})
        super_query = urlencode({"state": state, "identity": "super"})
        html = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow">
    <title>本地身份演示</title>
    <style>
      body {{ margin: 0; background: #f5f7fa; color: #1f2937; font: 16px/1.6 sans-serif; }}
      main {{ width: min(520px, calc(100% - 40px)); margin: 12vh auto; padding: 32px;
        box-sizing: border-box; border-radius: 14px; background: white;
        box-shadow: 0 12px 32px rgba(31, 41, 55, .1); }}
      h1 {{ margin: 0 0 8px; font-size: 24px; }}
      .notice {{ color: #b45309; }}
      .actions {{ display: grid; gap: 12px; margin: 24px 0; }}
      a {{ padding: 11px 16px; border-radius: 8px; background: #1677ff; color: white;
        text-align: center; text-decoration: none; }}
      code {{ padding: 2px 6px; border-radius: 4px; background: #eef2f7; }}
    </style>
  </head>
  <body>
    <main>
      <h1>本地身份选择</h1>
      <p class="notice">仅限本机演示，不会连接真实飞书、短信或微信。</p>
      <div class="actions">
        <a href="/api/v1/local-demo/feishu-authorize?{escape(ordinary_query)}">普通管理员登录</a>
        <a href="/api/v1/local-demo/feishu-authorize?{escape(super_query)}">最高管理员登录</a>
      </div>
      <p>申请人手机号：<code>{LOCAL_DEMO_PHONE}</code></p>
    </main>
  </body>
</html>"""
        return HTMLResponse(
            html,
            headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
        )

    return router
