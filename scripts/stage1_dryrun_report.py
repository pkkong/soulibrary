"""
Stage1 dry-run report for exact duplicate groups.

Usage:
  python scripts/stage1_dryrun_report.py
  python scripts/stage1_dryrun_report.py --out docs/reports/stage1_dryrun_2026-02-11.json
"""

import argparse
import json
import os
from datetime import datetime

import psycopg2


SUMMARY_SQL = """
WITH dup AS (
  SELECT title_norm, author_norm, publisher_norm, COUNT(*) AS book_count
  FROM books
  GROUP BY title_norm, author_norm, publisher_norm
  HAVING COUNT(*) > 1
),
metrics0 AS (
  SELECT
    d.title_norm,
    d.author_norm,
    d.publisher_norm,
    d.book_count,
    COUNT(h.id) AS holdings_rows,
    COUNT(DISTINCT NULLIF(TRIM(b.isbn), '')) AS book_isbn_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.isbn), '')) AS holdings_isbn_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.brcd), '')) AS brcd_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.goods_id), '')) AS goods_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.content_id), '')) AS content_cnt
  FROM dup d
  JOIN books b
    ON b.title_norm = d.title_norm
   AND b.author_norm = d.author_norm
   AND b.publisher_norm = d.publisher_norm
  LEFT JOIN holdings h ON h.book_id = b.id
  GROUP BY d.title_norm, d.author_norm, d.publisher_norm, d.book_count
),
metrics AS (
  SELECT *,
         (book_isbn_cnt <= 1 AND holdings_isbn_cnt <= 1 AND brcd_cnt <= 1 AND goods_cnt <= 1 AND content_cnt <= 1) AS is_safe
  FROM metrics0
)
SELECT
  COUNT(*) AS total_dup_groups,
  SUM(book_count) AS total_dup_book_rows,
  SUM(CASE WHEN is_safe THEN 1 ELSE 0 END) AS safe_groups,
  SUM(CASE WHEN is_safe THEN book_count ELSE 0 END) AS safe_book_rows,
  SUM(CASE WHEN is_safe THEN 0 ELSE 1 END) AS review_groups,
  SUM(CASE WHEN is_safe THEN 0 ELSE book_count END) AS review_book_rows
FROM metrics
"""


TOP_SQL = """
WITH dup AS (
  SELECT title_norm, author_norm, publisher_norm, COUNT(*) AS book_count
  FROM books
  GROUP BY title_norm, author_norm, publisher_norm
  HAVING COUNT(*) > 1
),
metrics0 AS (
  SELECT
    d.title_norm,
    d.author_norm,
    d.publisher_norm,
    d.book_count,
    COUNT(h.id) AS holdings_rows,
    COUNT(DISTINCT NULLIF(TRIM(b.isbn), '')) AS book_isbn_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.isbn), '')) AS holdings_isbn_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.brcd), '')) AS brcd_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.goods_id), '')) AS goods_cnt,
    COUNT(DISTINCT NULLIF(TRIM(h.content_id), '')) AS content_cnt
  FROM dup d
  JOIN books b
    ON b.title_norm = d.title_norm
   AND b.author_norm = d.author_norm
   AND b.publisher_norm = d.publisher_norm
  LEFT JOIN holdings h ON h.book_id = b.id
  GROUP BY d.title_norm, d.author_norm, d.publisher_norm, d.book_count
),
metrics AS (
  SELECT *,
         (book_isbn_cnt <= 1 AND holdings_isbn_cnt <= 1 AND brcd_cnt <= 1 AND goods_cnt <= 1 AND content_cnt <= 1) AS is_safe
  FROM metrics0
)
SELECT title_norm, author_norm, publisher_norm, book_count, holdings_rows,
       book_isbn_cnt, holdings_isbn_cnt, brcd_cnt, goods_cnt, content_cnt, is_safe
FROM metrics
ORDER BY book_count DESC, holdings_rows DESC
LIMIT %s
"""


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="", help="Optional output JSON path")
    parser.add_argument("--top", type=int, default=20, help="Top N groups to include")
    return parser.parse_args()


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "soulib_test"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "localpass"),
    )


def build_report(conn, top_n):
    cur = conn.cursor()
    cur.execute(SUMMARY_SQL)
    summary_row = cur.fetchone()

    cur.execute(TOP_SQL, (top_n,))
    top_rows = cur.fetchall()
    cur.close()

    return {
        "measured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db": os.getenv("DB_NAME", "soulib_test"),
        "summary": {
            "total_dup_groups": int(summary_row[0] or 0),
            "total_dup_book_rows": int(summary_row[1] or 0),
            "safe_groups": int(summary_row[2] or 0),
            "safe_book_rows": int(summary_row[3] or 0),
            "review_groups": int(summary_row[4] or 0),
            "review_book_rows": int(summary_row[5] or 0),
        },
        "top_groups": [
            {
                "title_norm": row[0],
                "author_norm": row[1],
                "publisher_norm": row[2],
                "book_count": int(row[3] or 0),
                "holdings_rows": int(row[4] or 0),
                "book_isbn_cnt": int(row[5] or 0),
                "holdings_isbn_cnt": int(row[6] or 0),
                "brcd_cnt": int(row[7] or 0),
                "goods_cnt": int(row[8] or 0),
                "content_cnt": int(row[9] or 0),
                "is_safe": bool(row[10]),
            }
            for row in top_rows
        ],
    }


def main():
    args = parse_args()
    conn = connect()
    try:
        report = build_report(conn, args.top)
    finally:
        conn.close()

    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"saved: {args.out}")
    else:
        print(output)


if __name__ == "__main__":
    main()
