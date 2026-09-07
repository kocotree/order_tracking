# 管理员网页端原型

本目录模拟跟单管理系统 Web 管理端的页面和交互，不连接飞书、真实 API 或数据库。2026-09-07 按当前前端提交 `50747abd` 反向同步；完整逐页差异、范围和未完成项见 [Web 原型同步差异清单](../../docs/project/Web原型同步差异清单.md)。

已同步看板、通知、订单/待导入/发货/返修列表与详情、工厂资料、产品资料、人员三个页签和登录/停用页。手工新建/编辑草稿页的“订单日期”与正式需求存在冲突，本轮未新增该表单。原型经过代码和 Node DOM 模拟检查，尚未进行浏览器视觉验收。

## 本地查看

```bash
cd prototype/admin-web-lowfi
python3 -m http.server 4173
```

浏览器打开 `http://127.0.0.1:4173/#/dashboard`。旧页面需强制刷新。图片为本地示意图，文件上传展示固定解析样例，下载按钮仅演示提示；页面操作只修改内存数据，刷新恢复。

| 内容 | 原型地址 |
|---|---|
| 看板、通知 | `#/dashboard`、`#/notifications` |
| 订单、候选 | `#/orders`、`#/pending-imports` |
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
