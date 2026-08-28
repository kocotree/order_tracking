#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

environment=${1:-}
target_commit=${2:-}
resolve_environment "${environment}"

if [[ ! "${target_commit}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "target commit must be an exact 40-character Git SHA" >&2
  exit 2
fi
if [[ $(git -C "${repository_root}" rev-parse HEAD) != "${target_commit}" ]]; then
  echo "checked-out commit does not match the approved target" >&2
  exit 1
fi
if [[ -n $(git -C "${repository_root}" status --porcelain --untracked-files=no) ]]; then
  echo "tracked server worktree changes must be resolved before deployment" >&2
  exit 1
fi
if [[ $(git -C "${repository_root}" rev-parse --is-shallow-repository) == "true" ]]; then
  echo "deployment repository must not be shallow" >&2
  exit 1
fi

available_kib=$(df -Pk "${repository_root}" | awk 'NR == 2 {print $4}')
recommended_kib=$((15 * 1024 * 1024))
if (( available_kib < recommended_kib )); then
  echo "warning: less than the project-recommended 15 GiB disk margin is available" >&2
fi

docker version >/dev/null
docker compose version >/dev/null
docker network inspect traefik-network >/dev/null
compose config --quiet
echo "preflight passed for ${environment} at ${target_commit}"
