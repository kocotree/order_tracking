# 微信小程序

这是管理员和工厂共用的唯一一套微信原生 TypeScript 小程序工程。当前包含身份与工厂申请页面，以及 S04 管理员只读订单列表/详情、工厂“任务—订单”列表/详情。发货和返修业务仍由后续工单接入。

## 命令行检查

项目固定 Node.js 24 与 pnpm 11.22.0：

```bash
corepack enable
corepack prepare pnpm@11.22.0 --activate
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
```

## 微信开发者工具

1. 复制 `project.config.json.example` 为 `project.config.json`；该文件已被 Git 忽略；
2. 将其中的 `appid` 改为你当前使用的测试号或正式小程序 AppID；
3. 在微信开发者工具选择仓库中的 `miniprogram/` 目录，不要再创建第二个项目；
4. 开发工具会按 `useCompilerPlugins: ["typescript"]` 编译根目录下的 TypeScript 源码；
5. 本地开发接口默认为 `http://127.0.0.1:8000/api/v1`，体验版和正式版当前使用不可访问的 `example.invalid` 占位域名，接入真实 HTTPS 域名前不得发布。

真实 AppID、AppSecret、域名凭证和生产接口地址不得提交到 Git。
