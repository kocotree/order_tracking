# Issue #28 通知详情返回补齐与本地交接

> **2026-09-08 状态核验：** 已合并 [PR #32](https://github.com/kocotree/order_tracking/pull/32)及 [PR #49](https://github.com/kocotree/order_tracking/pull/49)；Issue #28/#42/#43/#46 仍开放，后续验收按对应 Issue 跟进。
>
> 下文保留当时实施、授权停止点和验证证据，均属历史记录。提交、推送、建 PR 的旧待办已被上述合并结果替代；其余真实验收不得仅凭合并推定通过。

## 2026-09-07 范围与授权

用户补充管理员发货详情已可返回，其他通知入口仍不能返回，授权本地代码修复；微信开发者工具编译、上传及实际通知验证由用户执行。本次范围由两类发货详情扩展到现有通知允许进入的订单、任务和返修详情，只补页面栈返回适配，不修改页面字段、按钮、样式、业务状态、通知渠道或服务器。

工作区基线 c5aaad9，开工时干净且为分离 HEAD；已建立 codex/issue-28-notification-detail-back；本节记录初次修复时的状态，最终交付范围见文末。此文记录本轮对原 S11 Issue #28 范围的补充，避免与并行 #44 需求分析改动同一份正式文档。

## 原因与实现

两类发货详情原本均已调用 returnFromShipmentDetail，不能认定旧修复只覆盖管理员。管理员订单详情、工厂任务详情、管理员返修详情、工厂返修详情仍直接调用 wx.navigateBack，页面栈仅一页时无法返回；新增页面级测试复现 8 项失败（4 个单页入口、4 个返回 API 失败场景）。这证明代码遗漏，不代替用户实际微信版本和入口复现。

navigation.ts 将原逻辑扩展为 returnFromNotificationDetail，按业务类别及服务器返回的当前有效角色选择入口；两类发货详情继续使用原包装函数。四个遗漏页面接入共用方法：

| 类型 | 管理员入口 | 工厂入口 |
| --- | --- | --- |
| 订单/任务 | 订单 | 任务 |
| 发货 | 发货 | 发货记录 |
| 返修 | 发货 | 任务 |

有上一页仍返回原页面并保留筛选；没有上一页或返回失败则 reLaunch 到上述角色主入口。返修的单页兜底进入主入口默认页签，用户可切换现有返修页签；未新增列表查询参数或改动列表页。身份失效、停用或无角色仍进入既有登录入口。身份核验继续调用既有 /me 和会话续期接口，因此运行时需要服务器可用，但本次无服务器改动或部署需求。

## 修改文件

- miniprogram/modules/navigation.ts
- miniprogram/pages/admin-order-detail/admin-order-detail.ts
- miniprogram/pages/factory-task-detail/factory-task-detail.ts
- miniprogram/pages/admin-repair-detail/admin-repair-detail.ts
- miniprogram/pages/factory-repair-detail/factory-repair-detail.ts
- miniprogram/tests/shipment-detail-navigation.spec.ts
- 本交接文档

## 验证与停止点

Node.js 24 下，在 miniprogram 目录运行 pnpm test --run：15 个测试文件、68 项通过；pnpm lint、pnpm build（含 typecheck 和项目结构检查）通过，git diff --check 通过。原返回专项基线 12 项通过，新增 12 项覆盖四页面的单页入口、保留上一页及 navigateBack 失败。模拟微信页面栈及 HTTP，不等同于真实微信运行环境。

曾从仓库根目录用 pnpm --dir 运行时遇到 pnpm 版本选择不匹配，未修改依赖或全局配置；回到 miniprogram 目录按项目配置执行后检查通过。

已核对对应原型返回代码，未改原型与视觉文件。按用户要求未执行微信开发者工具编译、上传、真机或原型并排视觉验收；未运行远程 CI、部署、发送真实通知或修改 Base/GitHub 状态。

下一步由用户在当前工作区编译、上传，核对所测试小程序版本，从已有订单/任务、返修和发货通知分别冷/热启动进入后点击页面左上角返回，并回归正常列表及通知中心内进入、会话恢复。上传成功不等于通知入口真实验收完成。

## 同批交付补充（2026-09-07）

用户确认 #28 修复，并明确授权 #42、#43、#46 在同一分支共同提交；最新停止点为仅本地提交，推送和创建 PR 由用户执行。未包含并行分析的 #44。

本轮已确认的可见差异优先于这些 Issue 创建时的初始方案及原型旧布局：

- #42：订单卡片缩小内边距、区块间距；商品名称和订单编号均为 28rpx，数量为 30rpx。商品名称在前、订单编号紧随其后，保持同一行；长文本省略，保留字段、筛选和详情入口。
- #43：返修发回编辑及预览页面所有自绘文字为黑色粗体；页面标题栏通过默认关闭的 monochrome 属性局部适配。每个产品默认折叠，点击产品标题展开该产品全部 SKU，再点收起；折叠不清空选择和输入，不影响汇总及校验。顶部“返修单号”“返回进度”“待返回总数量”为 28rpx，明细“仓库退回”“已返回”“待返回”为 26rpx。删除“选择本次发回”，保留复选框。此确认明确替代原 Issue 中不折叠的初始描述，背景与业务数量规则沿用原实现。
- #46：通知卡片占满正常左右边距之间的可用宽度，覆盖原生按钮默认宽度约束；类型/时间同一行，标题一行省略，摘要最多两行；保留全部/未读、已读状态和跳转行为。

新增修改位于 admin-orders 的 WXML/WXSS、factory-repair-return 的 TS/WXML/WXSS、notifications 的 WXSS、mini-titlebar 的 TS/WXML/WXSS，以及 repair-return-page.spec.ts。完整 PR 说明现见已合并的 [PR #49](https://github.com/kocotree/order_tracking/pull/49)。

最终本地验证：Node.js 24，16 个测试文件共 71 项通过；lint、build（typecheck 和项目结构检查）、git diff --check 通过。返修新增 3 项测试覆盖默认折叠/独立展开、收起和预览往返保留数量、折叠项数量超限仍拦截。

以实际 WXML/WXSS 和样例数据在浏览器做了 320px 窄屏近似渲染，检查名称与编号同一行、长文本截断、返修折叠展开、通知卡片宽度。此检查不是微信原生编译或真机视觉验收，也不替代原型并排验收；#42/#43/#46 的原生表现待用户在微信开发者工具核对。无服务器或数据库变更，无须为这批代码部署服务器；现有 API 仍需正常可用。未执行远程 CI、推送、PR 创建、部署或小程序上传。
