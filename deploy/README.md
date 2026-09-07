# S12 deployment entrypoint

Shared test uses the company SSH + Git + Docker Compose path. Production uses
the manual-dispatch image CD described below. This directory never stores real credentials.

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
6. Configure and verify Traefik/HTTPS only after internal health is green.
7. Keep all real notification switches false until each first-send gate is approved.

Production uses the image CD procedure below with an approved immutable tag.
A successful release does not authorize real messages, Mini Program upload,
trial operation, or production cutover.

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

1. Merge the associated PR and wait for complete main CI.
2. Push an approved `vMAJOR.MINOR.PATCH` tag. Wait for **Release images** to pass.
3. Run **Deploy production**, selecting that same tag (not main). This reruns
   complete CI, checks successful image publication, and deploys through SSH.
4. Configure the GitHub `production` environment with reviewers when available.
   Manual dispatch is an explicit production action even without environment reviewers.
5. Verify external HTTPS and real user login separately after internal health.

Required repository/environment Secrets: `PROD_SSH_HOST`, `PROD_SSH_PORT`,
`PROD_SSH_USER`, `PROD_SSH_PRIVATE_KEY`, `PROD_SSH_KNOWN_HOSTS`, `PROD_DEPLOY_DIR`.
Use a dedicated deployment SSH key and verified host keys. The workflow uses its
short-lived `GITHUB_TOKEN` to pull GHCR images; it removes the temporary Docker
login configuration when finished. No personal registry token is required.

Provision the protected configuration at `DEPLOY_DIR/deploy/.env.production`.
Set `ORDER_TRACKING_MYSQL_BACKUP_DIR` and `ORDER_TRACKING_OSS_BACKUP_DIR` to existing
protected absolute directories. The server needs Docker Compose with `--wait`,
Python 3.8+, mysqldump, flock, and ossutil 2.x. Release artifacts are retained at
`DEPLOY_DIR/releases/<commit>/`; no source checkout is needed on the server.

The deployment checks both image revision labels, backs up MySQL and OSS, runs
migrations, waits for container health, and records the version only on success.
Backup completion checks are not a substitute for periodic restore rehearsals.
On failure, inspect the actual container and schema state before retrying; DDL
and a partial container replacement cannot automatically be rolled back safely.

For application rollback, use the retained previous release directory and exact
previous image version, export `ORDER_TRACKING_DEPLOY_VERSION`, and run Compose
`up -d --no-build --wait api worker admin-web`, followed by `health-check.sh
production`. Do not run migrations or Alembic downgrade during rollback. Verify
schema compatibility first, and update the protected version and release record
after the rollback is healthy. Keep previous images; do not run broad image prune.
