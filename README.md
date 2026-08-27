# 跟单管理系统

本仓库包含管理员网页端、服务器后端，以及管理员和工厂共用的一套微信小程序。一期业务范围以 `docs/requirements/一期需求文档.md` V1.55 为准；S01 至 S10 已合并到 `main`，真实微信登录接缝已补齐，下一阶段按已确认工单实施 S11 通知提醒与审计收口。

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
pnpm generate:api
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

## 持续集成与镜像发布

普通分支推送和 Pull Request 会运行 `.github/workflows/ci.yml`，包括仓库空白检查、MySQL 8 迁移与后端测试、管理员网页端和小程序检查，以及 server、admin-web Docker 镜像构建。只有全部任务显示绿色勾才表示 CI 通过。

查看最近的 CI：

```bash
gh run list --workflow CI --limit 5
gh run watch <run-id> --exit-status
gh run view <run-id> --log-failed
```

`.github/workflows/release.yml` 只在推送 `v*` 版本标签时运行。它会先复用完整 CI，成功后使用仓库自带的 `GITHUB_TOKEN` 发布两个 GHCR 镜像：

- `ghcr.io/kocotree/order-tracking-server:<version>`；
- `ghcr.io/kocotree/order-tracking-admin-web:<version>`。

API 和 worker 共用 server 镜像并使用不同启动命令；微信小程序不发布 Docker 镜像。创建首个版本示例：

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

推送普通 `main` 提交不会发布 GHCR 镜像。发布镜像也不等于部署 ECS；测试环境和生产环境仍需独立的部署 Compose、服务器环境变量、HTTPS 路由和明确的人工发布确认。部署时固定使用版本标签，不使用浮动的 `latest`。

## 配置与安全

- `.env`、真实 AppID、AppSecret、Token、数据库密码和生产数据不得提交；
- 本地开发和自动化测试不得连接生产飞书、聚水潭、微信、MinIO、MySQL 或公司 ECS；
- 开发、测试和生产必须使用不同数据库和最小权限账号；
- GHCR 发布使用工作流内置的 `GITHUB_TOKEN`，不得把个人 Token 或服务器拉取凭证写入仓库；
- 本地自动化、微信开发者工具、真实外部联调、GHCR 发布和 ECS 部署是不同验收层级，不能互相替代。
