"""
Migrate SQLite split DB (books/holdings) to PostgreSQL.

Usage:
  DB_HOST=... DB_PORT=5432 DB_USER=... DB_PASSWORD=... DB_NAME=postgres \
  python scripts/migrate_split_to_postgres.py
"""

import os
import sqlite3
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE = ROOT_DIR / "data" / "library_split.db"
SQLITE_PATH = Path(os.environ.get("SQLITE_PATH", DEFAULT_SQLITE))


def pg_config():
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "dbname": os.environ.get("DB_NAME", "postgres"),
    }


def connect_pg():
    cfg = pg_config()
    if isinstance(cfg, str):
        return psycopg2.connect(cfg)
    return psycopg2.connect(**cfg)


def init_schema(pg_conn):
    cur = pg_conn.cursor()
    cur.execute("DROP TABLE IF EXISTS holdings;")
    cur.execute("DROP TABLE IF EXISTS books;")
    cur.execute(
        """
        CREATE TABLE books (
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
        CREATE TABLE holdings (
            id INTEGER PRIMARY KEY,
            book_id INTEGER NOT NULL,
            library_code TEXT,
            library TEXT,
            provider TEXT,
            platform TEXT,
            image_url TEXT,
            isbn TEXT
        );
        """
    )
    cur.execute("CREATE INDEX idx_holdings_book_id ON holdings(book_id);")
    cur.execute("CREATE INDEX idx_books_title_norm ON books(title_norm);")
    cur.execute("CREATE INDEX idx_books_author_norm ON books(author_norm);")
    cur.execute("CREATE INDEX idx_books_publisher_norm ON books(publisher_norm);")
    pg_conn.commit()


def migrate_table(sqlite_conn, pg_conn, table, columns, batch_size=5000):
    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()
    col_list = ", ".join(columns)
    sqlite_cur.execute(f"SELECT {col_list} FROM {table} ORDER BY id")
    inserted = 0
    while True:
        rows = sqlite_cur.fetchmany(batch_size)
        if not rows:
            break
        execute_values(
            pg_cur,
            f"INSERT INTO {table} ({col_list}) VALUES %s",
            rows,
        )
        pg_conn.commit()
        inserted += len(rows)
        print(f"[{table}] inserted {inserted:,}")


def main():
    if not SQLITE_PATH.exists():
        raise SystemExit(f"SQLite not found: {SQLITE_PATH}")
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    pg_conn = connect_pg()
    try:
        init_schema(pg_conn)
        migrate_table(
            sqlite_conn,
            pg_conn,
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
        migrate_table(
            sqlite_conn,
            pg_conn,
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
            ],
        )
        print("[done] migration complete")
    finally:
        sqlite_conn.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
