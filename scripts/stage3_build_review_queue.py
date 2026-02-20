"""
Stage3 candidate builder (conservative, admin-review required).

Purpose:
- Build merge candidate pairs from strong text match (title_norm + author_norm exact).
- Store candidates in review queue (no automatic merge).
- Keep existing decisions (approved/rejected/applied/hold) intact.

Usage:
  python scripts/stage3_build_review_queue.py
  python scripts/stage3_build_review_queue.py --limit 5000
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values


EDITION_RE = re.compile(r"(개정|증보|수정|제\s*\d+\s*판|\d+\s*판)")
VOLUME_RE = re.compile(r"(상권|하권|상|하|\d+\s*권)")
SET_RE = re.compile(r"(세트)")
TRANSLATION_RE = re.compile(r"(번역|옮김|역자)")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=20000,
        help="Max candidate pairs to generate (0 means no limit)",
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
        CREATE INDEX IF NOT EXISTS idx_merge_review_status_score
        ON merge_review_queue (status, total_score DESC, updated_at DESC)
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_merge_review_last_seen
        ON merge_review_queue (last_seen_at DESC)
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
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_merge_review_log_queue_id
        ON merge_review_log (queue_id, created_at DESC)
        """
    )


def _extract_token(pattern, text):
    if not text:
        return ""
    m = pattern.search(text)
    if not m:
        return ""
    return re.sub(r"\s+", "", m.group(0))


def _has_pattern(pattern, text):
    return bool(pattern.search(text or ""))


def _risk_and_score(row):
    left_title = (row["left_title"] or "").strip()
    right_title = (row["right_title"] or "").strip()
    left_pub_norm = (row["left_publisher_norm"] or "").strip()
    right_pub_norm = (row["right_publisher_norm"] or "").strip()

    title_score = 60
    author_score = 30
    publisher_score = 10 if left_pub_norm and left_pub_norm == right_pub_norm else 0

    left_isbn = (row["left_isbn"] or "").strip()
    right_isbn = (row["right_isbn"] or "").strip()
    signal_score = 15 if left_isbn and right_isbn and left_isbn == right_isbn else 0

    risk_flags = []
    penalty = 0

    left_edition = _extract_token(EDITION_RE, left_title)
    right_edition = _extract_token(EDITION_RE, right_title)
    if left_edition != right_edition:
        if left_edition or right_edition:
            risk_flags.append("edition_diff")
            penalty += 25

    left_volume = _extract_token(VOLUME_RE, left_title)
    right_volume = _extract_token(VOLUME_RE, right_title)
    if left_volume != right_volume:
        if left_volume or right_volume:
            risk_flags.append("volume_diff")
            penalty += 25

    left_set = _has_pattern(SET_RE, left_title)
    right_set = _has_pattern(SET_RE, right_title)
    if left_set != right_set:
        risk_flags.append("set_diff")
        penalty += 20

    left_trans = _has_pattern(TRANSLATION_RE, left_title)
    right_trans = _has_pattern(TRANSLATION_RE, right_title)
    if left_trans != right_trans:
        risk_flags.append("translation_marker_diff")
        penalty += 15

    if left_pub_norm and right_pub_norm and left_pub_norm != right_pub_norm:
        risk_flags.append("publisher_diff")
        penalty += 15

    total = max(0, title_score + author_score + publisher_score + signal_score - penalty)
    reason = "title_norm+author_norm exact"

    return {
        "title_score": title_score,
        "author_score": author_score,
        "publisher_score": publisher_score,
        "signal_score": signal_score,
        "total_score": total,
        "risk_flags": ",".join(risk_flags),
        "reason": reason,
    }


def fetch_pairs(cur, limit):
    pair_limit = int(limit or 0)
    key_limit = max(pair_limit * 10, 500) if pair_limit > 0 else 5000
    limit_sql = "LIMIT %s" if pair_limit > 0 else ""
    params = [key_limit]
    if pair_limit > 0:
        params.append(pair_limit)

    cur.execute(
        f"""
        WITH hold_counts AS (
          SELECT book_id, COUNT(*) AS holdings_count
          FROM holdings
          GROUP BY book_id
        ),
        live_books AS (
          SELECT
            b.id,
            b.title,
            b.author,
            b.publisher,
            b.isbn,
            b.title_norm,
            b.author_norm,
            b.publisher_norm,
            hc.holdings_count
          FROM books b
          JOIN hold_counts hc ON hc.book_id = b.id
          WHERE NULLIF(TRIM(b.title_norm), '') IS NOT NULL
            AND NULLIF(TRIM(b.author_norm), '') IS NOT NULL
        ),
        dup_keys AS (
          SELECT
            title_norm,
            author_norm,
            COUNT(*) AS book_count,
            SUM(holdings_count) AS holdings_sum
          FROM live_books
          GROUP BY title_norm, author_norm
          HAVING COUNT(*) > 1
          ORDER BY holdings_sum DESC, book_count DESC, title_norm ASC, author_norm ASC
          LIMIT %s
        ),
        key_books AS (
          SELECT
            l.*,
            ROW_NUMBER() OVER (
              PARTITION BY l.title_norm, l.author_norm
              ORDER BY l.holdings_count DESC, l.id ASC
            ) AS rn
          FROM live_books l
          JOIN dup_keys k
            ON k.title_norm = l.title_norm
           AND k.author_norm = l.author_norm
        )
        SELECT
          l.id AS left_book_id,
          r.id AS right_book_id,
          l.title AS left_title,
          r.title AS right_title,
          l.author AS left_author,
          r.author AS right_author,
          l.publisher AS left_publisher,
          r.publisher AS right_publisher,
          l.publisher_norm AS left_publisher_norm,
          r.publisher_norm AS right_publisher_norm,
          l.isbn AS left_isbn,
          r.isbn AS right_isbn,
          l.holdings_count AS left_holdings_count,
          r.holdings_count AS right_holdings_count
        FROM key_books l
        JOIN key_books r
          ON l.id < r.id
         AND l.title_norm = r.title_norm
         AND l.author_norm = r.author_norm
        WHERE l.rn <= 4
          AND r.rn <= 4
        ORDER BY
          GREATEST(l.holdings_count, r.holdings_count) DESC,
          LEAST(l.holdings_count, r.holdings_count) DESC,
          l.id ASC,
          r.id ASC
        {limit_sql}
        """,
        params,
    )
    rows = cur.fetchall()
    output = []
    for row in rows:
        output.append(
            {
                "left_book_id": int(row[0]),
                "right_book_id": int(row[1]),
                "left_title": row[2] or "",
                "right_title": row[3] or "",
                "left_author": row[4] or "",
                "right_author": row[5] or "",
                "left_publisher": row[6] or "",
                "right_publisher": row[7] or "",
                "left_publisher_norm": row[8] or "",
                "right_publisher_norm": row[9] or "",
                "left_isbn": row[10] or "",
                "right_isbn": row[11] or "",
                "left_holdings_count": int(row[12] or 0),
                "right_holdings_count": int(row[13] or 0),
            }
        )
    return output


def upsert_candidates(cur, candidates):
    if not candidates:
        return 0

    values = []
    for c in candidates:
        score = _risk_and_score(c)
        values.append(
            (
                c["left_book_id"],
                c["right_book_id"],
                "rule_auto",
                score["title_score"],
                score["author_score"],
                score["publisher_score"],
                score["signal_score"],
                score["total_score"],
                score["risk_flags"],
                score["reason"],
            )
        )

    sql = """
        INSERT INTO merge_review_queue (
          pair_left_book_id,
          pair_right_book_id,
          source,
          title_score,
          author_score,
          publisher_score,
          signal_score,
          total_score,
          risk_flags,
          reason
        )
        VALUES %s
        ON CONFLICT (pair_left_book_id, pair_right_book_id)
        DO UPDATE
        SET
          source = EXCLUDED.source,
          title_score = EXCLUDED.title_score,
          author_score = EXCLUDED.author_score,
          publisher_score = EXCLUDED.publisher_score,
          signal_score = EXCLUDED.signal_score,
          total_score = EXCLUDED.total_score,
          risk_flags = EXCLUDED.risk_flags,
          reason = EXCLUDED.reason,
          updated_at = NOW(),
          last_seen_at = NOW()
        WHERE merge_review_queue.status IN ('new', 'hold')
    """

    execute_values(cur, sql, values, page_size=1000)
    return len(values)


def count_summary(cur):
    cur.execute(
        """
        SELECT status, COUNT(*)
        FROM merge_review_queue
        GROUP BY status
        ORDER BY status
        """
    )
    by_status = {r[0]: int(r[1]) for r in cur.fetchall()}
    cur.execute("SELECT COUNT(*) FROM merge_review_queue")
    total = int(cur.fetchone()[0] or 0)
    return total, by_status


def main():
    args = parse_args()
    conn = connect()
    conn.autocommit = False
    payload = {
        "measured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db": os.getenv("DB_NAME", "soulib_test"),
        "limit": int(args.limit or 0),
    }
    try:
        cur = conn.cursor()
        ensure_review_tables(cur)
        pairs = fetch_pairs(cur, args.limit)
        upsert_count = upsert_candidates(cur, pairs)

        cur.execute(
            """
            INSERT INTO merge_review_log (queue_id, action, actor, note, payload)
            VALUES (NULL, 'build_candidates', 'system', %s, %s::jsonb)
            """,
            (
                "stage3 queue build",
                json.dumps(
                    {
                        "pairs_fetched": len(pairs),
                        "pairs_upserted": upsert_count,
                        "limit": int(args.limit or 0),
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        total, by_status = count_summary(cur)
        conn.commit()
        cur.close()

        payload["pairs_fetched"] = len(pairs)
        payload["pairs_upserted"] = upsert_count
        payload["queue_total"] = total
        payload["queue_by_status"] = by_status
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
