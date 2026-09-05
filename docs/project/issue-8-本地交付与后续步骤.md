# Issue #8 本地交付与后续步骤

## 范围与停止点

用户已确认开始代码实施；完成本地代码与必要测试即停止。分支为 `codex/issue-8-admin-feishu-notifications`，基于 `bb3e13fc19975602c66923da899345f93a74c7cc`（main CI 33940831938 五项成功）。当前修改未提交、未推送，不创建 PR、不合并、不部署、不上传小程序、不发送真实消息。

- 只改管理员新生成的正常发货、返修发回、撤回申请的外部通知；合同提醒、工厂行为、管理员微信授权入口及历史投递保持现状。
- 站内通知仍面向原有管理员集合，三类飞书提醒只面向四位指定管理员。
- 发货卡片取发货单固化明细，按订单和 SKU 汇总跨箱数量；返修取本次批次的修好与报废数量，显示“本次发回”；撤回申请使用申请记录中的人、时间和原因。
- 复用飞书应用、业务发件箱、失败重试及诊断机制，没有数据库迁移、API 或客户端改动。

## 接收人核验

2026-09-05 使用用户授权的飞书 CLI，以王心玲&煎饼用户身份查询四人，均唯一、已激活、同租户，查询无剩余分页。

| 花名 | 通讯录完整名称 |
| --- | --- |
| 煎饼 | 王心玲&煎饼 |
| 花卷 | 张小薇&花卷 |
| 怡宝 | 陆小易&怡宝 |
| 蜜桔 | 程月红&蜜桔 |

代码按上述完整飞书显示名称精确匹配系统管理员，重名或不存在记录诊断并跳过，停用不外发；发送器仍解析业务应用作用域的现有 ExternalIdentity。CLI open_id 不写入业务代码或配置。通讯录核验不等于实际业务应用绑定或送达核验；姓名改动后需重新核实名单。真实环境未查询或修改。

## 本地验证

- MySQL 8 完整后端测试：212 passed，1 skipped；跳过项为未配置隔离 OSS 测试桶。
- 通知最终版本专项回归：23 passed（32.04 秒）。
- Ruff、mypy（67 个源文件）、Alembic 模型漂移、OpenAPI 导出一致性及 git diff --check 通过。
- 小程序 Node.js 24：29 项测试、lint、类型检查与结构构建通过；小程序源代码未变更。
- 用例覆盖真实业务服务的跨箱提交与撤回申请、指定四人外发、其他管理员站内保留、重名/停用排除、本批返修数量、历史微信任务原样发送、业务应用身份缺失及 HTTP 卡片结构。
- 完整测试后的最后修改仅为通知名单缺失诊断和相关局部整理，另跑最终通知专项回归覆盖。未运行新的远程 CI、Docker 构建、浏览器/真机或真实发送；未修改网页和小程序界面。

## 后续执行命令（本轮不执行）

在项目根目录执行。先核对当前分支及差异；若出现其他任务改动，先分离再暂存。

```sh
git branch --show-current
git status --short
git diff --check
git diff -- server/app/adapters/notifications.py server/app/modules/notifications_audit/service.py

git add server/app/adapters/notifications.py \
  server/app/modules/notifications_audit/service.py \
  server/tests/integration/test_feishu_notifications.py \
  server/tests/integration/test_notifications_audit.py \
  docs/requirements/一期需求文档.md \
  docs/project/一期技术设计方案.md \
  docs/project/一期里程碑与决策记录.md \
  docs/project/work-orders/S11-通知提醒与审计收口.md \
  docs/project/issue-8-本地交付与后续步骤.md
git diff --cached --check
git diff --cached --stat
git commit -m "feat(notifications): route admin business reminders to Feishu"
git push -u origin codex/issue-8-admin-feishu-notifications
```

以下 PR 正文沿用仓库模板。使用 `Refs #8`，不因本地通过提前关闭需真实验收的 Issue。执行前复核差异仍与本记录一致。

```sh
pr_body_file=$(mktemp)
cat > "$pr_body_file" <<'EOF'
## 关联

- Issue：Refs #8
- 正式工单或需求：一期需求、技术设计和 S11 的 Issue #8 修订节。

## 修改内容

管理员新生成的发货、返修发回和撤回申请提醒改为飞书卡片，仅发送给四位指定管理员，站内通知接收范围不变。保留合同提醒、工厂通知、管理员微信授权交互及历史投递。发货按单汇总跨箱数量；返修展示本次批次数据。

## 验证

- [x] 单元或集成测试：后端 MySQL 8 完整测试 212 通过、1 项 OSS 因未配置隔离测试桶跳过；小程序 29 通过。最终通知专项结果见本地交付文档。
- [x] 静态检查、构建或迁移检查：Ruff、mypy、Alembic/OpenAPI 漂移、小程序 lint/类型/结构构建及差异空白检查通过。
- [ ] 浏览器或开发者工具检查：无客户端界面改动；飞书卡片真实显示待联调。
- [ ] 真实外部或共享测试验证：未运行。

未运行或失败的验证：隔离 OSS 桶未配置；本地未构建 Docker、未真实发送。HTTP 模拟校验不能替代飞书实际送达和显示验证。

## 风险与回滚

四人按已核实的完整飞书姓名唯一匹配系统管理员；改名、未注册或缺少业务应用身份时需重新核验，不能直接使用 CLI open_id。历史微信任务保持原状，仍可能发送。无数据库迁移；回退代码后原通知分发行为恢复，但已生成的投递任务不会自动改渠道，队列处理需另行确认。

## 发布边界

- [x] 本 PR 不代表已部署、已迁移、已发布小程序或已发送真实通知。
- [ ] 推送标签、部署、迁移和真实外发已另行获得授权：当前未授权。

EOF
# 确认本地差异与上述验证记录一致后执行。
gh pr create --repo kocotree/order_tracking --base main \
  --head codex/issue-8-admin-feishu-notifications \
  --title "管理员新业务提醒统一通过飞书发送" --body-file "$pr_body_file"
gh pr checks --repo kocotree/order_tracking codex/issue-8-admin-feishu-notifications --watch
gh run list --repo kocotree/order_tracking --branch codex/issue-8-admin-feishu-notifications --workflow ci.yml --limit 5
```

PR 全部 CI 成功并完成审查后，再取得合并指令。合并后检查 main 最终提交完整 CI。部署、版本标签与真实发送另行确认，不自动执行；本单未改小程序代码，不因本单自动上传小程序。

## 真实联调时核对

确认四人在业务应用的身份绑定和应用可见范围；按授权产生一条发货、一条含报废的返修发回及一条撤回申请，核对接收人、卡片、合计与按钮权限。检查合同/工厂回归。历史微信任务未清理，仍可能按原逻辑发送。当前测试使用 HTTP 假适配器，不证明飞书平台接受卡片或真机显示正常。
