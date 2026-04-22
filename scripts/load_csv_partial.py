"""
Safe wrapper for partial CSV -> PostgreSQL updates.

Usage:
  python scripts/load_csv_partial.py --csv-only gangdong_subs
  python scripts/load_csv_partial.py --csv-only gangdong_subs,gwangjin_subs
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.csv_partial_precheck import build_report

LOAD_SCRIPT = ROOT / "scripts" / "load_csv_to_postgres.py"


def _normalize_csv_only(value: str) -> str:
    items = []
    for raw in (value or "").split(","):
        text = raw.strip()
        if not text:
            continue
        if text.endswith(".csv"):
            text = Path(text).stem
        items.append(text.replace("_db", ""))
    normalized = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return ",".join(normalized)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run safe partial CSV -> PostgreSQL update.")
    parser.add_argument("--csv-only", required=True, help="Comma-separated library codes or CSV basenames")
    args = parser.parse_args()

    csv_only = _normalize_csv_only(args.csv_only)
    if not csv_only:
        raise SystemExit("--csv-only is required")

    report = build_report(csv_only)
    print("[precheck]")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report.get("ok"):
        print("[precheck] blocked: csv validation failed")
        return 2

    env = os.environ.copy()
    env["CSV_ONLY"] = csv_only
    env.pop("MIGRATE_DROP", None)
    env.pop("ALLOW_REMOTE_REBUILD", None)

    cmd = [sys.executable, str(LOAD_SCRIPT)]
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
