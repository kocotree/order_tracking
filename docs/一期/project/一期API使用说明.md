# 一期 API 使用说明

核对日期：2026-09-08；代码基线：本地 `3b2c90d`；业务基线：V1.60。本文解释调用方法，不另维护请求字段副本，不证明线上部署版本。

## Issue #88–#91 本地实现增量（2026-09-11）

来源明细订单导入只生成宽松草稿，不能走下文旧人工草稿的整单保存／发布接口。未派工日期使用 `PATCH /admin/orders/{order_id}/details/{detail_id}/contract-date`；更新先调用 `source-refresh/preview`，有差异独立确认 `source-refresh/confirm`，再使用 `dispatch/preview` 和 `dispatch/confirm` 派工（均为订单下的 POST，前缀 `/api/v1`）。取消派工不撤销已确认的来源更新。

旧 `POST /admin/orders/{order_id}/withdraw` 已移除。按工厂撤回先 GET `dispatch/factories` 获取当前派工及禁止原因标记，再 POST `dispatch/withdraw`，只带工厂和订单版本、CSRF、幂等键；无原因字段或二次确认。所选工厂有有效系统发货时返回冲突，其他工厂不受影响。接口具体字段以 OpenAPI 为准。

完成接口仍由管理员手动调用，全部明细有效派工且逐条交足才成功。合同允许部分派工及已有发货，首次仅包含所选厂有效派工，重复导出保留首次快照。管理员列表按完整来源与有效执行口径先筛选、排序、计数后分页；工厂接口只包含本厂有效派工。

首页 `GET /api/v1/admin/dashboard/orders` 包含草稿，支持 `keyword` 和与订单列表相同的 `sortBy`；在完整集合上查询后返回前十条 `recentOrders` 和匹配总数 `totalOrders`，统计卡片仍是全局口径。

本段覆盖下文旧流程中相冲突的范围，验证与未上线边界见 [#91 实施记录](issue-91-本地实施与验证.md)。

## Issue #65 本地实现增量（2026-09-09）

新增 `POST /api/v1/factory/shipments/{id}/withdraw`，必填原因、原单版本和幂等键；成功即撤回并冲销数量。通过 `GET /api/v1/factory/shipments/{id}/withdraw-draft` 恢复该单的共享编辑草稿，仅该轮提交人和撤回人可用。沿用草稿保存、附件和提交接口；撤回草稿的附件修改和重新提交也必须带版本。版本过期返回 409，客户端不得自动覆盖。

原撤回申请与管理员审核写接口已移除，历史记录保留。详情返回可编辑权限、草稿 ID 和操作记录；管理员核对旧页面遇到撤回返回 409。规则与页面见 [Issue #65 设计](issue-65-页面与技术设计.md)。本段反映本地代码，不代表部署完成。

## 契约与入口

- 完整路径、参数、请求体、响应结构见 [OpenAPI](../../../server/openapi/openapi.json)。
- 路由实现见 [API 目录](../../../server/app/api/)，异常映射见 [main.py](../../../server/app/main.py)。
- 业务接口前缀为 `/api/v1`；健康检查为 `/health/live`、`/health/ready`，不要添加 `/api` 前缀。
- 网页和小程序使用同一后端；不是每个 `/admin/` 接口都能由管理员小程序写入，权限须以会话终端和服务端检查为准。

## 登录、权限与请求保护

| 场景 | 处理方式 |
|---|---|
| 网页登录 | `/api/v1/auth/feishu/start` 发起 OAuth，callback 由服务端校验；浏览器保留 `ot_web_session` 等会话 Cookie |
| 网页写操作 | 按接口携带 Cookie 与 `X-CSRF-Token`，取值来自 `ot_csrf`；不在日志中输出 |
| 小程序登录 | `/api/v1/mini/auth/wechat`，需要绑定时调用 `/mini/auth/phone`；业务请求使用 `Authorization: Bearer …` |
| 会话续期 | 网页 `/auth/refresh`，小程序 `/mini/auth/refresh`；客户端合并并发续期，失效后回到登录流程 |
| 防重复提交 | 声明 `Idempotency-Key` 的接口为一次业务提交保留同一键；不因超时生成新键重复创建 |
| 并发编辑 | 携带接口定义的版本值；候选单条导入使用 `X-Candidate-Version`。冲突后重新读取，不盲目覆盖他人结果 |

部分幂等头在 OpenAPI 中可空，但运行时对提交动作仍要求提供；以路由中的校验和业务错误为准。不要自行把所有 GET 或 PUT 都加上相同幂等策略。

## 关键调用流程

以下路径均省略 `/api/v1`，请求字段按 OpenAPI 填写。

| 流程 | 顺序 | 成功判断 |
|---|---|---|
| 飞书导入 | `POST /admin/import-runs` → `GET /admin/import-runs/{run_id}` → `GET /admin/import-candidates` → 候选详情 → 日期 PATCH → `POST /admin/import-candidates/{candidate_id}/confirm` | 获取任务结束且候选校验通过；导入只生成草稿，不等于发布 |
| 草稿发布 | `POST /admin/orders` 或导入草稿 → `PUT /admin/orders/{order_id}` → `POST /admin/orders/{order_id}/publish` → `GET /orders/{order_id}` | 派工完整、日期齐备，相关工厂可见 |
| 工厂发货 | `GET /factory/shipment-catalog` → `POST /factory/shipments/drafts` → 草稿 PUT／附件上传 → `POST /factory/shipments/drafts/{shipment_id}/submit` | 正式单与有效数量形成；超时先查详情再决定是否重试 |
| 管理员核对 | `GET /admin/shipments/{shipment_id}/receipt` → 同路径 PUT → `POST /admin/shipments/{shipment_id}/receipt/confirm` | 保存不改进度，整单确认才固化数量；确认后回读订单及单据 |
| 退回补发 | `POST /admin/shipments/{shipment_id}/returns` → 回读订单 → 工厂普通发货流程 | 退回扣减原派工进度，不建立质检返修单 |
| 质检返修 | `POST /admin/repair-previews` → 预览 GET → 预览 confirm → 工厂任务 GET → return-draft GET/PUT → return-batches POST | 返修与报废合计计入返回数量，达标自动完成；不改普通订单进度 |

日期 PATCH 路径为 `/admin/import-candidates/{candidate_id}/lines/{candidate_line_id}/date`。收货、返修草稿具体版本字段不要相互套用。

## 查询与错误处理

列表筛选、排序和分页参数以对应接口为准，不假定所有列表相同。工厂可见范围由服务器确定，不能通过传其他工厂 ID 扩大权限。日期筛选命中任一可见明细；日期升序取最早、降序取最晚，空值最后。

| HTTP 状态 | 客户端处理 |
|---|---|
| 400 / 422 | 显示字段或业务校验原因；修正输入，不自动重复提交 |
| 401 | 尝试受控续期；无法恢复则重新登录 |
| 403 | 权限或请求保护失败；检查身份、终端、CSRF，不循环重试 |
| 404 | 资源不可用；刷新列表，不能猜测其他资源标识 |
| 409 | 版本或业务状态冲突；重新读取最新对象后重新确认 |
| 429 | 停止密集请求，稍后重试 |
| 500 / 503 | 保留脱敏的 `requestId` 和发生时间用于排查；先确认写入结果，避免重复业务动作 |

项目业务异常一般返回 `code`、`message`、`requestId`；框架参数校验响应也应按契约处理，不能假定所有错误完全同形。下载接口可返回文件流，不能统一按 JSON 解析。

## 更新与核验

后端路由改变后，在 `server/` 运行 `uv run python -m scripts.export_openapi`，在 `admin-web/` 和 `miniprogram/` 分别运行 `pnpm generate:api`，随后执行对应类型检查。检查导出一致性使用 `uv run python -m scripts.export_openapi --check`。不要直接编辑生成类型。

联调使用隔离开发／测试环境与演示身份。本文不包含凭据或可直接提交真实业务数据的请求示例。
