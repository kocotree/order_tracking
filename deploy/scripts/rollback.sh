#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

environment=${1:-}
target_commit=${2:-}
resolve_environment "${environment}"

if [[ ${ORDER_TRACKING_ROLLBACK_CONFIRMED:-} != "${environment}" ]]; then
  echo "set ORDER_TRACKING_ROLLBACK_CONFIRMED=${environment} after approving the exact target" >&2
  exit 1
fi
if [[ ! "${target_commit}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "rollback target must be an exact 40-character Git SHA" >&2
  exit 2
fi
if [[ -n $(git -C "${repository_root}" status --porcelain --untracked-files=no) ]]; then
  echo "tracked server worktree changes must be resolved before rollback" >&2
  exit 1
fi
git -C "${repository_root}" cat-file -e "${target_commit}^{commit}"
git -C "${repository_root}" switch --detach "${target_commit}"
compose build api worker admin-web
compose up -d api worker admin-web
"${deploy_root}/scripts/health-check.sh" "${environment}"
echo "application rollback completed without an Alembic downgrade"
