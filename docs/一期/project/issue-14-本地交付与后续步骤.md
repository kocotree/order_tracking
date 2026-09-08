# Issue #14 本地交付与后续步骤

> **2026-09-08 状态核验：** 已由 [PR #37](https://github.com/kocotree/order_tracking/pull/37) 合并，Issue #14 已关闭。
>
> 下文保留当时实施、授权停止点和验证证据，均属历史记录。提交、推送、建 PR 的旧待办已被上述合并结果替代；其余真实验收不得仅凭合并推定通过。

## 当前状态

用户授权按收窄范围实现和测试，完成后停止，不提交、推送或创建 PR。独立工作树分支 `codex/issue-14-product-image-preview`，基线 `761b4f039e0c6947c3e6b3eb18c2df78b593c389`；基线完整 CI `33974536003` 成功。原有 6 份 #14 文档修改完整保留。

## 改动范围

- `admin-web/src/components/ProductImage.vue`：缩略图、原生 dialog 放大预览、关闭按钮/遮罩/Esc、Tab 焦点、恢复触发位置和滚动样式；失败不可预览，版本更新重置状态。
- `admin-web/src/pages/ProductsPage.vue`：复用该组件。
- `admin-web/src/pages/OrderDetailPage.vue`、`OrderImportDetailPage.vue`、`ShipmentDetailPage.vue`：删除产品图片表头、单元格及发货表对应 colgroup。
- `admin-web/src/styles.css`：同步删列后的选择器，产品名称列吸收余量，确保序号列 52px、左右各 8px、居中。
- `admin-web/src/__tests__/`：新增 ProductImage.spec.ts，修改 App、OrderDetailPage、OrderImportDetailPage、ShipmentDetailPage 四份测试。
- 正式需求、S03/S04/S05/S07 工单、表格视觉规范和里程碑记录同步；PR 正文见已合并的 [PR #37](https://github.com/kocotree/order_tracking/pull/37)。
- 原型、后端、OpenAPI、数据库、小程序、合同和发货清单导出、发货凭证实现未修改。

## 验证与边界

Node.js 24 / pnpm 11.22.0，网页 47 项测试、ESLint、类型检查、生产构建通过。修改前基线为 45 项通过。首轮失败来自旧图片列断言及 jsdom 未提供 dialog 方法；按新业务范围更新断言并在组件测试中提供浏览器方法替身。未降低业务断言。

Edge 隔离会话使用受控 API 和图片响应验证：加载成功预览、缺图占位、关闭按钮/遮罩/Esc、Tab、筛选及分页保持。四张表在 1440/1024 像素视口下实测序号列 52px、左右各 8px、居中。浏览器发现发货明细全列定宽会拉伸序号，已通过产品名称列吸收余量修正。

四页与旧原型以每页 1440×1000 并排检查。已确认差异是三页删图片列、产品资料图片预览和序号适配。旧原型仍用占位图和演示数据；订单关联发货表、状态颜色、操作顺序及历史布局差异在本次前已存在，未扩展修改。截图保留在本工作树 `output/playwright/issue14-*.png`（忽略的本地验收产物，不提交）。

未验证：真实 API/OSS 图片读取权限和缓存联调、共享测试业务验收、其他浏览器、后端及小程序全量测试。新改动尚无远程 CI。不得据此关闭真实业务验收或宣称已部署。

## 后续步骤

Git 交付已由 PR #37 完成，不再重复提交、推送或建 PR。真实图片、共享测试及其他环境的验收应按当前 Issue/发布记录核对，本篇仅保留当时本地证据。
