# S12 deployment entrypoint

Shared test uses the company SSH + Git + Docker Compose path. Production uses
the tag-triggered image CD described below. This directory never stores real credentials.

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

```bash
git switch main
git pull --ff-only origin main
# Confirm this commit's main CI and shared-test acceptance have passed first.
git tag v1.0.0
git push origin v1.0.0
# Observe publication and deployment in the same run.
gh run list --workflow release.yml --limit 5
```

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

The deployment checks both image revision labels, backs up MySQL and OSS, runs
migrations, waits for container health, and records the version only on success.
After each successful backup the script keeps the newest 30 MySQL dumps and 3 OSS
snapshots and deletes the rest; it only matches its own `production-<stamp>` names,
so manual artefacts in the same directories are left alone. A daily 00:00 cron on
the server runs the same script under the deployment lock, so scheduled and
deployment backups share one retention pool.
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
No automatic rollback, migration replay, archive policy or data cleanup is introduced.

For application rollback, use the retained previous release directory and exact
previous image version, export `ORDER_TRACKING_DEPLOY_VERSION`, and run Compose
`up -d --no-build --wait api worker admin-web`, followed by `health-check.sh
production`. Do not run migrations or Alembic downgrade during rollback. Verify
schema compatibility first, and update the protected version and release record
after the rollback is healthy. Keep previous images; do not run broad image prune.
