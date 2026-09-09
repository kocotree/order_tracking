# Issue #76 本地验证与交接

本轮授权：按已确认方案修改业务代码、完成必要测试、准备本地演示并本地提交后停止。不推送、不建PR、不部署、不运行Playwright或微信开发者工具，页面视觉与业务体验由用户自行验收。

## 本地入口与数据

- Web：<http://127.0.0.1:5176/repairs>。未登录时点击“通过飞书登录”，使用本地演示身份进入；这不是正式飞书账号授权。
- API：<http://127.0.0.1:8000/health/ready>。
- 工程：本轮独立Worktree的`miniprogram/`，分支`codex/issue-76-repair-periods`。不要打开另一工作区的小程序代码。
- 独立本地MySQL：开发库`order_tracking_issue76_dev`（3307），测试库`order_tracking_issue76_test`（3308），均不连接共享测试或生产。测试清理只针对测试库。
- 演示工厂：返修演示工厂，编号DEMO76；演示产品：演示遮阳帽。
- [演示质检单1.xlsx](../../reference/issue-76-demo/演示质检单1.xlsx)：蓝色/M 30件、粉色/S 12件，共42件。
- [演示质检单2.xlsx](../../reference/issue-76-demo/演示质检单2.xlsx)：蓝色/M 20件、粉色/S 8件，共28件。
- 两份Excel已通过真实上传解析与确认流程入库，周期`2026.8-2027.1`，合计70件；蓝色/M合计50件、粉色/S合计20件。初始未发回，便于用户测试。
- 上传区使用原文件名，正式附件按创建日期显示，本次同日两份为`2026-09-09-01.xlsx`、`2026-09-09-02.xlsx`。再次上传上述已创建文件应提示“该文件已创建”；修改数量后另存才能测试新文件创建。

## 微信开发者工具：真实本地API

1. 导入本轮Worktree的`miniprogram`文件夹。使用自己的小程序AppID或工具允许的测试AppID；本地`project.config.json`已按示例准备，不提交真实AppID。
2. “详情 → 本地设置”勾选“不校验合法域名、web-view（业务域名）、TLS版本以及HTTPS证书”。使用模拟器；手机中的127.0.0.1不是这台电脑。
3. 普通编译，打开调试器Console。不要加`preview=1`参数，这会进入静态预览而非本地数据。
4. 工厂身份执行：

```javascript
wx.request({
  url: "http://127.0.0.1:8000/api/v1/local-demo/repair-login?role=factory",
  method: "POST",
  success({ data, statusCode }) {
    if (statusCode !== 200) { console.error("本地演示登录失败", statusCode); return; }
    wx.setStorageSync("identity.accessToken", data.session.accessToken);
    wx.setStorageSync("identity.refreshToken", data.session.refreshToken);
    wx.setStorageSync("identity.user", data.user);
    wx.reLaunch({ url: "/pages/factory-tasks/factory-tasks" });
  }
});
```

进入“返修”页签，打开周期卡片，即可查看四块内容、填写本次发回与草稿恢复。

5. 管理员身份执行：

```javascript
wx.request({
  url: "http://127.0.0.1:8000/api/v1/local-demo/repair-login?role=admin",
  method: "POST",
  success({ data, statusCode }) {
    if (statusCode !== 200) { console.error("本地演示登录失败", statusCode); return; }
    wx.setStorageSync("identity.accessToken", data.session.accessToken);
    wx.setStorageSync("identity.refreshToken", data.session.refreshToken);
    wx.setStorageSync("identity.user", data.user);
    wx.reLaunch({ url: "/pages/admin-shipments/admin-shipments" });
  }
});
```

点击“返修进度”，按周期查看同一份数据及发回历史；管理员小程序只读，Web负责上传和整周期归档。

该登录入口只存在于`server/scripts/repair_period_demo.py`，要求本地演示模式和指定本地库；正式应用入口不注册它。此演示没有启动通知worker，不外发真实消息。

## 建议人工验证顺序

1. 三端先看到同一工厂、同一周期、70件及两份附件；Web详情显示2个SKU，没有箱明细和发回历史。
2. 工厂蓝色/M填写返修35、报废5，提交后返回总数量为40、待返回为30。两张源单分配30和10，两个小程序历史只显示一次40件，Web汇总同步。
3. 剩余蓝色/M 10件和粉色/S 20件发回后周期完成；Web归档二次确认后，三端列表和附件入口隐藏。归档会实际修改本地演示数据，建议最后验证。
4. 新建页可把两份修改数量后另存的Excel一起拖入，也可点击同一区域选择；解析通过只显示原文件名和状态。混入错误文件应显示其文件名和具体原因；确认创建只处理通过文件。

## 启停与复现

在本轮Worktree根目录启动后端（`.env`为本机忽略文件，含本地连接配置，不提交）：

```sh
cd server
set -a
source ../.env
set +a
uv run uvicorn scripts.repair_period_demo:create_demo_app --factory --host 127.0.0.1 --port 8000
```

另一个终端启动Web：

```sh
cd admin-web
pnpm dev --host 127.0.0.1 --port 5176 --strictPort
```

使用项目要求的Node 24。后端重启会按内容判重，保留已发生的本地发回/归档，不自动重置数据。演示附件使用内存文件存储；启动时会恢复这两份固定Excel，其他手动上传文件的字节只保留至后端停止。需要持续验证上传附件时保持服务运行。

测试必须覆盖演示模式配置，避免自动初始化影响测试：

```sh
cd server
set -a
source ../.env
set +a
export ORDER_TRACKING_APP_ENV=development
uv run pytest -q
uv run ruff check .
uv run mypy app
uv run alembic check
```

本次迁移0033只执行于上述隔离本地库。发现旧非空草稿或归档记录会停止；降级会移除周期分组及新周期草稿，虽保留原单/来源发回事实，也不是无损业务回滚方案。未批准任何共享测试或生产迁移。

## 验证记录

- 后端全量执行349项：347通过，1项OSS测试因未配置独立桶跳过，1项旧表结构断言缺少新增的`period_id`。修正该断言后，最终返修专项19项全部通过（包括新增迁移前后原始明细一致、跨单通知、角色接口边界）；没有遗留失败。没有重复声称运行过修正后的全量测试。
- Web 88项通过；小程序83项通过。两端lint、类型检查及构建通过。
- 后端Ruff、mypy（73个源文件）、OpenAPI导出一致性、Alembic模型一致性通过。专项执行0033→0032→0033，核对已有质检明细、数量和来源发回历史保留。
- 实际本地HTTP检查：Web200、API健康、工厂和管理员登录、周期列表/详情及两份附件下载成功，开发库保持初始70件未发回。没有执行浏览器视觉检查、微信开发者工具、远程CI、部署或真实通知发送；本地测试通过不等于上述验收通过。
