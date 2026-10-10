# Deployment entrypoint

Shared test uses the company SSH + Git + Docker Compose path. Production uses
the tag-triggered image CD described below. This directory never stores real credentials.

开发、发布、日常巡检及排障的中文入口：[飞书交接文档](https://kocotree.feishu.cn/docx/F8VqdJGk8oTjMIxZzfOcwmAXnhb)。小程序审核账号在该文档填写，详细上传步骤见[miniprogram README](../miniprogram/README.md)。本文维护部署脚本、配置及恢复参数。

## Environment separation

- Shared test uses `compose.shared-test.yaml` and protected `.env.shared-test`.
- Production uses `compose.production.yaml` and protected `.env.production`.
- The examples document required names only. Copy the matching example on the
  server, replace every placeholder there, and run `chmod 600` on the real file.
- Each environment must use a different database, least-privilege database user,
  private Alibaba Cloud OSS bucket and RAM credentials, domain, Compose project,
  and external-system identities. The web
  UI and `/api/` share one domain per environment through the Nginx proxy.

## First clone and later updates

Only after the exact commit has passed the complete GitHub Actions CI and the user
has approved the server operation:

```bash
git clone <company-readonly-repository-url> <approved-independent-directory>
cd <approved-independent-directory>
git status --short
git pull --ff-only
git rev-parse HEAD
```

Do not paste the repository credential into the command, chat, documentation, or
shell history. Confirm the exact SHA equals the CI-passed target before continuing.

## Release order

1. Run `scripts/preflight.sh shared-test <40-character-commit>`.
2. Create and verify MySQL and OSS backups in protected independent storage.
3. Set `ORDER_TRACKING_BACKUP_CONFIRMED=yes` only for the release shell.
4. Run `scripts/release.sh shared-test <commit> <successful-ci-run-id>`.
5. Review `docker compose ps`, worker/API logs, and internal health results.
   `scripts/health-check.sh` also verifies that `docker compose top worker` lists
   the `sync`, `incoming`, `notification`, and `shipment` child processes.
6. Configure and verify Traefik/HTTPS only after internal health is green.
7. Keep all real notification switches false until each first-send gate is approved.

The single worker container starts four serial task processes. Their JSON logs
include `role` and `workerId`; job failures include `jobId` and `jobType`, and
delivery logs include `deliveryId`. Each child owns its database pool and external
clients. With SQLAlchemy defaults, four worker pools permit up to 60 connections
in total; include the API pool when checking the MySQL connection limit. A child
exit stops its siblings and exits nonzero so Docker restarts the whole container.
SIGTERM/SIGINT stops new claims; the manager waits 30 seconds, kills any child
still running, and reaps all children. Compose allows 45 seconds before force
stopping the container. Interrupted generic jobs recover after their five-minute
stale lease; `order_auto_sync` uses its existing lock-aware recovery. Outbox
processing recovers in the notification process. Check `docker compose top worker`
and the four `worker.started` events after a restart before treating it as live.

`sync` owns the six order/product jobs. `shipment` alone schedules and executes
`shipment_writeback`, including recovery of jobs previously claimed by `sync`.
Job types, IDs, frozen snapshots and retry limits are unchanged. When writeback
is disabled, `shipment` stays alive without scheduling or external writes;
already queued jobs retain the existing target-not-configured failure/retry behavior.
Issue #231 changes process ownership only; deployment and writeback enablement
require separate authorization.

Production uses the image CD procedure below with an approved immutable tag.
A production tag authorizes that version’s server deployment. It does not
authorize real messages, Mini Program upload, or business trial operation.

## Rollback and restore boundaries

- `rollback.sh` switches a clean deployment worktree to an exact prior commit,
  rebuilds the application, and intentionally does not run Alembic downgrade.
- `restore-mysql.sh` only accepts a target database ending in `_restore`.
- `restore-oss.sh` only accepts a target bucket ending in `-restore` and requires
  isolated restore credentials in the protected shell environment.
- Restore rehearsal, production rollback, DNS, and live data changes require their
  own explicit approval. Backup files and runtime records remain outside Git.

## Production image CD

Production now uses GHCR images through `compose.production.yaml`. The old
Git/build release and rollback scripts are for shared test only. No ordinary
`main` push deploys production.

1. Merge the associated PR and wait for complete **main push CI** on that exact commit.
2. Push an approved `vMAJOR.MINOR.PATCH` tag. This is the production approval.
3. **Release and deploy production** verifies the latest main push CI for the tag's
   exact commit, including all five required jobs. Missing, pending, failed or
   skipped CI stops publication; release and CD do not rerun the test suite.
4. Both GHCR image publications must succeed before the same workflow automatically
   calls **Deploy production**. No separate manual CD command is needed. The deploy
   workflow is reusable only; `needs: publish` is the publication gate.
5. Verify external HTTPS and real user login after internal health.

Production version numbering starts at `v1.0.0` by the user's 2026-09-08 decision,
independent of the Mini Program version. Subsequent patches use new tags such as
`v1.0.1`; never move or overwrite a published tag. Publish one version at a time
and wait for deployment completion before starting another.

Choose a new unused version for the approved commit; `v1.0.0` and other published
tags must not be reused. Observe publication and deployment with
`gh run list --workflow release.yml --limit 5`.

If CI was still running when the tag was pushed, wait for main CI success and
rerun the failed Release jobs on the same immutable tag. Do not recreate the tag.
The `production` environment must not require an extra reviewer if fully automatic
deployment after tag push is desired. Its existing secrets/environment separation remain.

Required repository/environment Secrets: `PROD_SSH_HOST`, `PROD_SSH_PORT`,
`PROD_SSH_USER`, `PROD_SSH_PRIVATE_KEY`, `PROD_SSH_KNOWN_HOSTS`, `PROD_DEPLOY_DIR`.
Use a dedicated deployment SSH key and verified host keys. The workflow uses its
short-lived `GITHUB_TOKEN` to pull GHCR images; it removes the temporary Docker
login configuration after image pull (also on normal task failure). No personal
registry token is required.

Provision the protected configuration at `DEPLOY_DIR/deploy/.env.production`.
Set `ORDER_TRACKING_MYSQL_BACKUP_DIR` and `ORDER_TRACKING_OSS_BACKUP_DIR` to existing
protected absolute directories. The server needs Docker Compose with `--wait`,
Python 3.8+, mysqldump, flock, and ossutil 2.x. Use a local Linux filesystem that
supports flock for the deployment root. Release artifacts are retained at
`DEPLOY_DIR/releases/<commit>/<run-id>-<attempt>/`; each Actions attempt uploads
to its own directory, leaving an active task's scripts intact. No source checkout
is needed on the server. Older releases keep their original directory layout.

The deployment checks image revisions and the target Alembic graph. Pending
migrations require a successful MySQL backup before upgrade; current schemas skip
both. Failed checks, unknown/incompatible revisions, multiple heads and unversioned
nonempty databases stop deployment. Deployment does not copy OSS. Container health
must pass before recording the version.
After each successful backup the script keeps the newest 7 MySQL dumps and 3 OSS
snapshots and deletes the rest; it only matches its own `production-<stamp>` names,
so manual artefacts in the same directories are left alone. The independent daily
00:00 backup schedule uses the same script and deployment lock, so scheduled and
deployment backups share one retention pool. Verify the actual cron installation,
host timezone and recent successful runs on the server.
Backup completion checks are not a substitute for periodic restore rehearsals.
On failure, inspect the actual container and schema state before retrying; DDL
and a partial container replacement cannot automatically be rolled back safely.

### Detached task and reconnect

`deploy-task.py start` registers one task per immutable version, bound to its exact
revision, then starts a new server process session with independent standard streams.
The server continues after SSH disconnects or the Actions job is cancelled.
`release-images.sh` still owns `production-deploy.lock` across image verification,
backup, migration, container update, health/four-worker checks and version recording.
Concurrent versions and scheduled backups use the same lock.

Task files are private at `DEPLOY_DIR/runtime/deployments/<version>/`:

- `state.json`: version, revision, original release directory, start time, worker PID,
  final exit code and finish time; terminal results are atomically replaced and synced.
- `stage`: current or last attempted stage.
- `events.log`: timestamped stage transitions and final exit code. External command
  stdout/stderr is suppressed to prevent credentials entering durable logs.
- `lease`: inherited file lock used to check whether the task or its release child
  still owns execution. PID alone is never used as proof of liveness.

Actions queries every 10 seconds, with SSH keepalive and a 60-second query timeout.
It tolerates up to 12 consecutive communication failures and waits at most 3 hours.
Exhaustion reports **deployment result unconfirmed**, without stopping the server.
Rerunning the failed deploy job queries the registered task; running and successful
tasks do not repeat login, backup, migration or container replacement. A lost start
reply can safely repeat registration. The same version with another revision is rejected.
Upload failures occur before this attempt starts a task; reconnect to check any
task from an earlier attempt.

Read the result over a new verified SSH connection, using the retained script and
the exact version/revision (registry user is the non-secret GitHub login):

```bash
python3 <release-dir>/deploy/scripts/deploy-task.py status <DEPLOY_DIR> <version> <40-character-commit> <registry-user>
cat <DEPLOY_DIR>/runtime/deployments/<version>/events.log
```

`running` requires a held lease; `succeeded` requires a completed zero-exit result;
`failed` retains the stage and nonzero exit code. Missing/corrupt state, released
leases without a terminal result, forced process termination or server reboot yield
`unknown`. `absent` means no task directory; identity conflicts are reported separately.
A successful task result is historical evidence for that version; use the normal
runtime checks to confirm the currently running version and external HTTPS.

Failed/unknown tasks never restart automatically. Preserve the task directory and
inspect its last stage, backup artefacts, actual schema, images and containers before
an explicitly authorized recovery. Do not delete state or rerun the release script
to force a retry. After forced termination during login/pull/backup, protected
temporary credential files may remain in the task directory; inspect and clean those
only after confirming no process still uses them and obtaining cleanup authorization.
No automatic rollback or migration replay is introduced. Archival is independent.

### Independent backup and log archival

Daily backup invokes `backup-production.py <protected-production-env>` under the
existing deployment lock; deployment adds the `mysql` argument. Only managed
successful names with checksums count toward retention. Incomplete snapshots,
symlinks and manual files are preserved. Seven dumps may cover fewer than seven days.

Copy `archive.env.example` into a protected file outside Git with separate archive
database/RAM credentials. Use the retained release directory and approved image:

```bash
bash deploy/scripts/archive-logs.sh <version> <archive-env> inventory
bash deploy/scripts/archive-logs.sh <version> <archive-env> run --limit 1000 --confirm archive-and-expire
bash deploy/scripts/archive-logs.sh <version> <read-only-env> search --table audit_logs --from-utc 2026-09-01T00:00:00 --to-utc 2026-09-02T00:00:00 --limit 1000
```

Search uses naive UTC boundaries and optional `--id`, returning verified redacted
records that have not expired. Run handles up to the limit per source table and
expiry sweep. After separate authorization, configure an independent hourly cron
with the exact approved run command; retain the independent daily backup schedule.
Deployment installs neither task. Capture exit status and investigate failures.

The script takes the deployment flock and archival takes a MySQL named lock.
`log_archive_entries` tracks pending/completed transfers and original-time expiry.
One private gzip JSON object per record under `log-archives/v1/` permits exact expiry.
Source details are removed only after GET, SHA-256 and identity verification in a
locked transaction. Interrupted runs resume pending entries; never delete manifests
to force progress. Completed job/outbox dedupe rows and referenced import rows remain
with `archived_at`; protected business audit, cursor and unfinished/failed records
remain intact. Log archives do not use snapshot retention; old backups may still
contain expired records.

Archive DB permissions: source/dependency SELECT, manifest INSERT/UPDATE/DELETE,
eligible audit/product row DELETE, eligible import/job/outbox detail UPDATE. RAM:
GetBucketAcl and Get/Put/DeleteObject limited to the archive prefix. Search only
needs manifest SELECT, GetBucketAcl and prefix GetObject. Keep the bucket private;
do not grant archive deletion to API credentials. Validate database restore and
archive retrieval in isolation before enablement. Capacity snapshots do not prove age.

For application rollback, use the retained previous release directory and exact
previous image version, export `ORDER_TRACKING_DEPLOY_VERSION`, and run Compose
`up -d --no-build --wait api worker admin-web`, followed by `health-check.sh
production`. Do not run migrations or Alembic downgrade during rollback. Verify
schema compatibility first, and update the protected version and release record
after the rollback is healthy. Keep previous images; do not run broad image prune.

## 配置与巡检

完整配置名及校验见[Settings](../server/app/settings/config.py)。以下名称均带 `ORDER_TRACKING_` 前缀；实际值只保存在受控环境文件中。

| 配置组 | 关键名称及检查 |
|---|---|
| 基础 | `APP_ENV`、`DATABASE_URL`、`ADMIN_WEB_BASE_URL`、`WEB_COOKIE_SECURE`；环境隔离、非root数据库账号、HTTPS与安全Cookie |
| 身份保护 | `IDENTITY_TOKEN_SECRET`、`PHONE_ENCRYPTION_SECRET`、`PHONE_DIGEST_SECRET`；更换前评估既有会话、手机号密文与匹配 |
| 飞书登录 | `FEISHU_IDENTITY_*`、`FEISHU_SUPER_ADMIN_SUBJECTS`；回调、手机号权限、应用版本与最高管理员白名单 |
| 来源与采购 | `FEISHU_ORDER_*`、`JST_*`；来源范围、字段映射、权限、Token续期；聚水潭Token缓存使用持久路径 |
| 微信 | `WECHAT_*`、`WECHAT_NOTIFICATION_MINIPROGRAM_STATE`；AppID、模板、合法域名，测试trial／生产formal |
| OSS | `OSS_*`；私有Bucket、最小RAM权限、Region与Endpoint一致 |
| MCP | `MCP_PUBLIC_URL`、`MCP_CLIENT_ID`、`MCP_FILE_HOSTS`；前两项成对，公开HTTPS `/mcp` 与精确文件主机白名单 |
| 来货出入 | `FEISHU_BOT_ENABLED`、`FEISHU_BOT_VERIFICATION_TOKEN`、`FEISHU_BOT_ENCRYPT_KEY`、`INCOMING_DIFF_VISION_API_KEY`、`INCOMING_DIFF_VISION_BASE_URL`、`INCOMING_DIFF_WORKBOOK_SIGNING_SECRET`；回调验签、模型额度、历史核对表签名兼容 |
| 外发 | `WECHAT_NOTIFICATIONS_ENABLED`、`FEISHU_NOTIFICATIONS_ENABLED`、`OPS_ALERTS_ENABLED`、`OPS_ALERT_RECIPIENT_USER_ID`；核对开关、模板和接收人，首次真实发送须单独验收 |

飞书机器人复用订单来源应用，扩充消息、卡片和资源权限后须发布应用版本；回调成功与下载、识别、投递、正式登记分别检查。

在当前release的`deploy/`目录，确认`.env.production`指向受控生产文件，再执行：

```bash
docker compose --env-file .env.production -f compose.production.yaml ps
docker compose --env-file .env.production -f compose.production.yaml top worker
docker compose --env-file .env.production -f compose.production.yaml logs --since 30m api worker
bash scripts/health-check.sh production
```

预期三容器健康、四个worker角色齐全、内部健康通过；再核对外部HTTPS、登录和关键业务。使用requestId、role、jobId、jobType、deliveryId定位错误，避免复制包含私人数据的整段日志。定向产品与图片维护沿用[server README](../server/README.md#产品同步内部任务)的预览及digest确认命令。

## 隔离恢复与升级边界

恢复配置与数据保存在Git外。获得恢复演练授权后，在独立空库和独立Bucket运行：

```bash
export ORDER_TRACKING_RESTORE_CONFIRMED=restore-test-only
bash deploy/scripts/restore-mysql.sh <备份SQL.gz> <受控恢复环境文件>
bash deploy/scripts/restore-oss.sh <OSS备份目录> <隔离Bucket-restore>
```

以上命令从release根目录执行。MySQL环境文件使用`ORDER_TRACKING_RESTORE_DATABASE_URL`且库名以`_restore`结尾；OSS通过受控shell设置独立`OSS_REGION`、`OSS_ENDPOINT`、`OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`。先核对备份摘要，恢复后核对schema、代表性数量、数据库文件索引与对象、附件和隔离应用可用，记录耗时和错误。MySQL与OSS恢复须选取一致备份批次。

从旧schema升级时，0050遇旧待审核发货／申请／审批通知会停止，须先处理存量；0053的自动收货历史转换按[专题设计第7节](../docs/一期/project/发货自动收货技术设计.md#7-历史转换与切换)在授权维护窗口执行。应用恢复旧版本先查当前schema兼容性；0049、0051、0052、0053等迁移保护既有业务事实，禁止自动降级或删记录绕过保护。

## 出货阶段回填运维

回填由`shipment`进程处理，每分钟扫描到期任务；阶段末日北京时间22点截止。关闭开关时仍保存提交事实，进程保持存活；已排队任务保留既有有限失败重试行为。首次启用按以下顺序执行，真实写入及启用取得明确授权：

1. 保持`ORDER_TRACKING_SHIPMENT_WRITEBACK_ENABLED=false`，确认迁移完成、全部API使用新版本且旧事务退出，再准备历史。
2. 核验订单来源应用对批准目标表的字段读／建／更新、记录读／更新及文档编辑权限，核对字段容量。
3. 在`server/`执行`uv run python -m scripts.shipment_writeback inspect`，取得总数字段及原生公式；结果只留受控配置。核对批准的历史`ROUND(SUM(IFBLANK(...,0),...),0)`基线，填写`ORDER_TRACKING_SHIPMENT_WRITEBACK_TOTAL_FIELD_ID`和`ORDER_TRACKING_SHIPMENT_WRITEBACK_BASELINE_FORMULA`。
4. 执行`uv run python -m scripts.shipment_writeback history`，核对并登记10月6日起存量事实；该步骤不写飞书、不改订单数量、不发通知。证据缺失或状态冲突时停止并处理。
5. 在授权环境验证建列、公式及代表性行写入回读；配置与历史核验通过后，设开关为`true`并按发布流程重启worker，核对`shipment`启动及执行结果。

日志、补排与原任务重试（`server/`工作目录）：

```bash
uv run python -m scripts.shipment_writeback logs
uv run python -m scripts.shipment_writeback schedule
uv run python -m scripts.shipment_writeback retry --job-id <失败任务ID>
```

容器内使用`/app/.venv/bin/python -m scripts.shipment_writeback`；先确认目标环境。`schedule`与`retry`要求启用开关，后者只重置本功能失败任务，保留任务ID、字段绑定、冻结数量和成功行。沿用最多3次尝试、30秒间隔；持续失败先处理权限、关联、公式或网络错误，再显式重试。

阶段单元格仅缺失或null视为空白，已有值含0均保留并记跳过；已验证和已跳过行均为终态，之后清空也不自动补写。日志`verified`为写入回读行数、`skipped`为已有值跳过行数、`verified_quantity`为实际验证的冻结数量；`quantity`为全部冻结统计量。远端成功而本地确认中断后，已有值仍按跳过记录，不推测填写来源。

飞书缺少远端原子条件更新保证，写前复查仍有并发人工编辑窗口，处理期间避免同时编辑目标阶段单元格与总数公式。冻结阶段不因后续补录／撤回重算；后续阶段在前序未冻结时停止。不得删除冻结归属、猜测来源或覆盖漂移公式。关闭开关不撤销已执行的飞书修改。业务定义及并发边界见[技术设计](../docs/二期/project/出货阶段汇总回填技术设计.md)。
