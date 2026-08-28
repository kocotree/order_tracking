#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

environment=${1:-}
target_commit=${2:-}
ci_run_id=${3:-}
resolve_environment "${environment}"

if [[ -z "${ci_run_id}" ]]; then
  echo "the successful GitHub Actions run id is required" >&2
  exit 2
fi
if [[ ${ORDER_TRACKING_BACKUP_CONFIRMED:-} != "yes" ]]; then
  echo "set ORDER_TRACKING_BACKUP_CONFIRMED=yes only after a verified pre-migration backup" >&2
  exit 1
fi

"${deploy_root}/scripts/preflight.sh" "${environment}" "${target_commit}"
compose build api worker admin-web
compose --profile operations run --rm migrate
compose up -d api worker admin-web
"${deploy_root}/scripts/health-check.sh" "${environment}"

mkdir -p "${deploy_root}/runtime"
printf '%s\t%s\t%s\t%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${environment}" "${target_commit}" "${ci_run_id}" \
  >>"${deploy_root}/runtime/releases.tsv"
echo "release completed; external HTTPS and real-delivery gates remain separate"
