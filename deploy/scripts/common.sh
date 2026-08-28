#!/usr/bin/env bash
set -euo pipefail

deploy_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repository_root=$(cd "${deploy_root}/.." && pwd)

resolve_environment() {
  case "${1:-}" in
    shared-test)
      compose_file="${deploy_root}/compose.shared-test.yaml"
      environment_file="${deploy_root}/.env.shared-test"
      ;;
    production)
      compose_file="${deploy_root}/compose.production.yaml"
      environment_file="${deploy_root}/.env.production"
      ;;
    *)
      echo "environment must be shared-test or production" >&2
      exit 2
      ;;
  esac
  if [[ ! -f "${environment_file}" ]]; then
    echo "missing protected environment file: ${environment_file}" >&2
    exit 2
  fi
}

compose() {
  docker compose --env-file "${environment_file}" -f "${compose_file}" "$@"
}
