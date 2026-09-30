# 微信小程序

这是管理员和工厂共用的唯一一套微信原生 TypeScript 小程序工程。当前包含身份与工厂申请、管理员业务查询、工厂订单任务、装箱发货与自主撤回、返修周期发回、来货出入查询及通知。操作见[管理员手册](../docs/shared/delivery/manuals/管理员操作手册.md)与[工厂手册](../docs/shared/delivery/manuals/工厂小程序操作手册.md)，实际发布版本见[交付清单](../docs/shared/delivery/交付清单.md)。

## 命令行检查

项目固定 Node.js 24 与 pnpm 11.22.0：

```bash
corepack enable
corepack prepare pnpm@11.22.0 --activate
pnpm install --frozen-lockfile
pnpm generate:api
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
```

接口类型由 `../server/openapi/openapi.json` 生成至 `api/generated.ts`；接口变更后重新生成并提交结果。`pnpm build` 执行类型及项目结构校验，微信端编译与真机验收须在开发者工具中另行完成。

## 微信开发者工具

1. 复制 `project.config.json.example` 为 `project.config.json`；该文件已被 Git 忽略；
2. 将其中的 `appid` 改为你当前使用的测试号或正式小程序 AppID；
3. 在微信开发者工具选择仓库中的 `miniprogram/` 目录，不要再创建第二个项目；
4. 开发工具会按 `useCompilerPlugins: ["typescript"]` 编译根目录下的 TypeScript 源码；
5. 本地开发接口默认为 `http://127.0.0.1:8000/api/v1`；体验版使用 `https://order-tracking-test.kktree.cn/api/v1`，正式版使用 `https://order-tracking.kktree.cn/api/v1`。域名完成 Traefik/HTTPS 验收并登记为微信合法请求域名前不得上传或发布。

公开 API 地址按开发版、体验版和正式版在 [api/config.ts](api/config.ts) 中维护；真实 AppID、AppSecret、Token 和域名凭证只存于被忽略的本地或受控配置。
