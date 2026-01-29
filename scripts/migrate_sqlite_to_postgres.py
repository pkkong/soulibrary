"""LEGACY: SQLite → PostgreSQL 마이그레이션 (이제는 CSV → PostgreSQL 권장)."""
import os
import sqlite3
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import execute_values


SQLITE_PATH = os.environ.get(
    "SQLITE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "library_split.db"),
)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_HOST = os.environ.get("DB_HOST", "").strip()
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "postgres")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DROP_EXISTING = os.environ.get("MIGRATE_DROP", "").lower() in {"1", "true", "yes"}
BATCH_SIZE = int(os.environ.get("MIGRATE_BATCH", "5000"))


def parse_database_url(url):
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "dbname": parsed.path.lstrip("/") if parsed.path else "",
        "user": parsed.username,
        "password": parsed.password,
    }


def pg_connect():
    if DATABASE_URL:
        cfg = parse_database_url(DATABASE_URL)
    else:
        cfg = {
            "host": DB_HOST,
            "port": DB_PORT,
            "dbname": DB_NAME,
            "user": DB_USER,
            "password": DB_PASSWORD,
        }
    conn = psycopg2.connect(**cfg)
    conn.autocommit = True
    return conn


def init_schema(cur):
    if DROP_EXISTING:
        cur.execute("DROP TABLE IF EXISTS holdings;")
        cur.execute("DROP TABLE IF EXISTS books;")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            author TEXT,
            publisher TEXT,
            image_url TEXT,
            isbn TEXT,
            title_norm TEXT,
            author_norm TEXT,
            publisher_norm TEXT
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL,
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


def copy_table(sqlite_conn, pg_cur, table, columns):
    col_list = ", ".join(columns)
    placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES %s"
    select_sql = f"SELECT {col_list} FROM {table}"

    cur = sqlite_conn.cursor()
    cur.execute(select_sql)
    total = 0
    while True:
        rows = cur.fetchmany(BATCH_SIZE)
        if not rows:
            break
        execute_values(pg_cur, insert_sql, rows, template=placeholders)
        total += len(rows)
        if total % (BATCH_SIZE * 10) == 0:
            print(f"[migrate] {table}: {total:,} rows")
    print(f"[migrate] {table}: {total:,} rows copied")


def main():
    if not os.path.exists(SQLITE_PATH):
        raise SystemExit(f"SQLite file not found: {SQLITE_PATH}")

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = pg_connect()
    try:
        pg_cur = pg_conn.cursor()
        init_schema(pg_cur)

        copy_table(
            sqlite_conn,
            pg_cur,
            "books",
            [
                "id",
                "title",
                "author",
                "publisher",
                "image_url",
                "isbn",
                "title_norm",
                "author_norm",
                "publisher_norm",
            ],
        )
        copy_table(
            sqlite_conn,
            pg_cur,
            "holdings",
            [
                "id",
                "book_id",
                "library_code",
                "library",
                "provider",
                "platform",
                "image_url",
                "isbn",
                "brcd",
                "ctts_dvsn_code",
                "ctgr_id",
                "sntn_auth_code",
                "goods_id",
                "content_id",
            ],
        )
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
