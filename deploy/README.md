# S12 deployment entrypoint

This directory implements the company SSH + Git + Docker Compose path. It does not
add automatic CD and never stores real credentials.

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

Production uses the same order with `production` and an approved immutable tag or
commit. A successful release does not authorize DNS, real messages, Mini Program
upload, trial operation, or production cutover.

## Rollback and restore boundaries

- `rollback.sh` switches a clean deployment worktree to an exact prior commit,
  rebuilds the application, and intentionally does not run Alembic downgrade.
- `restore-mysql.sh` only accepts a target database ending in `_restore`.
- `restore-oss.sh` only accepts a target bucket ending in `-restore` and requires
  isolated restore credentials in the protected shell environment.
- Restore rehearsal, production rollback, DNS, and live data changes require their
  own explicit approval. Backup files and runtime records remain outside Git.
