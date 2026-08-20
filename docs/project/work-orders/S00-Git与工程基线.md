# S00 Git 与工程基线开发工单

> 状态：已完成
>
> 工单编号：S00
>
> 日期：2026-08-20
>
> 需求基线：`docs/requirements/一期需求文档.md` V1.40
>
> 技术基线：`docs/project/一期技术设计方案.md` V1.0
>
> 计划基线：`docs/project/一期开发计划.md` V1.0

## 1. 工单目标

本工单只完成正式开发开始前的 Git、目录、工具链、环境和自动化检查基线，不实现登录、产品、工厂、订单、发货、返修、合同或通知等业务功能。

完成后必须得到以下结果：

1. 已确认的 V1.40 文档和原型修改形成清晰、可回退的基线提交；
2. 正式实现使用独立 `server/`、`admin-web/` 和 `miniprogram/` 目录；
3. 后端、管理员网页端和微信小程序空工程可以安装、检查、测试和构建；
4. 本地开发库与自动化测试库使用真实 MySQL 8 且相互隔离；
5. API、worker、请求编号、统一错误、结构化日志、审计、幂等和后台任务基础设施有最小可测试入口；
6. 锁文件、示例配置、容器构建和持续集成检查可以复现；
7. 仓库不包含真实 AppID、数据库密码、Token、密钥或生产数据；
8. S00 验收完成前不创建其他开发 Worktree。

## 2. 当前只读核对结果

以下是工单编写时的实际状态，不代表已经完成 S00：

| 项目 | 当前结果 | S00 处理 |
|---|---|---|
| Git | 已是 Git 仓库，分支为 `main`，当前提交 `7165a43` | 保留现有原型提交历史，不重新初始化仓库 |
| 远端 | 当前没有配置 Git remote | S00 不擅自创建远端或推送 |
| 工作区 | V1.39 原型、V1.40 文档和项目规则存在未提交修改 | 复核、验证后按逻辑选择性提交 |
| 参考图片 | 两张管理员小程序参考 PNG 已确认删除 | 随已确认资料基线提交删除 |
| 正式代码 | 尚无 `server/`、`admin-web/`、`miniprogram/` | 按已批准技术设计新建 |
| 本机 | Apple Silicon，macOS 26.5 | 所有本地命令兼容 arm64，不硬编码 Homebrew 路径 |
| Python | 系统 `python3` 为 3.9.6，已安装 uv 0.12.3 | 不使用已停止支持的系统 Python；由 uv 管理项目 Python 3.13 |
| Node.js | 本机 Node.js 26.7.0 为 Current，pnpm 11.22.0 | 项目固定 Node.js 24 LTS，并在 `package.json` 固定 pnpm 版本 |
| Docker | Docker 29.6.2 可用 | 用容器提供 MySQL 8 开发库和测试库 |
| MySQL CLI | 本机未安装 | 不安装系统 MySQL；通过 Docker 健康检查和容器内客户端验证 |

Python 3.13 目前处于官方 bugfix 支持期，Node.js 24 目前是官方 LTS；具体补丁版本和项目依赖版本由锁文件固定。S00 不使用本机 Node.js 26 Current 作为项目基线。

## 3. 实施顺序

### 3.1 固化已确认资料与原型基线

1. 重新检查当前所有修改的来源和范围，不回滚或覆盖已有改动；
2. 对管理员网页端 V1.39 关联 JavaScript 执行 `node --check`，对全部差异执行 `git diff --check`；
3. 复核 V1.40 需求、术语、技术设计、开发计划、页面地图、里程碑和项目规则的一致性；
4. 取得用户对两张参考 PNG 的处理决定；
5. 按逻辑选择性提交，不把未确认删除或无关文件混入提交：
   - 管理员网页端手动获取飞书新订单原型及对应说明；
   - V1.40 需求、技术设计 V1.0、开发计划 V1.0、术语和项目状态；
   - 参考 PNG 只有在用户明确决定后才恢复或提交删除；
6. 确认 `main` 工作区干净后，从该基线创建 `codex/s00-engineering-baseline` 分支；
7. S00 只在当前 Local 工作区串行实施，不创建第二个 Worktree。

### 3.2 固定运行时与根目录规则

新增或调整：

- `.python-version`：Python 3.13；
- `.node-version`：Node.js 24；
- `.editorconfig`：UTF-8、LF、基础缩进和文件末尾换行；
- `.gitattributes`：文本换行和常见二进制文件规则；
- `.gitignore`：Python、Node、微信开发者工具、本地环境、测试、构建和 IDE 产物；
- `.env.example`：只提供变量名和本地示例，不包含真实凭证；
- `README.md`：安装、启动、检查和目录说明；
- `compose.yaml`：本地开发与测试基础服务；
- `.github/workflows/ci.yml`：持续集成检查定义。

不修改系统 Python、系统 Node.js、全局代理或 Docker 全局设置。需要的 Python 版本由 uv 获取；Node.js 24 的本机切换方式只记录，不静默安装版本管理器。

### 3.3 后端与 worker 空工程

在 `server/` 建立：

```text
server/
├── app/
│   ├── api/
│   ├── modules/
│   ├── adapters/
│   ├── db/
│   ├── worker/
│   └── settings/
├── migrations/
├── tests/
├── alembic.ini
├── Dockerfile
├── pyproject.toml
└── uv.lock
```

最小实现包含：

- FastAPI 应用工厂；
- `/health/live` 存活检查；
- `/health/ready` MySQL 就绪检查；
- `/api/v1` 路由前缀；
- 统一错误响应和 `requestId`；
- 结构化日志与敏感字段过滤入口；
- SQLAlchemy 2 同步 Session、事务封装和 PyMySQL 驱动；
- Alembic 配置和可在空库执行的初始迁移；
- worker 启动、任务领取和安全停止入口；
- S00 计划已明确的通用持久化基础：`audit_logs`、`idempotency_records`、`background_jobs`、`outbox_messages`；
- 外部系统假适配器接口骨架，不连接飞书、聚水潭、微信、短信或正式 MinIO；
- OpenAPI 文件导出入口，作为后续 TypeScript 类型来源。

初始迁移不得创建用户、产品、工厂、订单、发货、返修或合同业务表。

后端使用 uv 管理 Python、`.venv` 和锁文件。基础检查使用 Ruff、mypy 和 pytest；MySQL 集成测试不得用 SQLite 替代。

### 3.4 管理员网页端空工程

在 `admin-web/` 建立 Vue 3、TypeScript、Vite 和 Element Plus 工程，包括：

- `src/api/` 统一请求和 OpenAPI 类型位置；
- `src/modules/`、`src/pages/`、`src/components/`、`src/stores/` 目录；
- Vue Router 基础路由；
- 最小应用入口、加载失败提示和404入口；
- API 基地址通过环境变量读取；
- Vitest 与 Vue Test Utils 基础测试；
- ESLint、TypeScript 检查和生产构建脚本；
- 只返回静态文件的内部 Nginx 容器配置和 Dockerfile。

S00 页面只用于证明应用可启动和构建，不设计或实现任何业务页面，也不偏离已确认原型增加可见功能。

### 3.5 微信小程序空工程

在 `miniprogram/` 建立管理员和工厂共用的一套微信原生 TypeScript 工程，包括：

- `miniprogram/api/`、`pages/`、`modules/`、`components/`、`utils/`；
- 最小 `app.ts`、`app.json`、`app.wxss` 和启动占位页；
- API 基地址和环境选择入口；
- 可独立测试的 TypeScript 工具入口；
- ESLint、TypeScript、Vitest 和构建检查；
- `project.config.json.example`，不写真实 AppID；
- README 中记录用户在微信开发者工具选择 `miniprogram/` 目录和填写自己 AppID 的步骤。

S00 不实现微信登录、手机号授权、角色跳转、管理员页面或工厂页面；这些属于 S01、S02 及后续工单。

### 3.6 本地 MySQL 与环境隔离

`compose.yaml` 至少提供：

- `mysql-dev`：本地开发数据库；
- `mysql-test`：自动化测试数据库；
- 两个服务使用不同数据库、账号、端口和数据卷；
- 仅绑定本机地址，不暴露到公网；
- 使用 MySQL 8.0、`utf8mb4` 和健康检查；
- 密码从本地 `.env` 读取，仓库只保存 `.env.example`。

S00 自动化测试只操作测试库。停止或清理测试容器不得删除开发库数据；不连接公司 ECS 正式数据库。

正式 MinIO、Traefik、域名、备份和生产 Compose 留到对应集成工单及 S12，S00 只保留适配接口和容器构建入口。

### 3.7 持续集成与容器检查

CI 定义至少包含：

- 后端依赖锁定安装、Ruff、mypy、pytest 和 Alembic 空库迁移；
- 管理员网页端冻结锁文件安装、ESLint、TypeScript、Vitest 和生产构建；
- 小程序冻结锁文件安装、ESLint、TypeScript、Vitest 和构建检查；
- OpenAPI 类型无未提交漂移；
- server 和 admin-web Docker 镜像构建；
- `git diff --check`。

当前没有 Git remote，因此 S00 只提交 CI 文件并在本机执行等价命令，不声称远程 CI 已实际运行。

## 4. 文件范围

| 范围 | 本工单允许修改 |
|---|---|
| 根目录 | Git规则、运行时版本、README、示例环境、Compose、CI |
| `server/` | 后端、worker、通用基础表、迁移、测试、锁文件和镜像 |
| `admin-web/` | 管理员网页空工程、测试、锁文件和静态镜像 |
| `miniprogram/` | 单一微信小程序空工程、测试、示例配置和说明 |
| `docs/project/` | 本工单、里程碑和S00实施结果 |
| 已确认原型和V1.40文档 | 只用于形成基线提交，不在S00重新设计页面或业务规则 |

除用户明确决定的两张参考 PNG 外，不删除、移动或重命名现有原型、参考资料和历史文档。

## 5. 测试与验收

### 5.1 后端 TDD 场景

先建立失败测试，再完成最小实现：

1. `/health/live` 返回存活状态和 `requestId`；
2. MySQL 可用时 `/health/ready` 成功，不可用时明确失败；
3. 未处理异常转换为统一错误结构，不泄露堆栈和密钥；
4. 请求编号由响应、日志和审计入口贯通；
5. 幂等键、后台任务和发件箱唯一约束阻止重复；
6. worker 只领取可执行任务并能在重启后继续；
7. Alembic 可以从空 MySQL 8 测试库升级到最新版本。

### 5.2 前端与小程序检查

- 管理员网页入口可以渲染，API 配置从环境读取，基础错误可展示；
- 管理员网页路由、类型检查、单元测试和生产构建通过；
- 小程序 TypeScript 与单元测试通过；
- 用户在微信开发者工具中选择 `miniprogram/` 后可以编译最小占位页；
- S00 不运行完整业务 Playwright 流程，不把空工程页面当作业务原型验收。

### 5.3 必须实际执行的检查

实施时根据最终脚本名称执行等价命令，至少包括：

```text
docker compose config
docker compose up -d mysql-dev mysql-test

cd server
uv sync --locked
uv run ruff check .
uv run mypy app
uv run pytest
uv run alembic upgrade head

cd admin-web
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build

cd miniprogram
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build

git diff --check
```

还必须执行 server 与 admin-web Docker 镜像构建、OpenAPI 类型漂移检查和仓库敏感信息检查。未运行的检查必须说明原因和影响。

### 5.4 人工验收

1. 打开管理员网页空工程，确认只有工程占位内容且无业务功能；
2. 在微信开发者工具选择 `miniprogram/`，确认单一小程序工程可以编译；
3. 停止测试 MySQL 后验证就绪检查失败，再恢复服务并验证成功；
4. 查看 Git 提交和工作区，确认已批准资料基线与 S00 工程提交可以分别回退；
5. 确认没有真实 AppID、数据库密码、Token、密钥或生产数据进入 Git。

## 6. 提交与回滚

### 6.1 提交原则

- 先在 `main` 上提交已确认的原型和 V1.40 正式资料基线；
- 再创建 `codex/s00-engineering-baseline` 分支实施正式工程；
- S00 工程按根目录/后端、管理员网页、小程序和 CI 的可验证结果形成少量逻辑提交；
- 只暂存本工单明确文件，不使用会覆盖用户改动的 reset 或 checkout；
- 当前没有 remote，不执行 push 或创建 PR。

### 6.2 回滚

- 已提交变更使用新提交执行可追溯回滚，不改写历史；
- 本地测试数据库和容器只清理 S00 明确命名的测试资源；
- 不删除开发数据卷，除非用户明确要求；
- 生产数据库、ECS、正式 MinIO 和付费资源不在本工单范围内；
- 工程基线未通过时停留在 S00，不创建 S01 工单或并行 Worktree。

## 7. 明确不做

- 不实现任何一期业务表、业务接口或正式页面；
- 不接入真实飞书、聚水潭、微信、短信或 MinIO 凭证；
- 不部署 ECS、配置正式域名、Traefik、HTTPS、备份或告警；
- 不创建两个小程序项目；
- 不沿用旧 CloudBase 正式实现；
- 不安装系统 MySQL，不修改全局代理或系统级运行时配置；
- 不删除来源不明的文件，不处理本工单之外的历史问题；
- 不因本地构建通过而声称真实业务或生产环境已经完成。

## 8. 开工确认门（已通过）

> 确认结果：用户已于 2026 年 8 月 20 日确认本工单整体范围、删除两张参考图片、使用 Python 3.13 和 Node.js 24 LTS、先提交资料基线再建立 S00 分支，以及 S00 不部署生产环境。工单已进入实施。

已确认：

1. 本工单整体范围；
2. 两张参考图片 `admin-miniprogram-order-detail.png`、`admin-miniprogram-order-list.png` 是恢复保留，还是确认删除；
3. 同意正式项目使用 Python 3.13 和 Node.js 24 LTS；
4. 同意先提交当前已确认资料与原型基线，再创建 `codex/s00-engineering-baseline` 分支；
5. 同意 S00 只建立本地开发/测试和 CI 基础，不部署生产环境。

上述确认门已通过，可以按本工单实施正式目录、依赖、数据库容器和分支。

## 9. 实施结果

S00 已于 2026 年 8 月 20 日完成，未实现任何一期业务功能，也未连接生产环境或真实外部系统。

### 9.1 提交

- `d2e91ef`：管理员网页端手动获取飞书新订单原型；
- `8c1e1c9`：V1.40 正式资料、需求 Markdown 和两张参考图片删除基线；
- `f7f160d`：根目录规则、MySQL 8 开发/测试环境、后端、worker、迁移和通用基础设施；
- `0b33012`：管理员网页端空工程；
- `9b7bf13`：单一微信原生 TypeScript 小程序空工程；
- `9a27310`：持续集成检查；
- `6a3f168`：忽略微信开发者工具在 TypeScript 源码旁生成的 JavaScript 编译产物。

### 9.2 自动检查

- `docker compose config` 通过，`mysql-dev`、`mysql-test` 均为健康状态且端口、账号、数据库和数据卷隔离；
- 后端冻结依赖安装、Ruff、mypy、Alembic 升级与模型漂移检查、OpenAPI 漂移检查通过，pytest 共 11 个测试通过；
- Alembic 已在单独创建的空 MySQL 8 数据库从零升级到最新版本并核对四张通用基础表，验证后删除该临时数据库；
- 管理员网页端和小程序均在 Node.js 24 容器内完成冻结锁文件安装、ESLint、TypeScript、Vitest 和构建检查，各 1 个测试通过；
- server 与 admin-web Docker 镜像均构建成功；
- 仓库敏感信息扫描、旧 XML 引用检查、CI YAML 解析和 `git diff --check` 通过。

### 9.3 运行与人工验收

- API 容器的 `/health/live`、`/health/ready` 正常；停止测试 MySQL 后就绪检查返回 503，恢复数据库后重新返回 200；
- 管理员网页容器的根页和 404 路由已在真实浏览器打开，页面仅显示 S00 工程占位内容且无控制台错误；
- 微信开发者工具 Stable 2.01.2510290 已用游客 AppID 导入 `miniprogram/` 并编译，成功显示 `pages/index/index` 占位页，项目“问题”面板为 0；游客模式产生的开发工具内部接口警告不来自项目源码；
- 本地 `project.config.json` 和开发者工具生成的 `project.private.config.json` 均被 Git 忽略，未开启开发者工具服务端口，未登录、预览、上传或使用正式 AppID；
- 再次用测试号导入时由开发者工具生成的默认 `pages/index/index.js` 已移出项目，后续同类 JavaScript 编译产物由 Git 忽略，TypeScript 源码继续作为唯一正式来源；
- 本地临时 API、网页验收容器已停止；MySQL 开发库和测试库保持健康运行，未删除任何数据卷。

### 9.4 下一步边界

阶段 5 已完成。下一步只允许先编写并确认 S01 工单；S01 未确认前不开始登录、身份绑定或其他业务功能编码，也不创建并行 Worktree。
