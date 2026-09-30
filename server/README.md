# 服务器后端

当前包含身份、工厂、产品／SKU图片、自动订单同步与派工、合同和箱贴、发货收货、返修、通知审计、Codex MCP和来货出入机器人。完整交付入口见[交付清单](../docs/shared/delivery/交付清单.md)，接口与运维见[接口说明](../docs/shared/delivery/接口与外部集成说明.md)及[运维手册](../docs/shared/delivery/部署与运维手册.md)。
未显式启用本地演示模式时，未配置的外部适配器保持禁用并明确失败。管理员飞书登录使用已验证手机号自动授予普通管理员角色。

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
ORDER_TRACKING_DATABASE_URL="$ORDER_TRACKING_TEST_DATABASE_URL" uv run pytest
uv run python -m scripts.export_openapi --check
```

启动 API：

```bash
uv run uvicorn app.main:create_app --factory --reload
```

启动 worker（管理进程会启动同步、来货出入、通知三个子进程）：

```bash
uv run python -m app.worker
```

API 存活和就绪入口为 `/health/live` 和 `/health/ready`。外部身份、文件与产品适配器的启用取决于当前环境受控配置；本地演示使用独立假适配器，真实联调按运维手册配置并单独验收。

## 本地身份演示

先把一个独立的本地 MySQL 8 数据库迁移到最新版本，再以以下非生产环境变量启动 API：

```bash
export ORDER_TRACKING_APP_ENV=local_demo
export ORDER_TRACKING_DATABASE_URL='mysql+pymysql://本地用户:本地密码@127.0.0.1:3308/独立演示库?charset=utf8mb4'
export ORDER_TRACKING_IDENTITY_TOKEN_SECRET="$(openssl rand -hex 32)"
export ORDER_TRACKING_PHONE_ENCRYPTION_SECRET="$(openssl rand -hex 32)"
export ORDER_TRACKING_PHONE_DIGEST_SECRET="$(openssl rand -hex 32)"
uv run uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

管理员网页端点击“通过飞书登录”后会进入只在 `local_demo` 下注册的身份选择页。演示申请人的假飞书资料包含不可真实投递的合成号码 `10000000000`，申请页只展示脱敏号码并直接提交，不发送短信。该模式使用假飞书、假微信和内存头像存储，并显式写入 12 条七分类启用假产品用于验收只读列表；这些记录不是真实聚水潭数据。本地演示仅用于本机验收，不要用于共享测试或生产环境。

## 产品同步内部任务

未配置聚水潭 OpenAPI 时，worker 的产品适配器保持禁用并明确失败。运维可用 `uv run python -m scripts.enqueue_product_sync --help` 查看内部任务参数；真实凭据只通过服务器受控配置注入，不写入命令、Git 或日志。

按精确名称或款号补拉只查询匹配商品的全部 SKU 分页，默认预览，不写库：

```bash
uv run python -m scripts.enqueue_product_sync targeted --name '商品精确名称'
uv run python -m scripts.enqueue_product_sync targeted --i-id '商品款号'
uv run python -m scripts.enqueue_product_sync targeted --i-id '商品款号' --commit '预览digest'
```

执行时重新读取来源及目标库，预览发生变化则停止并重新预览。同名多款需要指定款号；重复运行不新增相同 SKU。停用、范围外及旧来源在预览中报告；身份或同时间规格冲突阻止整批写入。定向批次使用原同步互斥，成功不推进全库游标；失败整批回滚并记录失败批次。

Issue #188 图片补齐：`uv run python -m scripts.enqueue_product_sync images` 默认预览本系统所有现有货号的 SKU 图片；确认环境与摘要后，使用 `images --commit '预览digest'` 执行。来源或目标状态变化会拒绝旧摘要，重新预览后重试。按 SKU 独立事务保存图片和审计，已完成项可复用，失败项会报告；输出 matched、reused、download（待下载）、downloaded（已下载）、missing、failed、unmatched 及逐 SKU 结果，有失败或未匹配项时退出码为 1。

该工具实际读取对象后才判断复用，403 等访问错误不会计为可复用；只给来源匹配的 SKU 使用旧产品图。缺失/损坏对象重新缓存，新内容按哈希保存，历史对象和订单/合同快照保留。同色不同尺码图片按各 SKU 来源分别保存；代表图由合同和箱贴导出按分组选择。生产迁移与补齐须按具体范围授权。

已有候选的分类汇总按本地明细重算，默认预览，保留状态、日期人工覆盖、数量和历史：

```bash
uv run python -m scripts.enqueue_product_sync categories
uv run python -m scripts.enqueue_product_sync categories --commit '预览digest'
```

无明细或含未知分类的候选只报告，人工核对后再处理。镜像包含该运维模块，可在 API 容器内以 `/app/.venv/bin/python -m scripts.enqueue_product_sync` 执行；环境由对应容器配置决定，须核对输出中的环境与数据库。部署和线上执行按项目确认门进行。
