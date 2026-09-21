# Issue #153 MCP 订单、派工与合同本地实施与验证

基线：`c791bed`（#151 授权基础）；分支：`codex/issue-153-mcp-orders-dispatch-contracts`。本记录只描述本 worktree 的本地结果。#157 仍需合并；本分支未推送、未建 PR、未合并或部署。

## 工具与 Web 动作对应

| Web 动作 | MCP 工具 | 现有服务与验证 |
|---|---|---|
| 手动获取飞书订单 | `start_import_run` | `OrderImportService.create_or_reuse_run`；`test_order_import.py` |
| 最新/指定任务状态 | `get_import_run` | `latest_run`、`get_run`；`test_order_import.py` |
| 候选列表、详情、审计 | `list_import_candidates`、`get_import_candidate`、`get_candidate_audit` | 候选服务与审计；`test_order_import.py`、`test_agent_order_tools.py` |
| 候选明细字段保存 | `update_candidate_lines` | `save_candidate_lines`；`test_issue_102_order_maintenance.py` |
| 单/批量导入 | `import_candidates` | 先按 ID、版本与 READY 状态全量预检，再逐项调用 `confirm_candidate`；`test_mcp_import_batch.py`、`test_order_import.py` |
| 排除候选 | `exclude_candidate` | `exclude_candidate`；`test_order_import.py` |
| 手工草稿创建、编辑、发布、删除 | `create_order_draft`、`update_order_draft`、`publish_order_draft`、`delete_order` | `OrderService` 原事务；`test_agent_order_tools.py`、`test_order_api.py` |
| 未派工明细维护 | `update_order_details` | `save_fields_batch`；`test_agent_order_tools.py`、`test_issue_102_order_maintenance.py` |
| 来源变化预览、确认 | `preview_source_refresh`、`confirm_source_refresh` | 原来源快照与确认事务；`test_agent_order_tools.py`、`test_order_dispatch.py` |
| 选中明细派工预览、确认 | `preview_dispatch`、`confirm_dispatch` | 原派工快照与确认事务；`test_agent_order_tools.py`、`test_order_dispatch.py` |
| 可撤回工厂、按厂撤回 | `list_withdrawable_factories`、`withdraw_factory_dispatch` | `OrderService`；`test_order_dispatch_rules.py` |
| 完成、带原因重开 | `complete_order`、`reopen_order` | `OrderService`；`test_agent_order_tools.py`、`test_order_dispatch_rules.py` |
| 合同资格、首次及重复导出 | `list_order_contracts`、`export_contract` | `ContractService` 稳定编号、模板和快照；`test_agent_order_tools.py`、`test_contracts.py` |

工具经 #151 的 MCP 令牌校验取得本人管理员 ID，写入继续走服务层权限、版本、状态、事务、幂等和通知逻辑。批量候选默认有任一预检失败即不提交；明确 `allow_partial` 时只执行合格项。执行中出现版本冲突会报告已成功、失败、未执行项。已导入候选重试回读原订单 ID。

## 验证

- 显式隔离库：`order_tracking_mcp153_test`，本地 MySQL 8，`ORDER_TRACKING_DATABASE_URL` 与 `ORDER_TRACKING_TEST_DATABASE_URL` 均显式指向此库。
- MCP 实际协议调用：手工草稿、发布幂等、合同资格及首次/重复导出；456# 来源变化预览/确认、补日期、派工预览/确认与回读；候选审计读取。相关测试见 `server/tests/api/test_agent_order_tools.py`。
- 批量候选全部预检、允许部分执行和中途冲突结果见 `server/tests/unit/test_mcp_import_batch.py`。
- Ruff、mypy、OpenAPI 快照检查、`alembic check` 均通过。隔离 MySQL 全量后端：481 passed、1 skipped（隔离 OSS 测试桶未配置）；新增工具定向复跑 3 passed。没有运行真实飞书、真实通知、HTTPS 代理或 Codex 对话工具调用。

## 跨工单接线

- #155 已确定 `app.mcp.files.download_descriptor(origin, path, filename, size_bytes, sha256)` 契约。待其提交进入本分支后，合同侧用 `ContractExport.stored_file_id` 关联的 `StoredFile` 元数据生成描述，下载路径为现有本人 Web 授权的 `/api/v1/admin/contract-exports/{exportId}/download`。当前只生成合同并返回导出标识、文件名和状态；该路径仍需本人 Web 登录，Codex 本地接收尚未验收。
- #152 承载对话授权引导和完整 Codex 对话验收；模型传入的确认参数不作为后端授权证据。
- 与 #154、#155、#156 合并前核对 `server/app/mcp/server.py` 的中央注册接线及工具名；本工单未新增迁移号。
