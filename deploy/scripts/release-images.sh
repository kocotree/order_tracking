#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
resolve_environment production
version=${1:?provide immutable version tag}
revision=${2:?provide exact Git commit}
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.-]+)?$ ]] || exit 2
[[ "$revision" =~ ^[0-9a-f]{40}$ ]] || exit 2
# Shared across release directories through the protected configuration location.
production_root=$(dirname "$(dirname "$(readlink -f "$environment_file")")")
stage() {
  if [[ -n "${ORDER_TRACKING_DEPLOY_TASK_DIR:-}" ]]; then
    printf '%s\n' "$1" > "$ORDER_TRACKING_DEPLOY_TASK_DIR/stage.pending"
    mv "$ORDER_TRACKING_DEPLOY_TASK_DIR/stage.pending" "$ORDER_TRACKING_DEPLOY_TASK_DIR/stage"
    printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$ORDER_TRACKING_DEPLOY_TASK_DIR/events.log"
  fi
}
stage deployment-lock
exec 9>"$production_root/production-deploy.lock"
flock -n 9 || { echo 'Another production deployment is running'; exit 1; }
export ORDER_TRACKING_DEPLOY_VERSION="$version"
stage compose-config
compose config --quiet
stage image-pull
compose pull api worker admin-web
if [[ -n "${ORDER_TRACKING_DEPLOY_TASK_DIR:-}" ]]; then
  rm -f "$ORDER_TRACKING_DEPLOY_TASK_DIR/registry/config.json"
fi
stage image-revision
for service in server admin-web; do
  image="ghcr.io/kocotree/order-tracking-${service}:${version}"
  actual=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")
  [[ "$actual" == "$revision" ]] || { echo 'Image revision mismatch'; exit 1; }
done
stage migration-check
migration_state=$(compose --profile operations run --rm --no-deps migrate uv run --no-sync python -m scripts.check_migrations)
case "$migration_state" in
  pending)
    stage backup
    python3 "$deploy_root/scripts/backup-production.py" "$environment_file" mysql
    stage migration
    compose --profile operations run --rm migrate
    ;;
  current) ;;
  *) echo 'Invalid migration check result'; exit 1 ;;
esac
stage containers
compose up -d --no-build --wait --wait-timeout 180 api worker admin-web
stage health
"$deploy_root/scripts/health-check.sh" production
# Persist the version only after a successful deployment.
stage record-version
python3 - "$environment_file" "$version" <<'PY'
from pathlib import Path
import os
import sys
os.umask(0o077)
p = Path(sys.argv[1]).resolve()
lines = p.read_text().splitlines()
key = 'ORDER_TRACKING_DEPLOY_VERSION='
lines = [key + sys.argv[2] if line.startswith(key) else line for line in lines]
tmp = p.with_name('.env.production.version-pending')
with tmp.open('x') as output:
    output.write('\n'.join(lines) + '\n')
os.replace(tmp, p)
PY
mkdir -p "$production_root/runtime"
printf '%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$version" "$revision" >> "$production_root/runtime/releases.tsv"
echo "Production deployment healthy: $version $revision"
