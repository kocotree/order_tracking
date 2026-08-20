# 管理员网页端

Vue 3、TypeScript、Vite、Vue Router、Pinia 和 Element Plus 工程，当前已实现 S01 管理员登录、身份申请、审核状态、最高管理员审核和普通管理员启停页面。

项目固定 Node.js 24 与 pnpm 11.22.0。本机没有 Node.js 24 时，可使用项目 CI 或 Node.js 24 容器执行同样命令；不要把本机 Node.js 26 当成项目基线。

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

开发前可将 `.env.example` 复制为 `.env.local` 并设置 `VITE_API_BASE_URL`。OpenAPI 类型由 `../server/openapi/openapi.json` 生成，修改接口后必须重新执行 `pnpm generate:api` 并提交生成结果。

本机开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`。后端以 `local_demo` 模式启动后，运行 `pnpm dev --host 127.0.0.1 --port 5173`，打开 `http://127.0.0.1:5173/` 即可从正式登录页进入假身份验收流程。该入口不代替真实飞书、短信或微信联调。
