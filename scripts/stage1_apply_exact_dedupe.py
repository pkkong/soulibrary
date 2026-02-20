"""
Stage1 exact dedupe executor.

Purpose:
- Merge duplicate books that share exact (title_norm, author_norm, publisher_norm).
- Reassign holdings to a deterministic representative book_id.
- Optionally dedupe duplicate holdings rows per (book_id, library_code).
- Optionally add unique lock on books norm key.

Usage:
  python scripts/stage1_apply_exact_dedupe.py --dry-run
  python scripts/stage1_apply_exact_dedupe.py --apply --scope safe
  python scripts/stage1_apply_exact_dedupe.py --apply --scope all --add-unique
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

import psycopg2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply changes")
    parser.add_argument(
        "--scope",
        choices=["safe", "all"],
        default="all",
        help="Target groups: safe-only or all exact duplicate groups",
    )
    parser.add_argument(
        "--dedupe-holdings",
        action="store_true",
        help="Delete duplicate holdings rows per (book_id, library_code), keep best row",
    )
    parser.add_argument(
        "--add-unique",
        action="store_true",
        help="Add unique index/constraint on books(title_norm, author_norm, publisher_norm)",
    )
    return parser.parse_args()


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "soulib_test"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "localpass"),
    )


def _build_temp_tables(cur, scope: str):
    cur.execute("DROP TABLE IF EXISTS tmp_stage1_group_metrics")
    cur.execute("DROP TABLE IF EXISTS tmp_stage1_groups")
    cur.execute("DROP TABLE IF EXISTS tmp_stage1_rep")
    cur.execute("DROP TABLE IF EXISTS tmp_stage1_map")
    cur.execute("DROP TABLE IF EXISTS tmp_stage1_holdings_dups")

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage1_group_metrics AS
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
        )
        SELECT *,
               (book_isbn_cnt <= 1
                AND holdings_isbn_cnt <= 1
                AND brcd_cnt <= 1
                AND goods_cnt <= 1
                AND content_cnt <= 1) AS is_safe
        FROM metrics0
        """
    )

    if scope == "safe":
        cur.execute(
            """
            CREATE TEMP TABLE tmp_stage1_groups AS
            SELECT *
            FROM tmp_stage1_group_metrics
            WHERE is_safe
            """
        )
    else:
        cur.execute(
            """
            CREATE TEMP TABLE tmp_stage1_groups AS
            SELECT *
            FROM tmp_stage1_group_metrics
            """
        )

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage1_rep AS
        WITH scored AS (
          SELECT
            b.id,
            b.title_norm,
            b.author_norm,
            b.publisher_norm,
            COUNT(h.id) AS holdings_rows,
            MAX(CASE WHEN NULLIF(TRIM(b.isbn), '') IS NOT NULL OR NULLIF(TRIM(h.isbn), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_isbn,
            MAX(CASE WHEN NULLIF(TRIM(h.brcd), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_brcd,
            MAX(CASE WHEN NULLIF(TRIM(h.goods_id), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_goods_id,
            MAX(CASE WHEN NULLIF(TRIM(h.content_id), '') IS NOT NULL THEN 1 ELSE 0 END) AS has_content_id
          FROM books b
          JOIN tmp_stage1_groups g
            ON g.title_norm = b.title_norm
           AND g.author_norm = b.author_norm
           AND g.publisher_norm = b.publisher_norm
          LEFT JOIN holdings h ON h.book_id = b.id
          GROUP BY b.id, b.title_norm, b.author_norm, b.publisher_norm
        ),
        ranked AS (
          SELECT
            *,
            (has_isbn + has_brcd + has_goods_id + has_content_id) AS id_signal,
            ROW_NUMBER() OVER (
              PARTITION BY title_norm, author_norm, publisher_norm
              ORDER BY holdings_rows DESC,
                       (has_isbn + has_brcd + has_goods_id + has_content_id) DESC,
                       id ASC
            ) AS rn
          FROM scored
        )
        SELECT
          title_norm,
          author_norm,
          publisher_norm,
          id AS rep_book_id
        FROM ranked
        WHERE rn = 1
        """
    )

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage1_map AS
        SELECT
          b.id AS old_book_id,
          r.rep_book_id
        FROM books b
        JOIN tmp_stage1_rep r
          ON r.title_norm = b.title_norm
         AND r.author_norm = b.author_norm
         AND r.publisher_norm = b.publisher_norm
        WHERE b.id <> r.rep_book_id
        """
    )


def _collect_summary(cur, scope: str):
    cur.execute(
        """
        SELECT
          COUNT(*) AS total_groups,
          SUM(book_count) AS total_group_rows,
          SUM(CASE WHEN is_safe THEN 1 ELSE 0 END) AS safe_groups,
          SUM(CASE WHEN is_safe THEN book_count ELSE 0 END) AS safe_rows,
          SUM(CASE WHEN is_safe THEN 0 ELSE 1 END) AS review_groups,
          SUM(CASE WHEN is_safe THEN 0 ELSE book_count END) AS review_rows
        FROM tmp_stage1_group_metrics
        """
    )
    r = cur.fetchone()
    summary = {
        "scope": scope,
        "total_groups": int(r[0] or 0),
        "total_group_rows": int(r[1] or 0),
        "safe_groups": int(r[2] or 0),
        "safe_rows": int(r[3] or 0),
        "review_groups": int(r[4] or 0),
        "review_rows": int(r[5] or 0),
    }

    cur.execute("SELECT COUNT(*) FROM tmp_stage1_groups")
    summary["target_groups"] = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COALESCE(SUM(book_count), 0) FROM tmp_stage1_groups")
    summary["target_group_rows"] = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM tmp_stage1_map")
    summary["books_to_merge"] = int(cur.fetchone()[0] or 0)

    cur.execute(
        """
        SELECT COUNT(*)
        FROM holdings h
        JOIN tmp_stage1_map m ON m.old_book_id = h.book_id
        """
    )
    summary["holdings_to_reassign"] = int(cur.fetchone()[0] or 0)

    return summary


def _apply_merge(cur):
    cur.execute(
        """
        UPDATE holdings h
        SET book_id = m.rep_book_id
        FROM tmp_stage1_map m
        WHERE h.book_id = m.old_book_id
        """
    )
    holdings_updated = cur.rowcount

    cur.execute(
        """
        DELETE FROM books b
        USING tmp_stage1_map m
        WHERE b.id = m.old_book_id
        """
    )
    books_deleted = cur.rowcount
    return holdings_updated, books_deleted


def _apply_holdings_dedupe(cur):
    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage1_holdings_dups AS
        WITH ranked AS (
          SELECT
            h.id,
            ROW_NUMBER() OVER (
              PARTITION BY h.book_id, COALESCE(h.library_code, '')
              ORDER BY
                (CASE WHEN NULLIF(TRIM(h.content_id), '') IS NOT NULL THEN 2 ELSE 0 END
                 + CASE WHEN NULLIF(TRIM(h.goods_id), '') IS NOT NULL THEN 2 ELSE 0 END
                 + CASE WHEN NULLIF(TRIM(h.brcd), '') IS NOT NULL THEN 2 ELSE 0 END
                 + CASE WHEN NULLIF(TRIM(h.ctts_dvsn_code), '') IS NOT NULL THEN 1 ELSE 0 END
                 + CASE WHEN NULLIF(TRIM(h.ctgr_id), '') IS NOT NULL THEN 1 ELSE 0 END
                 + CASE WHEN NULLIF(TRIM(h.sntn_auth_code), '') IS NOT NULL THEN 1 ELSE 0 END
                 + CASE WHEN NULLIF(TRIM(h.isbn), '') IS NOT NULL THEN 1 ELSE 0 END
                 + CASE WHEN NULLIF(TRIM(h.image_url), '') IS NOT NULL THEN 1 ELSE 0 END
                ) DESC,
                h.id ASC
            ) AS rn
          FROM holdings h
        )
        SELECT id
        FROM ranked
        WHERE rn > 1
        """
    )
    cur.execute("SELECT COUNT(*) FROM tmp_stage1_holdings_dups")
    target = int(cur.fetchone()[0] or 0)
    if target == 0:
        return 0

    cur.execute(
        """
        DELETE FROM holdings h
        USING tmp_stage1_holdings_dups d
        WHERE h.id = d.id
        """
    )
    return cur.rowcount


def _add_unique_lock(conn):
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_books_norm_idx
            ON books (title_norm, author_norm, publisher_norm)
            """
        )
        cur.execute(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_books_norm'
                  AND conrelid = 'books'::regclass
              ) THEN
                ALTER TABLE books
                ADD CONSTRAINT uq_books_norm UNIQUE USING INDEX uq_books_norm_idx;
              END IF;
            END
            $$;
            """
        )
    finally:
        cur.close()
        conn.autocommit = False


def _post_metrics(cur):
    cur.execute(
        """
        SELECT COUNT(*)
        FROM (
          SELECT 1
          FROM books
          GROUP BY title_norm, author_norm, publisher_norm
          HAVING COUNT(*) > 1
        ) t
        """
    )
    books_dup_groups = int(cur.fetchone()[0] or 0)

    cur.execute(
        """
        SELECT COUNT(*)
        FROM (
          SELECT 1
          FROM holdings
          GROUP BY book_id, library_code
          HAVING COUNT(*) > 1
        ) t
        """
    )
    holdings_dup_groups = int(cur.fetchone()[0] or 0)

    return {
        "books_exact_dup_groups_after": books_dup_groups,
        "holdings_book_library_dup_groups_after": holdings_dup_groups,
    }


def main():
    args = parse_args()
    conn = connect()
    conn.autocommit = False

    payload = {
        "measured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db": os.getenv("DB_NAME", "soulib_test"),
        "mode": "apply" if args.apply else "dry-run",
        "scope": args.scope,
        "dedupe_holdings": bool(args.dedupe_holdings),
        "add_unique": bool(args.add_unique),
    }

    try:
        cur = conn.cursor()
        _build_temp_tables(cur, args.scope)
        payload["precheck"] = _collect_summary(cur, args.scope)

        if not args.apply:
            conn.rollback()
            cur.close()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        holdings_updated, books_deleted = _apply_merge(cur)
        payload["applied"] = {
            "holdings_reassigned": int(holdings_updated),
            "books_deleted": int(books_deleted),
        }

        if args.dedupe_holdings:
            holdings_deleted = _apply_holdings_dedupe(cur)
            payload["applied"]["holdings_deleted_by_book_library_dedupe"] = int(
                holdings_deleted
            )

        conn.commit()
        cur.close()

        if args.add_unique:
            _add_unique_lock(conn)

        cur = conn.cursor()
        payload["postcheck"] = _post_metrics(cur)
        cur.close()
        conn.commit()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
