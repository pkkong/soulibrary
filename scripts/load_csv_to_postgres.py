"""
Load CSV data into PostgreSQL with books/holdings split and de-dup logic.

Env:
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
  CSV_DIR (default: data)
  CSV_ONLY (optional: comma-separated list of csv basenames or library codes)
  MIGRATE_DROP (1/true/yes to drop tables first)
"""

import csv
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.norm_rules import (  # noqa: E402
    NORM_RULE_VERSION,
    normalize_author,
    normalize_publisher,
    normalize_title,
)

CSV_DIR = Path(os.environ.get("CSV_DIR", ROOT / "data"))
SKIP_CODES = {"songpa", "yangcheon"}
CSV_ONLY = os.environ.get("CSV_ONLY", "")

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "postgres")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DROP_EXISTING = os.environ.get("MIGRATE_DROP", "").lower() in {"1", "true", "yes"}
HOLDINGS_BATCH = int(os.environ.get("HOLDINGS_BATCH", "5000"))


def _normalize_csv_only(value: str):
    if not value:
        return set()
    raw = [v.strip() for v in value.split(",") if v.strip()]
    normalized = set()
    for item in raw:
        if item.endswith(".csv"):
            stem = Path(item).stem
        else:
            stem = item
        normalized.add(stem.replace("_db", ""))
    return normalized


CSV_ONLY_SET = _normalize_csv_only(CSV_ONLY)


def normalize_provider(value: str) -> str:
    if not value:
        return ""
    text = str(value).strip()
    mapping = {
        "교보": "교보",
        "교보문고": "교보",
        "교보전자책": "교보",
        "kyobo": "교보",
        "yes24": "YES24",
        "예스24": "YES24",
        "알라딘": "알라딘",
        "aladin": "알라딘",
        "bookcube": "북큐브",
        "북큐브": "북큐브",
    }
    norm = mapping.get(text) or mapping.get(text.lower())
    return norm or text


def iter_rows():
    for path in CSV_DIR.iterdir():
        if not path.name.endswith("_db.csv"):
            continue
        lib_code = path.stem.replace("_db", "")
        if lib_code in SKIP_CODES:
            continue
        if CSV_ONLY_SET and lib_code not in CSV_ONLY_SET:
            continue
        if path.stat().st_size == 0:
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                def _norm_empty(value: str):
                    if value is None:
                        return None
                    text = str(value).strip()
                    return text if text else None

                title = row.get("title", "") or ""
                author = row.get("author", "") or ""
                publisher = row.get("publisher", "") or ""
                yield {
                    "title": title,
                    "author": author,
                    "publisher": publisher,
                    "image_url": row.get("image_url", "") or "",
                    "isbn": _norm_empty(row.get("isbn", "")),
                    "brcd": _norm_empty(row.get("brcd", "")),
                    "ctts_dvsn_code": _norm_empty(row.get("ctts_dvsn_code", "")),
                    "ctgr_id": _norm_empty(row.get("ctgr_id", "")),
                    "sntn_auth_code": _norm_empty(row.get("sntn_auth_code", "")),
                    "goods_id": _norm_empty(row.get("goods_id", "")),
                    "content_id": _norm_empty(row.get("content_id", "")),
                    "provider": normalize_provider(row.get("provider", "") or ""),
                    "platform": row.get("platform", "") or "",
                    "library": row.get("library", "") or "",
                    "library_code": lib_code,
                    "title_norm": normalize_title(title),
                    "author_norm": normalize_author(author),
                    "publisher_norm": normalize_publisher(publisher),
                }


def connect_pg():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def init_schema(cur):
    if DROP_EXISTING:
        cur.execute("DROP TABLE IF EXISTS holdings;")
        cur.execute("DROP TABLE IF EXISTS books;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            id SERIAL PRIMARY KEY,
            title TEXT,
            author TEXT,
            publisher TEXT,
            image_url TEXT,
            isbn TEXT,
            title_norm TEXT,
            author_norm TEXT,
            publisher_norm TEXT,
            UNIQUE(title_norm, author_norm, publisher_norm)
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS holdings (
            id SERIAL PRIMARY KEY,
            book_id INTEGER NOT NULL REFERENCES books(id),
            library_code TEXT,
            library TEXT,
            provider TEXT,
            platform TEXT,
            image_url TEXT,
            isbn TEXT,
            brcd TEXT,
            ctts_dvsn_code TEXT,
            ctgr_id TEXT,
            sntn_auth_code TEXT,
            goods_id TEXT,
            content_id TEXT
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_books_title_norm ON books(title_norm);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_books_author_norm ON books(author_norm);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_books_publisher_norm ON books(publisher_norm);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_holdings_book_id ON holdings(book_id);")


def has_books_unique_index(cur):
    try:
        cur.execute(
            """
            SELECT 1
            FROM pg_indexes
            WHERE tablename = 'books'
              AND indexdef ILIKE '%unique%'
              AND indexdef ILIKE '%(title_norm, author_norm, publisher_norm)%'
            LIMIT 1
            """
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def purge_holdings(cur, library_codes):
    if not library_codes:
        return
    cur.execute(
        "DELETE FROM holdings WHERE library_code = ANY(%s)",
        (list(library_codes),),
    )


def main():
    print(f"[norm] {NORM_RULE_VERSION}")
    conn = connect_pg()
    conn.autocommit = True
    cur = conn.cursor()
    init_schema(cur)
    use_unique = has_books_unique_index(cur)
    if CSV_ONLY_SET and not DROP_EXISTING:
        purge_holdings(cur, CSV_ONLY_SET)

    book_map = {}
    holdings_buf = []
    total_rows = 0
    for row in iter_rows():
        total_rows += 1
        key = (row["title_norm"], row["author_norm"], row["publisher_norm"])
        book_id = book_map.get(key)
        if not book_id:
            if use_unique:
                cur.execute(
                    """
                    INSERT INTO books
                    (title, author, publisher, image_url, isbn, title_norm, author_norm, publisher_norm)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (title_norm, author_norm, publisher_norm)
                    DO NOTHING
                    RETURNING id
                    """,
                    (
                        row["title"],
                        row["author"],
                        row["publisher"],
                        row["image_url"],
                        row["isbn"],
                        row["title_norm"],
                        row["author_norm"],
                        row["publisher_norm"],
                    ),
                )
                res = cur.fetchone()
                if res:
                    book_id = res[0]
                else:
                    cur.execute(
                        "SELECT id FROM books WHERE title_norm=%s AND author_norm=%s AND publisher_norm=%s",
                        key,
                    )
                    book_id = cur.fetchone()[0]
            else:
                cur.execute(
                    "SELECT id FROM books WHERE title_norm=%s AND author_norm=%s AND publisher_norm=%s",
                    key,
                )
                res = cur.fetchone()
                if res:
                    book_id = res[0]
                else:
                    cur.execute(
                        """
                        INSERT INTO books
                        (title, author, publisher, image_url, isbn, title_norm, author_norm, publisher_norm)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (
                            row["title"],
                            row["author"],
                            row["publisher"],
                            row["image_url"],
                            row["isbn"],
                            row["title_norm"],
                            row["author_norm"],
                            row["publisher_norm"],
                        ),
                    )
                    book_id = cur.fetchone()[0]
            book_map[key] = book_id

        holdings_buf.append(
            (
                book_id,
                row["library_code"],
                row["library"],
                row["provider"],
                row["platform"],
                row["image_url"],
                row["isbn"],
                row["brcd"],
                row["ctts_dvsn_code"],
                row["ctgr_id"],
                row["sntn_auth_code"],
                row["goods_id"],
                row["content_id"],
            )
        )
        if len(holdings_buf) >= HOLDINGS_BATCH:
            execute_values(
                cur,
                """
                INSERT INTO holdings
                (book_id, library_code, library, provider, platform, image_url, isbn, brcd, ctts_dvsn_code, ctgr_id, sntn_auth_code, goods_id, content_id)
                VALUES %s
                """,
                holdings_buf,
            )
            holdings_buf.clear()
        if total_rows % 200000 == 0:
            print(f"[progress] rows={total_rows:,}")

    if holdings_buf:
        execute_values(
            cur,
            """
            INSERT INTO holdings
            (book_id, library_code, library, provider, platform, image_url, isbn, brcd, ctts_dvsn_code, ctgr_id, sntn_auth_code, goods_id, content_id)
            VALUES %s
            """,
            holdings_buf,
        )
    cur.execute("SELECT COUNT(*) FROM books;")
    books_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM holdings;")
    holdings_total = cur.fetchone()[0]
    print(f"[done] rows={total_rows:,} books={books_total:,} holdings={holdings_total:,}")
    conn.close()


if __name__ == "__main__":
    main()
