"""
Stage3 apply script: apply only admin-approved review queue pairs.

Purpose:
- Read approved rows from merge_review_queue.
- Merge connected components into representative book_id.
- Reassign holdings, delete merged books, optional holdings dedupe.
- Mark queue rows as applied.

Usage:
  python scripts/stage3_apply_approved.py
  python scripts/stage3_apply_approved.py --apply --dedupe-holdings
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply destructive changes")
    parser.add_argument(
        "--dedupe-holdings",
        action="store_true",
        help="Delete duplicate holdings rows per (book_id, library_code) after merge",
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


def ensure_review_tables(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_review_queue (
          id BIGSERIAL PRIMARY KEY,
          pair_left_book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          pair_right_book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
          source TEXT NOT NULL DEFAULT 'rule_auto',
          title_score INTEGER NOT NULL DEFAULT 0,
          author_score INTEGER NOT NULL DEFAULT 0,
          publisher_score INTEGER NOT NULL DEFAULT 0,
          signal_score INTEGER NOT NULL DEFAULT 0,
          total_score INTEGER NOT NULL DEFAULT 0,
          risk_flags TEXT NOT NULL DEFAULT '',
          reason TEXT,
          status TEXT NOT NULL DEFAULT 'new',
          decision_note TEXT,
          decided_by TEXT,
          decided_at TIMESTAMP,
          applied_at TIMESTAMP,
          created_at TIMESTAMP NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
          last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
          CONSTRAINT ck_merge_review_pair_order CHECK (pair_left_book_id < pair_right_book_id),
          CONSTRAINT uq_merge_review_pair UNIQUE (pair_left_book_id, pair_right_book_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_review_log (
          id BIGSERIAL PRIMARY KEY,
          queue_id BIGINT REFERENCES merge_review_queue(id) ON DELETE CASCADE,
          action TEXT NOT NULL,
          actor TEXT NOT NULL DEFAULT 'system',
          note TEXT,
          payload JSONB,
          created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )


class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}

    def add(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0

    def find(self, x):
        p = self.parent[x]
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a, b):
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1


def fetch_approved_pairs(cur):
    cur.execute(
        """
        SELECT
          q.id,
          q.pair_left_book_id,
          q.pair_right_book_id
        FROM merge_review_queue q
        JOIN books b1 ON b1.id = q.pair_left_book_id
        JOIN books b2 ON b2.id = q.pair_right_book_id
        WHERE q.status = 'approved'
        ORDER BY q.id ASC
        """
    )
    rows = []
    for r in cur.fetchall():
        rows.append((int(r[0]), int(r[1]), int(r[2])))
    return rows


def build_components(pairs):
    uf = UnionFind()
    queue_ids = []
    for qid, left_id, right_id in pairs:
        uf.add(left_id)
        uf.add(right_id)
        uf.union(left_id, right_id)
        queue_ids.append(qid)

    groups = defaultdict(list)
    for book_id in uf.parent.keys():
        root = uf.find(book_id)
        groups[root].append(book_id)
    components = [sorted(v) for v in groups.values() if len(v) > 1]
    return components, queue_ids


def fetch_holdings_counts(cur, book_ids):
    if not book_ids:
        return {}
    cur.execute(
        """
        SELECT b.id, COUNT(h.id) AS holdings_count
        FROM books b
        LEFT JOIN holdings h ON h.book_id = b.id
        WHERE b.id = ANY(%s)
        GROUP BY b.id
        """,
        (list(book_ids),),
    )
    out = {}
    for r in cur.fetchall():
        out[int(r[0])] = int(r[1] or 0)
    return out


def choose_mapping(components, holdings_counts):
    mapping = {}
    reps = []
    for comp in components:
        ranked = sorted(
            comp,
            key=lambda bid: (-(holdings_counts.get(bid, 0)), bid),
        )
        rep = ranked[0]
        reps.append(rep)
        for old in ranked[1:]:
            mapping[old] = rep
    return mapping, sorted(set(reps))


def precheck(cur, mapping):
    old_ids = sorted(mapping.keys())
    if not old_ids:
        return 0
    cur.execute("SELECT COUNT(*) FROM holdings WHERE book_id = ANY(%s)", (old_ids,))
    return int(cur.fetchone()[0] or 0)


def apply_mapping(cur, mapping):
    if not mapping:
        return 0, 0
    cur.execute("DROP TABLE IF EXISTS tmp_stage3_map")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage3_map (
          old_book_id INTEGER PRIMARY KEY,
          rep_book_id INTEGER NOT NULL
        )
        """
    )
    pairs = [(old_id, rep_id) for old_id, rep_id in mapping.items()]
    execute_values(
        cur,
        "INSERT INTO tmp_stage3_map (old_book_id, rep_book_id) VALUES %s",
        pairs,
        page_size=1000,
    )

    cur.execute(
        """
        UPDATE holdings h
        SET book_id = m.rep_book_id
        FROM tmp_stage3_map m
        WHERE h.book_id = m.old_book_id
        """
    )
    holdings_updated = cur.rowcount

    cur.execute(
        """
        DELETE FROM books b
        USING tmp_stage3_map m
        WHERE b.id = m.old_book_id
        """
    )
    books_deleted = cur.rowcount
    return holdings_updated, books_deleted


def dedupe_holdings(cur):
    cur.execute("DROP TABLE IF EXISTS tmp_stage3_holdings_dups")
    cur.execute(
        """
        CREATE TEMP TABLE tmp_stage3_holdings_dups AS
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
    cur.execute("SELECT COUNT(*) FROM tmp_stage3_holdings_dups")
    target = int(cur.fetchone()[0] or 0)
    if target == 0:
        return 0
    cur.execute(
        """
        DELETE FROM holdings h
        USING tmp_stage3_holdings_dups d
        WHERE h.id = d.id
        """
    )
    return cur.rowcount


def refresh_representatives(cur, rep_ids):
    if not rep_ids:
        return 0
    cur.execute(
        """
        UPDATE books
        SET canonical_id = NULL
        WHERE id = ANY(%s)
        """,
        (rep_ids,),
    )

    cur.execute(
        """
        WITH one_canon AS (
          SELECT
            h.book_id,
            MIN(NULLIF(TRIM(h.canonical_id), '')) AS canonical_id
          FROM holdings h
          WHERE h.book_id = ANY(%s)
            AND NULLIF(TRIM(h.canonical_id), '') IS NOT NULL
          GROUP BY h.book_id
          HAVING COUNT(DISTINCT NULLIF(TRIM(h.canonical_id), '')) = 1
        )
        UPDATE books b
        SET canonical_id = o.canonical_id
        FROM one_canon o
        WHERE b.id = o.book_id
        """,
        (rep_ids,),
    )

    cur.execute(
        """
        UPDATE books
        SET merge_group_id = COALESCE(canonical_id, 'stage3:' || id::TEXT)
        WHERE id = ANY(%s)
        """,
        (rep_ids,),
    )
    return cur.rowcount


def mark_applied(cur, queue_ids, mapping):
    if not queue_ids:
        return 0
    cur.execute(
        """
        UPDATE merge_review_queue
        SET status = 'applied',
            applied_at = NOW(),
            updated_at = NOW()
        WHERE id = ANY(%s)
          AND status = 'approved'
        """,
        (queue_ids,),
    )
    updated = cur.rowcount
    payload = json.dumps(
        {
            "queue_ids": queue_ids,
            "mapping_size": len(mapping),
        },
        ensure_ascii=False,
    )
    cur.execute(
        """
        INSERT INTO merge_review_log (queue_id, action, actor, note, payload)
        SELECT id, 'applied', 'system', 'stage3 approved apply', %s::jsonb
        FROM merge_review_queue
        WHERE id = ANY(%s)
        """,
        (payload, queue_ids),
    )
    return updated


def postcheck(cur):
    cur.execute("SELECT COUNT(*) FROM books")
    books_total = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM holdings")
    holdings_total = int(cur.fetchone()[0] or 0)
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
    holdings_dup = int(cur.fetchone()[0] or 0)
    cur.execute(
        """
        SELECT COUNT(*)
        FROM books b
        WHERE NOT EXISTS (SELECT 1 FROM holdings h WHERE h.book_id = b.id)
        """
    )
    orphan = int(cur.fetchone()[0] or 0)
    return {
        "books_total": books_total,
        "holdings_total": holdings_total,
        "holdings_book_library_dup_groups": holdings_dup,
        "orphan_books": orphan,
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
        ensure_review_tables(cur)
        pairs = fetch_approved_pairs(cur)
        components, queue_ids = build_components(pairs)
        all_book_ids = sorted({bid for comp in components for bid in comp})
        holdings_counts = fetch_holdings_counts(cur, all_book_ids)
        mapping, reps = choose_mapping(components, holdings_counts)
        holdings_to_reassign = precheck(cur, mapping)

        payload["precheck"] = {
            "approved_pairs": len(pairs),
            "components": len(components),
            "books_in_components": len(all_book_ids),
            "books_to_merge": len(mapping),
            "representative_books": len(reps),
            "holdings_to_reassign": int(holdings_to_reassign),
        }

        if not args.apply:
            conn.rollback()
            cur.close()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        holdings_updated, books_deleted = apply_mapping(cur, mapping)
        deduped = 0
        if args.dedupe_holdings:
            deduped = dedupe_holdings(cur)
        merge_refreshed = refresh_representatives(cur, reps)
        queue_applied = mark_applied(cur, queue_ids, mapping)

        payload["applied"] = {
            "holdings_reassigned": int(holdings_updated),
            "books_deleted": int(books_deleted),
            "holdings_deleted_by_book_library_dedupe": int(deduped),
            "representative_merge_group_refreshed": int(merge_refreshed),
            "queue_rows_applied": int(queue_applied),
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
