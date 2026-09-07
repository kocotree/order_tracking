# Issue #44 规则确认与资料交接

日期：2026-09-07。当前阶段为S12集成验收期间的反馈迭代；用户随后授权修改代码并运行功能测试，Playwright 指定 Edge；本次交付范围为本地实现与验证。

## 工作区

- 从干净的detached HEAD `c5aaad9`建立`codex/issue-44-receipt-spec`；沿用当前独立Worktree，未修改其他工作区。
- 2026-09-07 开工复核：HEAD 与最新 origin/main 均为 `c5aaad971e0038e0c7262b1fb84a45b6e76b8d12`，基线 CI `34010875737` 成功。沿用当前分支并保留上一轮文档修改；本轮未提交/推送。

## 上一轮保留的文档修改

- `AGENTS.md`：仅将正式需求引用更新至V1.59。
- `CONTEXT.md`：收货核对、原报/确认数量、差额及有效数量术语。
- `docs/requirements/一期需求文档.md`：V1.59，正文第4.3节、状态/数量/权限/通知及验收更新。
- `docs/project/一期技术设计方案.md`：核对独立存储、版本、事务、投影及逆向数量设计。
- `docs/project/一期开发计划.md`：#44增量范围、顺序与并行边界。
- `docs/project/work-orders/S07-正常装箱发货闭环.md`：页面方案、文件及核心测试范围。
- `docs/project/work-orders/S08-发货清单作废退回与补发.md`：收货后退回/作废和原报导出边界。
- `docs/project/work-orders/S11-通知提醒与审计收口.md`：工厂确认结果事件和现有微信模板映射。
- `docs/project/一期里程碑与决策记录.md`：本轮规则、授权与证据边界。
- 本交接文件。

## 规则与验收依据

以需求第4.3节为业务正文，技术设计及工单各承担本身职责。用户已确认其余建议，包括下载清单保留原报、确认后锁定及收货结果通知。没有旧正式发货单兼容需求，不清理测试数据。

用户明确不读取/修改/对照旧原型，不另做Browser手动操作；网页使用Playwright，小程序编译、真机和真实通知送达由用户验收。这是#44当前任务的明确例外，不能扩展为其他Issue的规则。

## 资料同步阶段的验证与下一步

本轮检查文档差异、需求版本、链接目标、关键口径和空白，并回读GitHub #44标题与正文确认同步。未运行功能测试、Playwright、远程CI、微信开发者工具或真机，不表示实现/业务验收通过。

下一步为依据同步后的技术方案实施并验证；保存/确认需处理真实MySQL事务、版本和权限，逆向数量使用确认基数；完整文件范围见S07补充节。提交、PR、部署、服务器迁移、小程序发布和真实发送按各自授权推进；本轮没有操作服务器、Base或真实业务数据。


## 本地实现（2026-09-07）

- 新增 `shipment_receipts` 和 `shipment_receipt_items`，迁移 `20260907_0029`；原报行、原报箱明细与原正向数量记录不改。
- 网页专用 `GET/PUT /api/v1/admin/shipments/{id}/receipt` 读取和保存完整核对草稿；版本从 0 开始，保存递增。`POST .../receipt/confirm` 使用已保存版本，要求网页管理员会话、CSRF 和幂等头；首次无差异可直接确认版本 0。
- 保存、确认和逆向流程先锁同一发货单，再读取当前状态。确认追加派工差额并记录审计/通知事件；重复确认不重复计数。已完成订单按订单净差额决定是否恢复。
- 三端正常详情与列表统一读取确认结果，未确认草稿仅网页专用接口可读。退回按确认基数校验，作废按确认基数冲销；确认全为 0 时仍可合法作废。
- 网页新增核对数量、保存、确认、错误反馈及重读；工厂新增按订单/SKU差异块，两类小程序显示确认人/时间，沿用现有折叠、凭证和返回。
- 确认结果使用 `factory_status` 模板与 `BUSINESS_RESULT` 类别，无差异也通知；发送前重新检查账号启用和同厂归属。所有外发测试使用假适配器。

### 代码与测试文件

- `server/app/db/models.py`、`server/migrations/versions/20260907_0029_shipment_receipts.py`
- `server/app/modules/shipments/service.py`、`server/app/api/shipments.py`
- `server/app/modules/notifications_audit/service.py`
- `server/tests/api/test_shipment_receipt_api.py`
- `server/openapi/openapi.json`、两端 `generated.ts`
- `admin-web/src/api/client.ts`、`admin-web/src/pages/ShipmentDetailPage.vue`、对应单元测试
- `admin-web/scripts/verify-shipment-receipt-edge.mjs`、`shipment-receipt-fixture.mjs`
- `miniprogram/api/shipments.ts`、两类发货详情的 TS/WXML、`miniprogram/tests/shipment-receipt.spec.ts`

### Edge 重跑

使用项目要求的 Node.js 24、本机已安装的 `playwright-cli` 和 Microsoft Edge：

```sh
pnpm --dir admin-web dev --port 5184
# 在另一个终端执行
node admin-web/scripts/verify-shipment-receipt-edge.mjs
```

脚本只接受本地地址，使用独立 Edge 会话和受控 API 响应；验证保存冲突、输入保留、保存恢复、确认锁定、数量汇总及 1440/1280 两个宽度下序号列 52px/8px。截图与结果写入被 Git 忽略的 `output/playwright/`。它证明网页交互，真实事务由独立 MySQL 8 API 测试验证；不等于共享测试环境端到端验收。

### 数据库与后续边界

本地测试使用本次新建的独立临时 MySQL 8 容器，未连接既有开发库或共享测试/生产数据库。新迁移不自动确认现有记录，也不清理用户数据。有核对记录时迁移降级会拒绝删除表，不能通过删除原报或台账回滚业务结果。

小程序开发者工具编译、iOS/Android 真机、订阅授权和真实送达由用户验收。没有修改或对照旧原型，没有 Browser 手动验收；没有提交、推送、PR、部署、服务器迁移、小程序发布或真实发送。后续按用户指令推进。


### 已完成的客户端与静态验证

- Node.js 24.20.0：网页 61 项单元测试、ESLint、类型检查、生产构建通过；小程序 58 项测试、ESLint、类型和项目结构构建通过。项目结构构建不等于微信开发者工具编译。
- Edge 自动化脚本通过；浏览器 User-Agent 确认 `Edg/152`，使用独立自动化会话，不复用日常登录状态。`output/playwright/receipt-edge-result.txt` 和 `receipt-edge-verified.png` 是本地忽略文件。
- 后端 Ruff 与 CI 要求的 `mypy app` 通过；OpenAPI 漂移检查和两端生成类型同步完成。
- 额外扩大到 `mypy app scripts` 时，既有 `scripts/prepare_contract_template.py` 有 4 项类型错误，涉及合并单元格索引类型及工作表私有属性；不属于本次改动，也不在 CI 的 `mypy app` 范围，未修改该脚本。
- 首轮未按 CI 环境变量执行的回归及曾发生测试进程重叠的输出不作为验收证据；后端正式结果以之后的隔离库、单进程回归记录为准。


### 后端全量结果

按 CI 环境变量在独立 MySQL 8 测试库运行 `uv run pytest -xq --tb=short`：**265 passed, 1 skipped**（524.35 秒）。唯一跳过项是未配置隔离 S12 OSS 测试桶，未把该项描述为真实 OSS 验证通过。

收货专项覆盖：草稿隔离和重入、严格整数及完整明细集合、版本冲突、正负零数量、原报导出、整单幂等、并发确认/保存/退回互斥、事务失败回滚、已完成订单恢复、初始基线、混装同 SKU 跨订单、确认后退回/作废、通知去重和换厂后的外发资格。新增订单审计使用可读中文说明确认差额。


### 最终复验与停止点

- 最后收货专项复验 **26 passed**（70.31 秒），包含最终中文审计内容。
- `alembic check` 无差异；在已清空的本次独立测试库执行 `0029 → 0028 → head` 成功，再次检查无模型漂移。Ruff、`mypy app` 和 OpenAPI 检查均通过。
- 原发货清单模板、三端锁文件没有修改。网页、小程序和最终迁移检查均未降低断言或删除失败测试。
- 本次启动的 Vite、独立 Edge 测试会话已关闭，临时 MySQL 测试容器已移除；既有本地数据库与用户测试数据未操作。未运行本分支远程 CI。
- 代码与文档保留在当前 Worktree，未提交。下一步由用户进行小程序设备与业务验收，再决定提交/PR及部署；本地测试通过不等于业务上线完成。
