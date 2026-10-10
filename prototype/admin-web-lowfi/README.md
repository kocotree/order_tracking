# 管理员网页端原型

本目录模拟跟单管理系统 Web 管理端的页面和交互，不连接飞书、真实 API 或数据库。2026-09-07 按当前前端提交 `50747abd` 反向同步；历史逐页差异、范围和未完成项可从 Git 历史中的 Web 原型同步记录查阅。

原型包含看板、通知、订单、发货、返修、工厂、产品、人员及身份页面；#187 已删除待导入列表、详情和相关入口。历史字段与交互须对照[现行页面地图](../../docs/一期/project/一期三端页面地图.md)及正式需求；原型检查记录不能代替当前正式页面的业务或视觉验收。

## 本地查看

Issue #240（2026-10-10）：发货详情删除人工确认及旧撤回审批，已收货可继续修改箱内数量和同厂同产品订单/规格；保存立即更新模拟订单数量，退回后只读。原报快照保留，下载仍为演示提示。打开 `#/shipments/FH20260812-006` 可演示连续保存，`#/shipments/FH20260814-003` 可演示混装箱。原型不发送通知、不连接生产；三端各自使用独立模拟数据。页面范围已授权，本轮更新后的视觉待用户查看。

非浏览器交互自检：在仓库根目录执行 `node prototype/check-auto-receipt.mjs`，复用 `admin-web` 已安装的 jsdom。

Issue #240 追加：订单详情删除“关联发货单”区块及专用渲染、排序、跳转和样式；来货出入后直接接操作记录。底层模拟关联数据及已有发货不可撤回订单的校验保留。打开 `#/orders/078%23` 查看；发货单继续从 `#/shipments` 进入。

```bash
cd prototype/admin-web-lowfi
python3 -m http.server 4173
```

浏览器打开 `http://127.0.0.1:4173/#/dashboard`。旧页面需强制刷新。图片为本地示意图，文件上传展示固定解析样例，下载按钮仅演示提示；页面操作只修改内存数据，刷新恢复。

| 内容 | 原型地址 |
|---|---|
| 看板、通知 | `#/dashboard`、`#/notifications` |
| 订单 | `#/orders` |
| 发货、返修 | `#/shipments`、`#/repairs` |
| 产品、工厂 | `#/products`、`#/factories` |
| 工厂申请、管理员、工厂用户 | `#/people`、`#/people?tab=admin-users`、`#/people?tab=users` |
| 登录、停用 | `#/login`、`#/access-status/disabled` |

## 文件边界

- `scripts/components/`：公共外壳、排序和数字分页。
- `scripts/pages/`：逐页渲染和本地演示交互。
- `scripts/mock-data.js`：模拟数据，各页面共用同一模块。
- `styles/frontend-baseline.css`：当前 Web 样式的独立副本。
- `styles/prototype-adapter.css`：普通 JS 的可见性、包装节点和原型提示适配。
- 其他历史样式文件不再被 `index.html` 加载，不能用来判定当前页面样式。

正式实现继续位于 `admin-web/`，原型与正式实现不互相引用运行代码。
