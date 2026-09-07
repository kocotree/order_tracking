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
exec 9>"$production_root/production-deploy.lock"
flock -n 9 || { echo 'Another production deployment is running'; exit 1; }
export ORDER_TRACKING_DEPLOY_VERSION="$version"
compose config --quiet
compose pull api worker admin-web
for service in server admin-web; do
  image="ghcr.io/kocotree/order-tracking-${service}:${version}"
  actual=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")
  [[ "$actual" == "$revision" ]] || { echo 'Image revision mismatch'; exit 1; }
done
python3 "$deploy_root/scripts/backup-production.py" "$environment_file"
# Migration errors stop deployment. Never downgrade a database automatically.
compose --profile operations run --rm migrate
compose up -d --no-build --wait --wait-timeout 180 api worker admin-web
"$deploy_root/scripts/health-check.sh" production
# Persist the version only after a successful deployment.
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
