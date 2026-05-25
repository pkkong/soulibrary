#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Soulib Mac setup"
echo "repo: $ROOT_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "Git is not installed. Run: xcode-select --install"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Install Python 3.11 or newer, then run this again."
  exit 1
fi

PYTHON_VERSION="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
echo "python: $PYTHON_VERSION"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data

if [ ! -f ".env" ]; then
  cp .env.example .env
  {
    echo ""
    echo "# Local Mac defaults"
    echo "LIBRARY_SEARCH_PORT=5001"
    echo "SHARED_SHELVES_STORAGE=json"
    echo "SHARED_SHELVES_FILE=$ROOT_DIR/data/shared_shelves.local.json"
  } >> .env
  echo "created .env from .env.example"
fi

python scripts/smoke_test.py

cat <<'MSG'

Mac setup complete.

Run the local server:

  bash scripts/run_mac_local.sh

Open:

  http://127.0.0.1:5001

MSG
