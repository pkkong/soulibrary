"""
Build guide statistics cache for the /guide page.

Usage:
    python scripts/update_guide_stats.py
    python scripts/update_guide_stats.py --output web/static/data/guide_stats.json
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from config import LIBRARIES  # noqa: E402
from db import get_db, using_postgres  # noqa: E402

DEFAULT_DB = ROOT / "data" / "library_split.db"
LEGACY_DB = ROOT / "data" / "library.db"
DB_PATH = Path(
    os.environ.get(
        "LIBRARY_DB_PATH",
        str(DEFAULT_DB if DEFAULT_DB.exists() else LEGACY_DB),
    )
)


def get_db_conn():
    return get_db(str(DB_PATH))


def _int_value(row, key="count"):
    if row is None:
        return 0
    if isinstance(row, dict):
        value = row.get(key)
        if value is None and row:
            value = next(iter(row.values()))
        return int(value or 0)
    return int(row[0] or 0)


def build_guide_stats():
    if not using_postgres():
        raise RuntimeError("PostgreSQL env vars are required (DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD).")

    conn = get_db_conn()
    try:
        book_row = conn.execute("SELECT COUNT(*) AS count FROM books;").fetchone()
        holdings_row = conn.execute("SELECT COUNT(*) AS count FROM holdings;").fetchone()
        cur = conn.execute(
            "SELECT library, COUNT(*) AS count FROM holdings "
            "WHERE library IS NOT NULL AND library != '' "
            "GROUP BY library;"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    library_counts = [
        {"library": str(r.get("library") or ""), "count": int(r.get("count") or 0)}
        for r in rows
    ]

    library_counts.sort(key=lambda item: item["library"])
    return {
        "library_count": int(len(LIBRARIES)),
        "book_count": _int_value(book_row),
        "holdings_total": _int_value(holdings_row),
        "library_counts": library_counts,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_cache(output_path: Path, stats: dict):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Update guide statistics cache JSON")
    parser.add_argument(
        "--output",
        default=str(ROOT / "web" / "static" / "data" / "guide_stats.json"),
        help="Output JSON path",
    )
    args = parser.parse_args()

    output = Path(args.output)
    started = time.time()
    stats = build_guide_stats()
    write_cache(output, stats)
    elapsed = time.time() - started
    print(
        f"[guide-stats] updated: {output} "
        f"(books={stats['book_count']}, holdings={stats['holdings_total']}, "
        f"libs={len(stats['library_counts'])}, {elapsed:.2f}s)"
    )


if __name__ == "__main__":
    main()
