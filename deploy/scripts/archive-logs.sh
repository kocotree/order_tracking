#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
resolve_environment production
version=${1:?provide approved immutable image version}
archive_file=${2:?provide protected archive environment file}
shift 2
[[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.-]+)?$ ]] || exit 2
[[ -f "$archive_file" ]] || exit 2
production_root=$(dirname "$(dirname "$(readlink -f "$environment_file")")")
exec 9>"$production_root/production-deploy.lock"
flock -n 9 || { echo 'Deployment or maintenance is running'; exit 1; }
docker run --rm --network order-tracking-production-internal \
  --env-file "$archive_file" \
  "ghcr.io/kocotree/order-tracking-server:$version" \
  uv run --no-sync python -m scripts.log_archives "$@"
