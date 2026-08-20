# 服务器后端

S00 建立的 FastAPI、worker、MySQL 迁移和通用基础设施工程，不包含一期业务模块。

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

API 公开工程检查入口为 `/health/live` 和 `/health/ready`。真实外部系统适配器尚未配置，S00 不连接飞书、聚水潭、微信、短信或正式对象存储。
