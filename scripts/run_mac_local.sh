#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d ".venv" ]; then
  echo ".venv is missing. Run: bash scripts/setup_mac.sh"
  exit 1
fi

source .venv/bin/activate

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export LIBRARY_SEARCH_PORT="${LIBRARY_SEARCH_PORT:-5001}"
python web/app_search.py
