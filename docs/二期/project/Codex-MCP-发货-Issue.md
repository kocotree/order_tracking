# 二期：MCP 发货、收货与退回

对应 [#154](https://github.com/kocotree/order_tracking/issues/154)；文件依赖 [#155](https://github.com/kocotree/order_tracking/issues/155)。

依赖 [基础接入 #151](https://github.com/kocotree/order_tracking/issues/151)；Excel 下载复用文件工单通路，对话验收配合 [Plugin #152](https://github.com/kocotree/order_tracking/issues/152)。本轮仅建票。

## 范围

- [ ] 发货列表筛选/排序/分页、详情、关联订单、箱内项、凭证及操作记录。
- [ ] 各厂日汇总、单张及同厂同日清单下载，复用日汇总导出查询；标明原报数量、上海业务日期，收货确认量单独标识。
- [ ] 收货草稿读取、逐箱保存、整单确认、按发货单规格退回，沿用原因及数量约束。
- [ ] 稳定单据/箱内项 ID、版本、事务和幂等保护；额外修改展示差异确认。批量先整批预检，部分执行须明确授权，中断如实报告。

## 验收

- [ ] 同厂多单、跨厂、撤回/作废、重提跨日、跨日收货、历史初始量和退回与 Web/Excel 对应口径一致。
- [ ] 同 SKU 不同箱不会误改，保存未确认不改变正式数量；确认后单据和订单数量回读正确。
- [ ] 并发无覆盖、重试无重复确认/退回；越权、凭证及导出访问受控。
- [ ] 隔离数据完成汇总→修改→保存→确认→回读；逐 Web 动作有映射，核心事务/数量 TDD、回归、静态检查及 PR/main CI 通过。

## 依据与边界

遵守 [AGENTS.md](https://github.com/kocotree/order_tracking/blob/main/AGENTS.md)；本地 `docs/二期/project/` 下 Codex 能力对照、技术设计和开发计划尚未提交推送，实施前验收并固化正式需求。不从聚水潭历史入库推断系统当日发货，不改数量口径。已进入 Web 的相关二期动作同步覆盖。部署、真实通知和生产操作按现有确认门执行。
