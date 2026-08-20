# 服务器后端

当前已包含 S00 工程基础设施和 S01 管理员身份、申请、审核、跨端绑定与会话模块。
未显式启用本地演示模式时，飞书、短信、微信和头像存储适配器保持禁用，不会静默调用外部服务。

## 本地检查

先在仓库根目录复制本地配置并启动 MySQL 8：

```bash
cp .env.example .env
docker compose up -d --wait mysql-dev mysql-test
```

再进入本目录执行：

```bash
set -a
source ../.env
set +a
uv sync --locked
uv run alembic upgrade head
uv run ruff check .
uv run mypy app
uv run pytest
uv run python -m scripts.export_openapi --check
```

启动 API：

```bash
uv run uvicorn app.main:create_app --factory --reload
```

启动 worker：

```bash
uv run python -m app.worker
```

API 公开工程检查入口为 `/health/live` 和 `/health/ready`。真实外部身份与文件适配器尚未配置；S01 本地演示不连接飞书、短信、微信或正式对象存储。

## S01 本地演示

先把一个独立的本地 MySQL 8 数据库迁移到最新版本，再以以下非生产环境变量启动 API：

```bash
export ORDER_TRACKING_APP_ENV=local_demo
export ORDER_TRACKING_DATABASE_URL='mysql+pymysql://本地用户:本地密码@127.0.0.1:3308/独立演示库?charset=utf8mb4'
export ORDER_TRACKING_IDENTITY_TOKEN_SECRET="$(openssl rand -hex 32)"
export ORDER_TRACKING_PHONE_ENCRYPTION_SECRET="$(openssl rand -hex 32)"
export ORDER_TRACKING_PHONE_DIGEST_SECRET="$(openssl rand -hex 32)"
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

管理员网页端点击“通过飞书登录”后会进入只在 `local_demo` 下注册的身份选择页。演示申请人使用不可真实投递的合成号码 `10000000000`，验证码为 `123456`。该模式使用假飞书、假短信、假微信和内存头像存储，仅用于本机验收；不要把 `local_demo` 用于共享测试或生产环境。
