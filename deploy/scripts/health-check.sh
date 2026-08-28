#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

environment=${1:-}
resolve_environment "${environment}"

compose ps
compose exec -T api python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).read()"
compose exec -T api python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()"
compose exec -T admin-web wget -qO- http://127.0.0.1/healthz >/dev/null
echo "internal container health checks passed for ${environment}"
