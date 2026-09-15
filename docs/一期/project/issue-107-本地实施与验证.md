# Issue #107 本地实施与验证

## 已实施

- “更新未派工明细”仅在预览时读取一次飞书／聚水潭；确认时直接应用 MySQL 中的服务器预览快照。
- 派工预览和派工确认不读飞书／聚水潭，使用系统当前已保存的明细值。
- 保留订单与明细版本校验、预览过期、幂等、数据库行锁、最终产品／工厂／启用账号校验及单事务全成全败。
- 未修改前端、API 结构、数据库结构或依赖。

## TDD 与回归证据

- 先新增失败用例：来源预览后外部服务不可用时，确认仍写入已保存快照；实施前失败于二次来源读取，实施后通过。
- 先新增失败用例：外部服务不可用时，派工预览与确认仍使用已保存明细完成；实施前失败于派工预览的来源读取，实施后通过。
- `pytest tests/integration/test_order_source_update.py tests/integration/test_order_dispatch.py -q`：34 通过。
- `pytest tests/integration/test_order_dispatch_rules.py -q`：11 通过。
- `ruff check ...`：通过。
- `mypy app`：通过。
- `pytest -q`：453 通过，1 条既有 OSS 隔离测试因未配置测试桶跳过。
- `python -m scripts.export_openapi --check`：通过。

## 边界

- 本记录只证明本地分支实现与测试结果，不证明共享测试或生产已更新。
- 未进行真实飞书／聚水潭调用次数验收或真实账号业务验收。
- 未推送分支、创建 PR、合并、打标签或部署。
