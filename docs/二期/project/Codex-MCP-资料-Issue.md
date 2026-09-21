# 二期：MCP 工厂、产品、人员与通知

对应 [#156](https://github.com/kocotree/order_tracking/issues/156)；覆盖核查关联 [#153](https://github.com/kocotree/order_tracking/issues/153)、[#154](https://github.com/kocotree/order_tracking/issues/154)、[#155](https://github.com/kocotree/order_tracking/issues/155)。

依赖 [基础接入 #151](https://github.com/kocotree/order_tracking/issues/151)，最终覆盖核查依赖其余四项 MCP 交付；完整对话由 [Plugin #152](https://github.com/kocotree/order_tracking/issues/152) 验收。本轮仅建票。

## 范围

- [ ] 工厂列表筛选/排序/分页、详情、新增/编辑、联系人、合同资料及关联人员；稳定 ID 和正式关联匹配。
- [ ] 产品列表、规格及受权图片查看，沿用 Web 只读能力。
- [ ] 工厂申请列表/详情、选择工厂通过、带原因拒绝；工厂用户启停、最高管理员专属的管理员启停。
- [ ] 本人通知列表、未读数、已读及目标对象定位。
- [ ] 每个工具强制角色、对象权限和版本约束；审核/停用等须明确授权，不能由“修复派工问题”推导。
- [ ] 汇总五项 MCP 的 Web 动作—工具—测试映射，核查所有按钮、禁用条件、分页和数据权限；新增 Web 能力归入相应工单补齐。

## 验收

- [ ] 工厂名称/编号唯一、不可改字段及合同资料校验与 Web 一致；产品不增加写入口。
- [ ] 普通/最高管理员、工厂、停用账号权限组合覆盖；最高管理员不可被停用，审核并发正确，歧义不误操作。
- [ ] 已读仅影响本人，图片受权，分页不漏项。
- [ ] 完整清单无未处理缺项；权限核心 TDD、隔离回归、静态检查及 PR/main CI 通过，未验证的真实环境项目明确记录。

## 依据与边界

遵守 [AGENTS.md](https://github.com/kocotree/order_tracking/blob/main/AGENTS.md)；本地 `docs/二期/project/` 下 Codex 能力对照、技术设计和开发计划尚未提交推送，实施前验收并固化正式需求。不新增角色、管理范围或通知规则；权限在服务端强制执行。部署、真实消息和生产修改按现有确认门执行。
