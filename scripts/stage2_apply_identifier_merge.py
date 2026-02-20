"""
Stage2 identifier-based canonical merge.

What it does:
1) Fill holdings.canonical_id from strong identifiers (goods_id/brcd/content_id namespace rules).
2) Reassign holdings.book_id by canonical representative.
3) Refresh books.canonical_id / books.merge_group_id.
4) Delete orphan books (without holdings).
5) Optionally dedupe holdings duplicates per (book_id, library_code).

Usage:
  python scripts/stage2_apply_identifier_merge.py
  python scripts/stage2_apply_identifier_merge.py --apply --dedupe-holdings
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime

import psycopg2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply destructive changes")
    parser.add_argument(
        "--dedupe-holdings",
        action="store_true",
        help="Delete duplicate holdings rows per (book_id, library_code) after remap",
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


def build_candidates(cur):
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_candidates")
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_effective")
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_rep")
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_book_map")
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_holdings_dups")

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage2_candidates AS
        WITH h AS (
          SELECT
            id AS holding_id,
            book_id,
            library_code,
            platform,
            NULLIF(TRIM(canonical_id), '') AS canonical_id,
            NULLIF(TRIM(brcd), '') AS brcd,
            NULLIF(TRIM(goods_id), '') AS goods_id,
            NULLIF(TRIM(content_id), '') AS content_id
          FROM holdings
        ),
        x_goods AS (
          SELECT DISTINCT NULLIF(TRIM(goods_id), '') AS goods_id
          FROM holdings
          WHERE NULLIF(TRIM(goods_id), '') IS NOT NULL
        ),
        x_brcd AS (
          SELECT DISTINCT NULLIF(TRIM(brcd), '') AS brcd
          FROM holdings
          WHERE NULLIF(TRIM(brcd), '') IS NOT NULL
        )
        SELECT
          h.holding_id,
          h.book_id,
          h.canonical_id AS canonical_old,
          CASE
            WHEN h.canonical_id IS NOT NULL THEN h.canonical_id
            WHEN h.goods_id IS NOT NULL THEN 'yes24:' || h.goods_id
            WHEN h.brcd IS NOT NULL THEN 'kyobo:' || h.brcd
            WHEN h.content_id IS NOT NULL AND xg.goods_id IS NOT NULL THEN 'yes24:' || h.content_id
            WHEN h.content_id IS NOT NULL AND xb.brcd IS NOT NULL THEN 'kyobo:' || h.content_id
            WHEN h.content_id IS NOT NULL AND h.platform ILIKE 'Bookcube%' THEN 'bookcube:' || h.content_id
            WHEN h.content_id IS NOT NULL AND h.library_code = 'seoul' THEN 'seoul:' || h.content_id
            WHEN h.content_id IS NOT NULL AND h.library_code IN ('sen_owned', 'sen_subs') THEN 'sen:' || h.content_id
            WHEN h.content_id IS NOT NULL AND h.library_code = 'gangnam' THEN 'gangnam:' || h.content_id
            WHEN h.content_id IS NOT NULL AND h.library_code = 'eunpyeong' THEN 'eunpyeong:' || h.content_id
            WHEN h.content_id IS NOT NULL THEN 'content:' || COALESCE(h.library_code, 'unknown') || ':' || h.content_id
            ELSE NULL
          END AS canonical_new,
          CASE
            WHEN h.canonical_id IS NOT NULL THEN 'keep_existing'
            WHEN h.goods_id IS NOT NULL THEN 'from_goods_id'
            WHEN h.brcd IS NOT NULL THEN 'from_brcd'
            WHEN h.content_id IS NOT NULL AND xg.goods_id IS NOT NULL THEN 'content_to_goods_crosswalk'
            WHEN h.content_id IS NOT NULL AND xb.brcd IS NOT NULL THEN 'content_to_brcd_crosswalk'
            WHEN h.content_id IS NOT NULL AND h.platform ILIKE 'Bookcube%' THEN 'content_bookcube_namespace'
            WHEN h.content_id IS NOT NULL AND h.library_code = 'seoul' THEN 'content_seoul_namespace'
            WHEN h.content_id IS NOT NULL AND h.library_code IN ('sen_owned', 'sen_subs') THEN 'content_sen_namespace'
            WHEN h.content_id IS NOT NULL AND h.library_code = 'gangnam' THEN 'content_gangnam_namespace'
            WHEN h.content_id IS NOT NULL AND h.library_code = 'eunpyeong' THEN 'content_eunpyeong_namespace'
            WHEN h.content_id IS NOT NULL THEN 'content_library_namespace'
            ELSE 'no_identifier'
          END AS rule_name
        FROM h
        LEFT JOIN x_goods xg ON xg.goods_id = h.content_id
        LEFT JOIN x_brcd xb ON xb.brcd = h.content_id
        """
    )


def build_effective_and_maps(cur):
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_effective")
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_rep")
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_book_map")

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage2_effective AS
        SELECT
          c.holding_id,
          c.book_id,
          c.rule_name,
          CASE
            WHEN c.canonical_old IS NOT NULL THEN c.canonical_old
            ELSE c.canonical_new
          END AS canonical_eff
        FROM tmp_stage2_candidates c
        """
    )

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage2_rep AS
        WITH stats AS (
          SELECT
            canonical_eff AS canonical_id,
            book_id,
            COUNT(*) AS rows,
            ROW_NUMBER() OVER (
              PARTITION BY canonical_eff
              ORDER BY COUNT(*) DESC, book_id ASC
            ) AS rn
          FROM tmp_stage2_effective
          WHERE canonical_eff IS NOT NULL AND canonical_eff <> ''
          GROUP BY canonical_eff, book_id
        )
        SELECT canonical_id, book_id AS rep_book_id
        FROM stats
        WHERE rn = 1
        """
    )

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage2_book_map AS
        SELECT
          e.canonical_eff AS canonical_id,
          e.book_id AS old_book_id,
          r.rep_book_id
        FROM tmp_stage2_effective e
        JOIN tmp_stage2_rep r
          ON r.canonical_id = e.canonical_eff
        WHERE e.canonical_eff IS NOT NULL
          AND e.canonical_eff <> ''
          AND e.book_id <> r.rep_book_id
        GROUP BY e.canonical_eff, e.book_id, r.rep_book_id
        """
    )


def summarize(cur):
    cur.execute(
        """
        SELECT
          COUNT(*) AS total_holdings,
          COUNT(*) FILTER (WHERE canonical_old IS NULL) AS canonical_missing_before,
          COUNT(*) FILTER (WHERE canonical_old IS NULL AND canonical_new IS NOT NULL) AS fillable_rows
        FROM tmp_stage2_candidates
        """
    )
    a = cur.fetchone()

    cur.execute(
        """
        SELECT rule_name, COUNT(*)
        FROM tmp_stage2_candidates
        GROUP BY rule_name
        ORDER BY COUNT(*) DESC, rule_name
        """
    )
    rules = {name: int(cnt) for name, cnt in cur.fetchall()}

    cur.execute(
        """
        SELECT
          COUNT(*) AS map_rows,
          COUNT(DISTINCT canonical_id) AS canonical_multi_book_groups
        FROM tmp_stage2_book_map
        """
    )
    b = cur.fetchone()

    cur.execute(
        """
        SELECT COUNT(*)
        FROM holdings h
        JOIN tmp_stage2_book_map m
          ON m.canonical_id = NULLIF(TRIM(h.canonical_id), '')
         AND m.old_book_id = h.book_id
        """
    )
    reassign_existing = int(cur.fetchone()[0] or 0)

    cur.execute(
        """
        SELECT COUNT(*)
        FROM tmp_stage2_effective e
        JOIN tmp_stage2_book_map m
          ON m.canonical_id = e.canonical_eff
         AND m.old_book_id = e.book_id
        """
    )
    reassign_effective = int(cur.fetchone()[0] or 0)

    return {
        "total_holdings": int(a[0] or 0),
        "canonical_missing_before": int(a[1] or 0),
        "fillable_rows": int(a[2] or 0),
        "rule_counts": rules,
        "book_map_rows": int(b[0] or 0),
        "canonical_multi_book_groups": int(b[1] or 0),
        "holdings_to_reassign_existing_canonical": reassign_existing,
        "holdings_to_reassign_effective": reassign_effective,
    }


def apply_fill_canonical(cur):
    cur.execute(
        """
        UPDATE holdings h
        SET canonical_id = c.canonical_new
        FROM tmp_stage2_candidates c
        WHERE h.id = c.holding_id
          AND NULLIF(TRIM(h.canonical_id), '') IS NULL
          AND c.canonical_new IS NOT NULL
        """
    )
    return cur.rowcount


def apply_reassign_by_canonical(cur):
    # Recompute maps using actual current holdings canonical values.
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_rep")
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_book_map")

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage2_rep AS
        WITH stats AS (
          SELECT
            NULLIF(TRIM(canonical_id), '') AS canonical_id,
            book_id,
            COUNT(*) AS rows,
            ROW_NUMBER() OVER (
              PARTITION BY NULLIF(TRIM(canonical_id), '')
              ORDER BY COUNT(*) DESC, book_id ASC
            ) AS rn
          FROM holdings
          WHERE NULLIF(TRIM(canonical_id), '') IS NOT NULL
          GROUP BY NULLIF(TRIM(canonical_id), ''), book_id
        )
        SELECT canonical_id, book_id AS rep_book_id
        FROM stats
        WHERE rn = 1
        """
    )

    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage2_book_map AS
        SELECT
          NULLIF(TRIM(h.canonical_id), '') AS canonical_id,
          h.book_id AS old_book_id,
          r.rep_book_id
        FROM holdings h
        JOIN tmp_stage2_rep r
          ON r.canonical_id = NULLIF(TRIM(h.canonical_id), '')
        WHERE NULLIF(TRIM(h.canonical_id), '') IS NOT NULL
          AND h.book_id <> r.rep_book_id
        GROUP BY NULLIF(TRIM(h.canonical_id), ''), h.book_id, r.rep_book_id
        """
    )

    cur.execute(
        """
        UPDATE holdings h
        SET book_id = m.rep_book_id
        FROM tmp_stage2_book_map m
        WHERE NULLIF(TRIM(h.canonical_id), '') = m.canonical_id
          AND h.book_id = m.old_book_id
        """
    )
    return cur.rowcount


def refresh_books(cur):
    # Reset books canonical before deterministic rebuild.
    cur.execute("UPDATE books SET canonical_id = NULL")

    cur.execute(
        """
        WITH one_canon AS (
          SELECT
            book_id,
            MIN(NULLIF(TRIM(canonical_id), '')) AS canonical_id
          FROM holdings
          WHERE NULLIF(TRIM(canonical_id), '') IS NOT NULL
          GROUP BY book_id
          HAVING COUNT(DISTINCT NULLIF(TRIM(canonical_id), '')) = 1
        )
        UPDATE books b
        SET canonical_id = o.canonical_id
        FROM one_canon o
        WHERE b.id = o.book_id
        """
    )
    books_single = cur.rowcount

    cur.execute(
        """
        UPDATE books
        SET merge_group_id = canonical_id
        WHERE canonical_id IS NOT NULL AND canonical_id <> ''
        """
    )
    merge_updated = cur.rowcount
    return books_single, merge_updated


def delete_orphan_books(cur):
    cur.execute(
        """
        DELETE FROM books b
        WHERE NOT EXISTS (
          SELECT 1
          FROM holdings h
          WHERE h.book_id = b.id
        )
        """
    )
    return cur.rowcount


def dedupe_holdings(cur):
    cur.execute("DROP TABLE IF EXISTS tmp_stage2_holdings_dups")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage2_holdings_dups AS
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
    cur.execute("SELECT COUNT(*) FROM tmp_stage2_holdings_dups")
    target = int(cur.fetchone()[0] or 0)
    if target == 0:
        return 0
    cur.execute(
        """
        DELETE FROM holdings h
        USING tmp_stage2_holdings_dups d
        WHERE h.id = d.id
        """
    )
    return cur.rowcount


def postcheck(cur):
    cur.execute(
        """
        SELECT
          COUNT(*) AS holdings_total,
          COUNT(*) FILTER (WHERE NULLIF(TRIM(canonical_id), '') IS NULL) AS holdings_no_canonical,
          COUNT(*) FILTER (WHERE NULLIF(TRIM(brcd), '') IS NOT NULL AND NULLIF(TRIM(canonical_id), '') IS NULL) AS brcd_no_canonical,
          COUNT(*) FILTER (WHERE NULLIF(TRIM(goods_id), '') IS NOT NULL AND NULLIF(TRIM(canonical_id), '') IS NULL) AS goods_no_canonical,
          COUNT(*) FILTER (WHERE NULLIF(TRIM(content_id), '') IS NOT NULL AND NULLIF(TRIM(canonical_id), '') IS NULL) AS content_no_canonical
        FROM holdings
        """
    )
    a = cur.fetchone()

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
    dup_holdings = int(cur.fetchone()[0] or 0)

    cur.execute(
        """
        SELECT COUNT(*)
        FROM (
          SELECT canonical_id
          FROM holdings
          WHERE NULLIF(TRIM(canonical_id), '') IS NOT NULL
          GROUP BY canonical_id
          HAVING COUNT(DISTINCT book_id) > 1
        ) t
        """
    )
    canon_multi_book = int(cur.fetchone()[0] or 0)

    cur.execute("SELECT COUNT(*) FROM books")
    books_total = int(cur.fetchone()[0] or 0)

    return {
        "books_total": books_total,
        "holdings_total": int(a[0] or 0),
        "holdings_no_canonical": int(a[1] or 0),
        "brcd_no_canonical": int(a[2] or 0),
        "goods_no_canonical": int(a[3] or 0),
        "content_no_canonical": int(a[4] or 0),
        "holdings_book_library_dup_groups": dup_holdings,
        "canonical_multi_book_groups_after": canon_multi_book,
    }


def main():
    args = parse_args()
    conn = connect()
    conn.autocommit = False

    payload = {
        "measured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db": os.getenv("DB_NAME", "soulib_test"),
        "mode": "apply" if args.apply else "dry-run",
        "dedupe_holdings": bool(args.dedupe_holdings),
    }

    try:
        cur = conn.cursor()
        build_candidates(cur)
        build_effective_and_maps(cur)
        payload["precheck"] = summarize(cur)

        if not args.apply:
            conn.rollback()
            cur.close()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        filled = apply_fill_canonical(cur)
        reassigned = apply_reassign_by_canonical(cur)
        books_single, merge_updated = refresh_books(cur)
        orphan_deleted = delete_orphan_books(cur)
        holdings_deleted = 0
        if args.dedupe_holdings:
            holdings_deleted = dedupe_holdings(cur)

        payload["applied"] = {
            "holdings_canonical_filled": int(filled),
            "holdings_reassigned_by_canonical": int(reassigned),
            "books_single_canonical_set": int(books_single),
            "books_merge_group_refreshed": int(merge_updated),
            "orphan_books_deleted": int(orphan_deleted),
            "holdings_deleted_by_book_library_dedupe": int(holdings_deleted),
        }

        payload["postcheck"] = postcheck(cur)

        conn.commit()
        cur.close()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
