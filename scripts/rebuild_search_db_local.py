"""
Explicit local-only full rebuild wrapper for CSV -> PostgreSQL.

Usage:
  python scripts/rebuild_search_db_local.py --yes-rebuild
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOAD_SCRIPT = ROOT / "scripts" / "load_csv_to_postgres.py"
LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run explicit local full rebuild for search DB.")
    parser.add_argument("--yes-rebuild", action="store_true", help="Required confirmation flag")
    args = parser.parse_args()

    if not args.yes_rebuild:
        raise SystemExit("--yes-rebuild is required")

    db_host = os.environ.get("DB_HOST", "localhost").strip().lower()
    if db_host not in LOCAL_DB_HOSTS:
        raise SystemExit(f"Local full rebuild is blocked for non-local DB host: {db_host}")

    env = os.environ.copy()
    env["MIGRATE_DROP"] = "1"
    env.pop("CSV_ONLY", None)

    cmd = [sys.executable, str(LOAD_SCRIPT)]
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
