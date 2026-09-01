# Issue tracker：GitHub

本仓库新的缺陷、功能切片、Spec 和执行 Ticket 使用 GitHub Issues 跟踪，默认通过仓库内已认证的 `gh` CLI 读写。

## 与正式资料的关系

- `docs/requirements/`、已批准原型、技术设计、开发计划和 `docs/project/work-orders/` 继续承担正式范围与验收依据；Issue 不替代它们。
- 既有 S00–S12 工单保留原位，不批量迁移、不删除，也不在 GitHub 重复创建同内容 Issue。
- 只有尚未完成、需要独立实施或跟踪的具体缺陷和功能切片才创建 Issue。
- Issue 应链接对应正式工单或需求，并只记录本次问题、证据、范围、依赖、验收标准和明确排除项。
- Issue 与正式资料冲突时停止实施，先按 `AGENTS.md` 的资料层级修正正式资料或取得确认。

## Issue 最小完整度

Issue 可以比正式工单简短，但必须让新的执行者无需依赖聊天记录即可回答：

1. 当前有什么问题或要实现什么；
2. 已有何种可复现证据或业务依据；
3. 本次修改包含和不包含什么；
4. 依赖哪些正式资料、前置任务或确认门；
5. 通过哪些可验证结果才算完成。

## 操作约定

- 创建：`gh issue create`，优先使用仓库的 Bug 或 Feature 模板。
- 读取：`gh issue view <number> --comments`。
- 列表：`gh issue list --state open`，按需要增加标签或状态条件。
- 评论、关闭或修改标签属于 GitHub 外部写操作，执行前遵守当前任务授权范围。
- Pull Request 不是需求入口；PR 必须关联 Issue，并使用仓库 PR 模板记录验证、风险和发布边界。

## 当 Skill 要求发布或读取 Ticket

- “发布到 issue tracker”表示创建 GitHub Issue。
- “读取 Ticket”表示读取对应 GitHub Issue 正文、评论和标签。
- `to-spec` 只用于需要跨多个任务或上下文的变更；单一小缺陷可直接创建一个 Bug Issue。
- `to-tickets` 只把已确认 Spec 拆成纵向、可独立验收的 Issue，不把技术层横向拆成互相无法交付的票据。
