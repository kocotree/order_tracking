# 二期：MCP 基础接入、共同授权与查询

对应 [#151](https://github.com/kocotree/order_tracking/issues/151)，配套 [Plugin #152](https://github.com/kocotree/order_tracking/issues/152)。本工单收窄为基础接入，订单、发货、文件返修、资料人员通知分别建票；共五项 MCP、一项 Plugin。本轮仅调整工单，未开始编码。

## 范围

- [ ] 在现有 FastAPI/server 内接入 Streamable HTTP、生命周期、HTTPS 代理、OAuth 元数据发现、工具契约、错误脱敏及审计身份；复用 MySQL 和业务服务。
- [ ] 公司明确登记的受信任 Codex 客户端复用浏览器有效网页登录，未登录走现有飞书登录后返回；无额外授权确认页或客户端管理页。
- [ ] 校验客户端、回调、授权事务、PKCE、resource/audience、账号及权限，保护登录衔接与 CSRF；公开 client ID 或模型 user_id 不能证明身份。签发 MCP 专用凭据，不传递 Web Cookie 或飞书令牌。
- [ ] Web/Plugin 同账号共享活动时间，连续 30 天无有效业务活动失效；独立短期凭据、自动刷新。刷新/轮询不保活；统一退出、停用或共同过期使两端失效，重新登录不复活旧 grant。
- [ ] 迁移仅关联有效会话，不重置闲置时间；覆盖 Cookie 保留、并发刷新/退出、多设备及凭据丢失，小程序现行会话规则不变。
- [ ] 本人身份、看板、订单列表/详情/审计及统一退出工具，保留 Web 筛选、排序、分页与角色限制。

## 验收

- [ ] 真正完成 Codex 已登录自动连接、未登录飞书认证、刷新和订单查询，记录客户端兼容证据。
- [ ] 查询与 Web 一致；工厂/停用账号、越权、错误回调/audience/PKCE、授权码及刷新重放均拒绝。
- [ ] 共同续期、30 天无活动失效、统一退出、多设备、并发与旧凭据不复活测试通过。
- [ ] 代理、重启、隔离 MySQL 迁移与原 Web/小程序登录回归通过；核心权限 TDD、静态检查及项目要求的 PR/main CI 通过。

## 依据与边界

遵守 [AGENTS.md](https://github.com/kocotree/order_tracking/blob/main/AGENTS.md)。本地 `docs/二期/project/` 下 Codex 能力对照、技术设计和开发计划尚未提交推送，实施前验收设计/工单并固化正式需求，现有退出文案按页面规则确认。后续业务工具使用本工单的身份及工具契约；真实 Codex 联调配合 Plugin。共享测试部署、真实通知、生产发布和数据写入继续按现有确认门执行。
