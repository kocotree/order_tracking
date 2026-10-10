# 跟单管理系统

生产部与外协工厂共用的订单协作系统，包含管理员网页端、管理员与工厂共用的微信小程序、服务器 API 和 worker，并提供 Codex 管理员 MCP、来货出入飞书机器人及箱贴导出。

管理员处理订单同步与派工、合同、收货、退回、返修和基础资料；工厂通过小程序装箱发货与返修发回。MySQL 保存正式业务事实，飞书提供订单来源，聚水潭提供产品与采购资料。

## 阅读入口

- 使用与交付：[文档目录](docs/README.md)、[交付清单](docs/shared/delivery/交付清单.md)、[操作手册](docs/README.md#操作手册)。
- 开发与维护：[AGENTS.md](AGENTS.md)、[领域术语](CONTEXT.md)、[飞书交接文档](https://kocotree.feishu.cn/docx/F8VqdJGk8oTjMIxZzfOcwmAXnhb)。
- 业务依据：[一期需求及增量](docs/一期/requirements/一期需求文档.md)、[二期建设范围](docs/二期/project/二期需求建设计划.md)。
- 发布与运行：[部署说明](deploy/README.md)、[验收记录](docs/shared/delivery/验收记录.md)。

## 工程入口

| 目录 | 内容与启动说明 |
|---|---|
| [server](server/README.md) | FastAPI、业务服务、worker、MySQL 迁移与运维 CLI |
| [admin-web](admin-web/README.md) | Vue 3 管理员网页端 |
| [miniprogram](miniprogram/README.md) | 微信原生 TypeScript 小程序 |
| [deploy](deploy/README.md) | 隔离环境配置、备份、发布与恢复脚本 |
| [docs](docs/README.md) | 正式需求、设计、计划、交付正文和操作手册 |
| `prototype/` | 已批准页面的交互参考；各目录 README 说明预览方式与历史边界 |

## 本地开发

工具链固定为 Python 3.13＋uv、Node.js 24＋pnpm 11.22.0、MySQL 8.0 和 Docker Compose；使用现有锁文件安装。

首次在仓库根目录准备被 Git 忽略的本地配置及隔离数据库：

```bash
cp .env.example .env
docker compose up -d --wait mysql-dev mysql-test
```

填写本机开发值后，按上表各工程 README 安装、迁移、启动和检查。后端工程提供 API 与 worker 两个入口；两客户端通过同一套 API 访问业务数据。

## CI、发布与安全

PR 和 main 推送运行 [CI](.github/workflows/ci.yml)，全部任务成功才称为通过。明确授权后推送 `v*` 标签触发 [Release](.github/workflows/release.yml)，核验同一提交的 main CI 后发布两个镜像并部署生产；存在待执行迁移时先备份 MySQL 再升级，无迁移时跳过备份和迁移。普通 main 推送不触发发布；小程序发布与真实通知须各自授权。

开发、测试和生产环境及数据必须隔离；本地自动化不得访问生产资源。密钥、真实 AppID、Token、数据库密码和生产数据不得提交。生产固定不可变版本标签；运行版本、客户端兼容及业务签收以[交付清单](docs/shared/delivery/交付清单.md)的实际核验记录为准。
