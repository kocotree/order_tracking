# Issue #155 MCP 文件与质检返修实施记录

基线：`c791bed`（#151 基础接入），分支：`codex/issue-155-mcp-excel-repair`。本分支未合并、部署或连接真实飞书与生产附件存储。

## 给 #153、#154 的文件契约

- 上传工具的顶层输入为 `files`，元素声明 `download_url`、`file_id` 必填及 `mime_type`、`file_name` 可选，工具描述符提供 `_meta["openai/fileParams"] = ["files"]`。服务器实际要求可验证的 `.xlsx` 文件名，按内容解析；每次最多 20 份，每份最多 20 MiB。官方[文件参数说明](https://developers.openai.com/plugins/reference)明确的是 ChatGPT 输入格式，Codex 0.149.1 尚无原生附件注入的实测证据。
- 下载统一调用 `app.mcp.files.download_descriptor(origin, path, filename, size_bytes, sha256)`，返回 `downloadUrl`、`filename`、`mimeType`、`sizeBytes`、`sha256`；领域工具另外返回业务 ID 和文件 ID。`path` 必须是固定的 `/api/v1/` 业务路径。合同与发货工具负责自己的受权下载 API，复用这个结果结构，不依赖返修模块。
- 返修示例为 `get_repair_download(repair_id, file_id)`。返回的地址位于本系统 HTTPS origin，要求本人 Web 登录；未登录时经现有飞书登录回到固定的下载路径。没有公开永久 OSS 链接。浏览器下载已在隔离 API 测试验证，Codex 将文件保存到本机仍待真实客户端验证。
- 上传来源须通过 `ORDER_TRACKING_MCP_FILE_HOSTS` 配置精确 HTTPS 主机名。未配置时上传拒绝；待目标 Codex 真实附件暴露的主机核实后再填入环境配置，不能猜测 CDN 域名。服务端拒绝内部地址、非 443 端口、跨主机跳转及超限内容，DNS 解析后固定公网 IP 建连。

## 本地实现与验证

- 工具：返修周期列表/详情、质检上传预览、预览回读、逐份确认、整周期归档、原件下载。上传只创建预览；确认默认整批预检，有错误时不创建任务；`allow_partial=true` 才确认合格项。结果逐份给出状态和业务 ID，重试使用同一预览与原幂等键。
- 复用现有质检解析、工厂/SKU 匹配、私有文件存储、确认事务、周期汇总及通知 outbox。损坏或伪造 `.xlsx` 现在返回业务校验错误。独立 MySQL 测试库为 `order_tracking_issue155_test`，通过测试启动器自动迁移；测试不接触其他任务数据库。
- 自动化已验证服务端协议工具发现、拒绝内部文件来源、批量预检与部分执行、原幂等键重试、周期详情、带登录的原件下载及字节/哈希一致。真实 Codex 附件注入、HTTPS 代理后登录、Codex 本地接收、真实通知、PR/main CI 仍未验收。
- 隔离 MySQL 后端全量回归：490 passed、1 skipped（独立 OSS 测试桶未配置）。最新改动的文件/解析/MCP 定向测试：30 passed。Ruff、mypy、OpenAPI `--check`、Alembic `check` 与 `git diff --check` 通过；无数据库迁移。
- 一次定向测试命令遗漏 `ORDER_TRACKING_TEST_DATABASE_URL`，两项数据库 fixture 在启动时失败；显式指定本任务测试库后重跑通过，未触及业务断言。

## 联调门

在隔离 HTTPS 环境用目标 Codex 的本地引用和拖入附件各完成一次真实上传、预览、确认、下载，核对 20 MiB 与 20 份边界、源文件和返回文件的大小及 SHA-256。记录 Codex、Plugin、服务端版本及工具输入形状，不保存临时 URL、令牌或凭据。若客户端没有提供上述 `files` 形状，需要修订文件通路并重新验证，不能把浏览器上传或协议模拟当作完整验收。
