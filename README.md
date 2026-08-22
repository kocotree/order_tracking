# 跟单管理系统

本仓库包含管理员网页端、服务器后端，以及管理员和工厂共用的一套微信小程序。当前已进入正式工程实施阶段；一期业务范围以 `docs/requirements/一期需求文档.md` V1.41 为准。

## 目录

- `server/`：FastAPI API、后台 worker、MySQL 迁移与通用基础设施；
- `admin-web/`：Vue 3 管理员网页端；
- `miniprogram/`：微信原生 TypeScript 小程序；
- `docs/`：需求、技术设计、开发计划、工单与参考资料；
- `prototype/`：已确认的低保真原型，仅作交互约束，不是正式运行代码。

## 固定工具链

- Python 3.13，由 uv 管理；
- Node.js 24 LTS；
- pnpm 11.22.0；
- Docker 与 Docker Compose；
- MySQL 8.0，开发库和测试库相互隔离。

不要使用系统 Python 安装项目依赖，也不要使用本机 Node.js 26 生成或更新锁文件。

## 首次启动

复制本地配置并只在被 Git 忽略的 `.env` 中填写本机开发值：

```bash
cp .env.example .env
docker compose up -d --wait mysql-dev mysql-test
```

初始化并检查后端：

```bash
cd server
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

检查管理员网页端：

```bash
cd admin-web
corepack enable
corepack prepare pnpm@11.22.0 --activate
pnpm install --frozen-lockfile
pnpm generate:api
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
```

检查微信小程序：

```bash
cd miniprogram
corepack enable
corepack prepare pnpm@11.22.0 --activate
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
```

微信开发者工具的导入步骤见 `miniprogram/README.md`。仓库只保存 `project.config.json.example`，不保存真实 AppID。

## 本地运行

后端：

```bash
cd server
uv run uvicorn app.main:create_app --factory --reload
```

管理员网页端：

```bash
cd admin-web
pnpm dev
```

API 存活和就绪入口分别为 `/health/live`、`/health/ready`。正式客户端只能通过同一套 HTTPS API 访问业务数据，不得直接连接 MySQL。

## 配置与安全

- `.env`、真实 AppID、AppSecret、Token、数据库密码和生产数据不得提交；
- S00 不连接正式飞书、聚水潭、微信、短信、MinIO 或公司 ECS；
- 开发、测试和生产必须使用不同数据库和最小权限账号；
- 当前三端页面只是工程占位，不代表业务功能已经实现。
