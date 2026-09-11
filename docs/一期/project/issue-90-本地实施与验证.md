# Issue #90 本地实施与验证

日期：2026-09-11。关联 [执行 Issue #90](https://github.com/kocotree/order_tracking/issues/90)。

## 授权与基线

用户授权按 #90 明细分批派工与工厂发货闭环本地实施，独立 worktree `/Users/wxl/Desktop/kk/order_tracking-issue-90`，分支 `codex/issue-90-detail-dispatch`，前置提交 f10a203（#89）。未使用 Playwright，未修改主工作区、#87/#88/#89 工作区。

未推送、未创建 PR、未合并、未部署、未上传小程序、未发送真实通知或修改飞书业务数据。

## 实现内容

### 数据库迁移（20260911_0036）

- 移除 `ck_order_assignments_quantity_covers_initial_shipped` 约束（允许超发派工）
- 将 `uq_order_assignments_line_factory` 从唯一约束改为普通索引（允许同SKU/工厂不同来源明细独立派工）
- `order_assignments` 新增 `detail_id` FK（unique, nullable）、`is_active` boolean（default true）
- `order_details` 新增 `dispatch_batch_id`（用于通知批次分组）
- 有损回滚防护：存在新派工数据时拒绝回退

### 后端 - 派工服务（`server/app/modules/orders/dispatch.py`）

`OrderDispatchService` 继承 `OrderService`：

- `preview()`：选择未派工明细 → 读取最新来源 → 来源差异检测 → 逐行校验（产品匹配、工厂/账号启用、日期必填、数量有效、跟单一致性）→ 生成五分钟有效预览
- `confirm()`：重新读取来源 → 串行锁订单+明细 → 逐行校验 → 创建/更新 OrderLine → 创建 OrderAssignment（含 detail_id、is_active、initial_shipped） → 关联 detail → 首派 DRAFT→PUBLISHED → 锁定订单跟单人 → 写入 outbox → 幂等
- 复用 `source_update._read()` 的来源读取能力（通过独立 `OrderDispatchSourceRead` 类桥接，避免多重继承）
- `_dispatch_snapshot()`：混合已派工（执行数量）和未派工（来源数量）明细的完整快照

### API 端点（`server/app/api/orders.py`）

| 路径 | 行为 |
|---|---|
| `POST /admin/orders/{id}/dispatch/preview` | 派工前来源检查与校验预览 |
| `POST /admin/orders/{id}/dispatch/confirm` | 整批确认派工，要求 Idempotency-Key |

### 工厂侧查询更新

- `shipments/service.py`：发货选单、订单可见性查询添加 `is_active.is_(True)` 过滤
- `orders/service.py`：`_page_snapshot_data` 三处查询、`_factory_ids` 添加 `is_active.is_(True)` 过滤
- 确保工厂只能获取本厂有效派工；未派工行/跨厂ID/失效ID不可越权

### 管理员网页（`admin-web/src/pages/OrderDetailPage.vue`）

- 明细表新增复选框列（仅未派工行、全选控制）
- 新增"派工状态"列（已派工/未派工标签）
- 标题行新增派工进度展示（已派工 X/Y 条 · 未派工/部分派工/全部派工）
- 右侧新增"更新未派工明细""派工（已选 N 条）"按钮
- 全部派工后隐藏选择列和两按钮
- 派工流程：先展示来源变化确认弹窗 → 再展示逐行校验结果弹窗
- 列宽按批准原型：序号52px（左右8px）、选择40px、表头800/内容700
- 合同导出按 #87 规则：有工厂已派工即可导出，不再要求 shippedQuantity===0
- API 客户端新增 dispatch、SourceDifference、DispatchValidationItem 类型

### 通知 outbox

- 派工确认时按 factory 写入 `OutboxMessage`（event_type: `order_detail_dispatched`）
- 使用模拟适配器验证；不发送真实通知

## 文件清单

| 文件 | 变更 |
|---|---|
| `server/migrations/versions/20260911_0036_dispatch_support.py` | 新增迁移 |
| `server/app/db/models.py` | OrderAssignment 加 detail_id/is_active，OrderDetail 加 dispatch_batch_id |
| `server/app/modules/orders/dispatch.py` | 新增派工服务（~870行） |
| `server/app/api/orders.py` | 新增 dispatch 端点及请求/响应模型 |
| `server/app/main.py` | 初始化 DispatchService 并传入路由 |
| `server/app/modules/orders/service.py` | 工厂侧查询加 is_active 过滤 |
| `server/app/modules/shipments/service.py` | 发货选单查询加 is_active 过滤 |
| `admin-web/src/api/client.ts` | 新增 dispatch API 方法及类型 |
| `admin-web/src/pages/OrderDetailPage.vue` | 重写明细表及派工交互 |

## 验证

- ✅ 后端模块导入通过（dispatch.py, orders API）
- ✅ admin-web TypeScript 类型检查通过
- ✅ admin-web production 构建通过（vite build）
- ⚠️ 后端测试因未配置 `ORDER_TRACKING_TEST_DATABASE_URL` 无法运行
- ⚠️ 小程序类型检查因未安装 TypeScript 无法运行（预存问题）
- ⚠️ 迁移未在真实 MySQL 上运行验证

## 留给 #91 的边界

#91 负责：
- 管理员订单列表/首页/日期筛选的混合口径（来源+执行）
- 整单撤回（设置 is_active=false、回退 detail dispatch_state）
- 确认订单完成（全部已派且逐条交足的条件）
- 合同导出资格更新
- 到期提醒仅有效已派且欠量行
- 完整迁移核对与回归
- 小程序端的 dispatch_state 字段消费更新

#90 不包含以上内容。#91 实施前不应开放本分支的部分派工写入路径。

## 未验证项目

- 远程 CI（GitHub Actions）
- 测试部署/共享测试环境
- MySQL 8 迁移执行
- 真实浏览器视觉对照
- 微信开发者工具/真机
- 真实飞书来源读取
- 真实通知外发

本地测试及构建通过不代表上线或业务验收。