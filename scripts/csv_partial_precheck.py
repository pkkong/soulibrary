"""
Precheck CSV files before partial DB apply.

Usage:
  python scripts/csv_partial_precheck.py --csv-only gangdong_subs,gwangjin_subs
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import psycopg2


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from config import LIBRARIES, LIBRARY_SHORT
except ImportError:
    from web.config import LIBRARIES, LIBRARY_SHORT


REQUIRED_COLUMNS = {"title", "author", "publisher", "library"}
RECENT_DROP_RATIO = 0.4
RECENT_JUMP_RATIO = 2.5
SMALL_FILE_ROW_THRESHOLD = 100


def normalize_csv_only(value: str):
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
    return normalized


def resolve_csv_path(lib_code: str) -> Path:
    cfg = LIBRARIES.get(lib_code) or {}
    db_file = cfg.get("db_file")
    if db_file:
        return Path(db_file)
    return ROOT / "data" / f"{lib_code}_db.csv"


def load_db_counts(lib_codes):
    host = os.environ.get("DB_HOST", "localhost")
    port = int(os.environ.get("DB_PORT", "5432"))
    name = os.environ.get("DB_NAME", "postgres")
    user = os.environ.get("DB_USER", "root")
    password = os.environ.get("DB_PASSWORD", "")

    conn = psycopg2.connect(host=host, port=port, dbname=name, user=user, password=password)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT library_code, COUNT(*) AS count
            FROM holdings
            WHERE library_code = ANY(%s)
            GROUP BY library_code
            """,
            (list(lib_codes),),
        )
        return {row[0]: int(row[1]) for row in cur.fetchall() or []}
    finally:
        conn.close()


def inspect_csv(lib_code: str, db_count_map, db_warning=None):
    cfg = LIBRARIES.get(lib_code) or {}
    path = resolve_csv_path(lib_code)
    label = LIBRARY_SHORT.get(lib_code) or cfg.get("name") or lib_code
    item = {
        "code": lib_code,
        "label": label,
        "path": str(path.relative_to(ROOT)).replace("\\", "/") if path.is_absolute() else str(path),
        "row_count": 0,
        "db_holding_count": db_count_map.get(lib_code),
        "blank_title_rows": 0,
        "warnings": [],
        "errors": [],
        "status": "ok",
    }

    if db_warning:
        item["warnings"].append(db_warning)

    if not path.exists():
        item["errors"].append("csv_missing")
        item["status"] = "error"
        return item

    if path.stat().st_size <= 0:
        item["errors"].append("csv_empty")
        item["status"] = "error"
        return item

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - header)
        if missing:
            item["errors"].append(f"missing_columns:{','.join(missing)}")
            item["status"] = "error"
            return item

        row_count = 0
        blank_title_rows = 0
        for row in reader:
            row_count += 1
            if not (row.get("title") or "").strip():
                blank_title_rows += 1

    item["row_count"] = row_count
    item["blank_title_rows"] = blank_title_rows

    if row_count <= 0:
        item["errors"].append("csv_has_no_rows")
    elif blank_title_rows and (blank_title_rows / max(row_count, 1)) >= 0.2:
        item["errors"].append("too_many_blank_titles")
    elif blank_title_rows and (blank_title_rows / max(row_count, 1)) >= 0.05:
        item["warnings"].append("many_blank_titles")

    db_count = item["db_holding_count"]
    if db_count and db_count > 0:
        ratio = row_count / float(db_count)
        item["delta"] = row_count - db_count
        item["delta_ratio"] = round(ratio, 4)
        if row_count < max(SMALL_FILE_ROW_THRESHOLD, int(db_count * RECENT_DROP_RATIO)):
            item["errors"].append("row_count_too_low_vs_db")
        elif row_count > int(db_count * RECENT_JUMP_RATIO):
            item["errors"].append("row_count_too_high_vs_db")
        elif ratio < 0.9 or ratio > 1.1:
            item["warnings"].append("row_count_diff_vs_db")

    if item["errors"]:
        item["status"] = "error"
    elif item["warnings"]:
        item["status"] = "warning"
    return item


def build_report(csv_only: str):
    lib_codes = normalize_csv_only(csv_only)
    if not lib_codes:
        raise ValueError("--csv-only is required")

    db_count_map = {}
    db_warning = None
    try:
        db_count_map = load_db_counts(lib_codes)
    except Exception as exc:
        db_warning = f"db_baseline_unavailable:{exc.__class__.__name__}"

    items = [inspect_csv(lib_code, db_count_map, db_warning=db_warning) for lib_code in lib_codes]
    error_count = sum(1 for item in items if item["status"] == "error")
    warning_count = sum(1 for item in items if item["status"] == "warning")

    return {
        "ok": error_count == 0,
        "csv_only": ",".join(lib_codes),
        "checked_count": len(items),
        "error_count": error_count,
        "warning_count": warning_count,
        "items": items,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check CSV files before partial DB apply.")
    parser.add_argument("--csv-only", required=True, help="Comma-separated library codes or CSV basenames")
    args = parser.parse_args()

    report = build_report(args.csv_only)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
