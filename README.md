# 跟单管理系统

本仓库包含管理员网页端、服务器后端，以及管理员和工厂共用的一套微信小程序。一期业务范围以 [一期需求 V1.60](docs/一期/requirements/一期需求文档.md) 为准，目前处于一期验收和反馈迭代阶段。收货核对、返修草稿及生产 CD 已进入 `main`；生产版本工作流的验证状态与未完成验收见[里程碑与决策记录](docs/一期/project/一期里程碑与决策记录.md)。二期已开始[需求建设](docs/二期/project/二期需求建设计划.md)，尚未进入功能开发。

## 业务用途与角色

系统用于生产部与外协工厂协作，串联订单导入与派工、加工合同导出、工厂装箱发货、管理员收货核对、退回补发和质检返修。MySQL 保存正式业务事实，飞书提供订单来源，聚水潭提供产品资料；一期不自动回写飞书，也不保存加工单价和合同金额。

| 使用者 | 主要入口与职责 |
|---|---|
| 管理员 | 网页端处理订单、基础资料、收货、返修及工厂用户；管理员小程序用于移动查询 |
| 最高管理员 | 具有管理员业务权限，另可管理普通管理员启停；通过同一飞书登录入口识别 |
| 工厂用户 | 小程序仅访问所属工厂任务，装箱发货、申请撤回并提交返修发回记录 |

## 阅读入口

- 了解业务范围：[一期需求](docs/一期/requirements/一期需求文档.md)。
- 接手开发：[技术设计](docs/一期/project/一期技术设计方案.md)、[数据字典与关系图](docs/一期/project/一期数据字典与关系图.md)、[API 使用说明](docs/一期/project/一期API使用说明.md)。
- 检查交付：[验收矩阵](docs/一期/project/一期验收与需求追溯矩阵.md)、[版本发布记录](docs/一期/project/一期版本发布记录.md)。
- 运行与维护：[部署与运维手册](docs/一期/project/一期部署与运维手册.md)、[维护与交接说明](docs/一期/project/一期维护与交接说明.md)。
- 日常操作：[管理员网页操作手册](docs/一期/manuals/管理员网页操作手册.md)、[工厂小程序操作手册](docs/一期/manuals/工厂小程序操作手册.md)。

## 目录

- `server/`：FastAPI API、后台 worker、MySQL 迁移与通用基础设施；
- `admin-web/`：Vue 3 管理员网页端；
- `miniprogram/`：微信原生 TypeScript 小程序；
- `docs/`：按一期、二期组织需求、技术设计、计划与工单，共用规范和参考资料独立保存，见[文档目录](docs/README.md)；
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

`.github/workflows/release.yml` 只在推送 `v*` 版本标签时运行。它会先核验标签同一提交的最新 `main` push 完整 CI 已成功，不重复运行 CI，再使用仓库自带的 `GITHUB_TOKEN` 发布两个 GHCR 镜像：

- `ghcr.io/kocotree/order-tracking-server:<version>`；
- `ghcr.io/kocotree/order-tracking-admin-web:<version>`。

API 和 worker 共用 server 镜像并使用不同启动命令；微信小程序不发布 Docker 镜像。服务器版本 `v1.0.0` 已存在，后续按已批准的新版本号发布，不复用或覆盖已有标签。创建和推送版本标签需要用户明确授权。

推送普通 `main` 提交不会发布 GHCR 镜像。用户主动推送已批准版本标签即授权该版本生产部署；两个镜像成功后会自动备份、迁移、更新生产服务并检查健康，无需手动触发 CD。测试和生产继续使用独立 Compose、环境配置和数据。详细发布与回滚步骤见 [部署说明](deploy/README.md)。部署时固定使用版本标签，不使用浮动的 `latest`。

## 配置与安全

- `.env`、真实 AppID、AppSecret、Token、数据库密码和生产数据不得提交；
- 本地开发和自动化测试不得连接生产飞书、聚水潭、微信、OSS、MySQL 或公司 ECS；
- 开发、测试和生产必须使用不同数据库和最小权限账号；
- GHCR 发布使用工作流内置的 `GITHUB_TOKEN`，不得把个人 Token 或服务器拉取凭证写入仓库；
- 本地自动化、微信开发者工具、真实外部联调、GHCR 发布和 ECS 部署是不同验收层级，不能互相替代。
