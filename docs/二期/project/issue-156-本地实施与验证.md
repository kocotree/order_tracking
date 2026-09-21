# Issue #156 本地实施与验证

2026-09-21。独立分支 `codex/issue-156-mcp-factory-product-users-notifications` 从 #151 的 `c791bed` 建立。以下结果仅属于本 worktree；#157 仍需合并与远程 CI 核验。

## Web 动作—MCP 工具—测试映射

依据 `admin-web/src/router/index.ts`、`admin-web/src/api/client.ts`、对应页面与 `server/app/api/` 核对。表中“待集成”指其他独立 Issue 尚未汇入本分支；其工具名来自开发计划，不能作为已实现能力。

| Web 动作 | MCP 工具 | 本分支证据与状态 |
| --- | --- | --- |
| 飞书登录衔接、我的身份、统一退出 | OAuth、`get_me`、`logout_shared_session` | #151 已接入；`test_agent_oauth.py`、`test_agent_shared_auth.py` |
| 看板统计、最近订单、订单列表筛选排序分页、订单详情及审计 | `get_dashboard`、`list_orders`、`get_order`、`get_order_audit` | #151 已接入；`test_agent_oauth.py`；真实 Codex 对话查询待验收 |
| 获取飞书候选、运行状态、候选列表详情、字段维护、导入与排除 | `start_import_run`、`get_import_run`、`list_import_candidates`、`get_import_candidate`、`get_candidate_audit`、`update_candidate_lines`、`import_candidates`、`exclude_candidate` | 待 #153 集成与测试 |
| 手工草稿建改删、旧草稿发布、未派工字段与日期维护 | `create_order_draft`、`update_order_draft`、`delete_order`、`publish_order_draft`、`update_order_details` | 待 #153 集成与测试 |
| 来源更新预览确认、派工预览确认、按厂撤回、完成与撤销完成 | `preview_source_refresh`、`confirm_source_refresh`、`preview_dispatch`、`confirm_dispatch`、`list_withdrawable_factories`、`withdraw_factory_dispatch`、`complete_order`、`reopen_order` | 待 #153 集成与测试 |
| 合同资格、生成、重复下载 | `list_order_contracts`、`export_contract` 与文件交付 | 待 #153、#155 集成与测试 |
| 发货单列表详情、操作记录、单张及同厂同日清单 | `list_shipments`、`get_shipment`、`get_daily_shipment_summary`、`export_shipment`、`export_daily_shipments` | 待 #154、#155 集成与测试 |
| 收货草稿读写确认、按单退回 | `get_receipt`、`save_receipt`、`confirm_receipt`、`return_shipment` | 待 #154 集成与测试 |
| 返修周期详情、质检 Excel 上传预览确认、原件下载、归档 | `list_repair_periods`、`get_repair`、`upload_repair_workbook`、`get_repair_preview`、`confirm_repair_previews`、`archive_repair_period` 与文件交付 | 待 #155 集成与测试 |
| 工厂关键词、合同完整性、接入状态筛选，排序分页；详情、新增、编辑、关联人员 | `list_factories`、`get_factory`、`create_factory`、`update_factory`、`list_users(role="factory", factory_id=...)` | #156 已接入；`test_agent_directory.py`；复用工厂 service 的唯一性、联系人、不可改供应商编号及版本校验 |
| 产品关键词、规格排序分页、图片查看 | `list_products`、`get_product_image` | #156 已接入；`test_agent_directory.py`；图片以 MCP image 内容返回，按当前版本校验私有对象；产品无写工具 |
| 工厂申请状态筛选排序分页、详情、选厂通过、带原因拒绝 | `list_factory_applications`、`get_factory_application`、`approve_factory_application`、`reject_factory_application` | #156 已接入；`test_agent_directory.py`；非待审核、旧版本及空原因拒绝 |
| 工厂人员按厂筛选排序分页、启停；管理员人员排序分页、启停 | `list_users`、`set_user_enabled` | #156 已接入；`test_agent_directory.py`；普通管理员不能管理管理员，最高管理员不可停用 |
| 本人通知全部/未读、未读数、查看并标记已读、目标定位 | `list_notifications`、`get_unread_count`、`mark_notification_read` | #156 已接入；`test_agent_directory.py`；他人通知不可标记，返回 `targetType`、`targetId`、`targetPath` |

网页“搜索/重置”、切换排序、上一页/下一页、详情弹窗和取消按钮由工具参数或客户端交互表达。写入按钮只在对应状态下出现；后端继续在同一业务服务中复查申请状态、角色、对象及版本。对话中的明确授权仍须由 #152 Plugin Skill 与真实 Codex 流程验收，服务器不能从工具参数证明用户已授权。

## 验证

- 独立 MySQL 8 数据库：`order_tracking_issue156_test`，显式设置 `ORDER_TRACKING_DATABASE_URL` 与 `ORDER_TRACKING_TEST_DATABASE_URL`。该库只供本 worktree 使用。
- `uv run pytest -q --tb=line`：479 passed，1 skipped（未配置隔离 OSS 测试桶）；完整回归运行于图片 MCP 内容调整之前，调整后 `test_agent_directory.py` 定向复验通过。
- `uv run ruff check .`、`uv run mypy app`、`uv run python -m scripts.export_openapi --check`、`git diff --check` 通过。无新增迁移。
- 测试涵盖 MCP 工具发现、OAuth 本人调用、工厂分页与旧版本、审核重复提交与拒绝原因、工厂用户停用、普通/最高管理员边界、本人通知隔离、产品只读图片。现有 Web API 和领域服务测试在完整回归中继续通过。

## 尚需集成与验收

- #153、#154、#155 合入后逐动作回填实际工具与测试名称，复核全部 Web 页面、按钮、禁用条件、分页和数据权限；当前表不能视为五项完整覆盖验收。
- #157 的 PR/main CI、真实飞书、HTTPS 代理、Codex 对话内查询、Plugin 安装及真实通知仍未在本任务验收。
- 本任务未推送、建 PR、合并、创建标签、部署、操作生产或发送真实通知。
