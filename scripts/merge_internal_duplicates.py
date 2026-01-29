import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from web import db


def main():
    dry_run = "--dry-run" in sys.argv
    conn = db.get_db()
    try:
        # 1) Set canonical_id on holdings based on platform keys.
        conn.execute(
            """
            UPDATE holdings
            SET canonical_id = 'yes24:' || goods_id
            WHERE (canonical_id IS NULL OR canonical_id = '')
              AND platform ILIKE ?
              AND goods_id IS NOT NULL AND goods_id <> '';
            """,
            ["YES24"],
        )
        conn.execute(
            """
            UPDATE holdings
            SET canonical_id = 'kyobo:' || brcd
            WHERE (canonical_id IS NULL OR canonical_id = '')
              AND platform ILIKE ?
              AND brcd IS NOT NULL AND brcd <> '';
            """,
            ["Kyobo%"],
        )
        conn.execute(
            """
            UPDATE holdings
            SET canonical_id = 'bookcube:' || content_id
            WHERE (canonical_id IS NULL OR canonical_id = '')
              AND platform ILIKE ?
              AND content_id IS NOT NULL AND content_id <> '';
            """,
            ["Bookcube%"],
        )
        conn.execute(
            """
            UPDATE holdings
            SET canonical_id = 'bookcube:' || content_id
            WHERE (canonical_id IS NULL OR canonical_id = '')
              AND platform ILIKE ?
              AND content_id IS NOT NULL AND content_id <> '';
            """,
            ["FxLibrary%"],
        )

        # 2) Set books.canonical_id only when a book maps to exactly one canonical_id.
        conn.execute(
            """
            WITH book_canon AS (
                SELECT book_id, MIN(canonical_id) AS canonical_id
                FROM holdings
                WHERE canonical_id IS NOT NULL AND canonical_id <> ''
                GROUP BY book_id
                HAVING COUNT(DISTINCT canonical_id) = 1
            )
            UPDATE books b
            SET canonical_id = bc.canonical_id
            FROM book_canon bc
            WHERE b.id = bc.book_id;
            """
        )

        # 3) First merge pass: canonical_id groups (platform internal).
        conn.execute(
            """
            UPDATE books
            SET merge_group_id = canonical_id
            WHERE canonical_id IS NOT NULL AND canonical_id <> '';
            """
        )

        # 4) Second merge pass: title/author match across platforms.
        conn.execute(
            """
            UPDATE books b
            SET merge_group_id = r.canonical_id
            FROM (
                SELECT
                    id,
                    title_norm,
                    author_norm,
                    canonical_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY title_norm, author_norm
                        ORDER BY
                            CASE
                                WHEN canonical_id LIKE ? THEN 1
                                WHEN canonical_id LIKE ? THEN 2
                                ELSE 9
                            END,
                            canonical_id
                    ) AS rn
                FROM books
                WHERE canonical_id IS NOT NULL AND canonical_id <> ''
                  AND title_norm IS NOT NULL AND title_norm <> ''
                  AND author_norm IS NOT NULL AND author_norm <> ''
            ) r
            WHERE b.title_norm = r.title_norm
              AND b.author_norm = r.author_norm
              AND r.rn = 1;
            """,
            ["kyobo:%", "yes24:%"],
        )

        # 5) Merge duplicate books per canonical_id.
        cur = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM (
                SELECT canonical_id
                FROM books
                WHERE canonical_id IS NOT NULL AND canonical_id <> ''
                GROUP BY canonical_id
                HAVING COUNT(*) > 1
            ) t;
            """
        )
        dup_groups = cur.fetchone()["cnt"]
        cur.close()

        if dry_run:
            conn.rollback()
            print(f"dry-run: duplicate canonical_id groups = {dup_groups}")
            return

        conn.execute(
            """
            WITH dup AS (
                SELECT canonical_id, MIN(id) AS keep_id, array_agg(id) AS ids
                FROM books
                WHERE canonical_id IS NOT NULL AND canonical_id <> ''
                GROUP BY canonical_id
                HAVING COUNT(*) > 1
            ),
            update_holdings AS (
                UPDATE holdings h
                SET book_id = d.keep_id
                FROM dup d
                WHERE h.book_id = ANY(d.ids)
                  AND h.book_id <> d.keep_id
                RETURNING h.id
            )
            DELETE FROM books b
            USING dup d
            WHERE b.id = ANY(d.ids)
              AND b.id <> d.keep_id;
            """
        )
        conn._conn.commit()
        print(f"merged duplicate canonical_id groups: {dup_groups}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
