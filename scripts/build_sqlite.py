"""
CSV/JSON -> SQLite(FTS5) 변환 스크립트

실행:
    python scripts/build_sqlite.py

결과:
    data/library.db 에 books(베이스 테이블) + books_fts(FTS5) 생성
"""

import csv
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "library.db"
# Allow overriding DB path for read-only filesystems (e.g., Cloudtype root)
DB_PATH = Path(os.environ.get("LIBRARY_DB_PATH", DEFAULT_DB_PATH))
DATA = DB_PATH.parent

# 표준 컬럼
COLUMNS = ["title", "author", "publisher", "library", "image_url", "isbn", "provider", "platform", "library_code"]


def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS books;
        DROP TABLE IF EXISTS books_fts;
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            publisher TEXT,
            library TEXT,
            image_url TEXT,
            isbn TEXT,
            provider TEXT,
            platform TEXT,
            library_code TEXT
        );
        CREATE VIRTUAL TABLE books_fts USING fts5(
            title, author, publisher, library, provider, platform, isbn, library_code,
            content='books', content_rowid='id'
        );
        """
    )
    conn.commit()


def iter_rows():
    for path in DATA.iterdir():
        if path.name.endswith("_db.csv"):
            lib_code = path.stem.replace("_db", "")
            if path.stat().st_size == 0:
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    yield {
                        "title": row.get("title", ""),
                        "author": row.get("author", ""),
                        "publisher": row.get("publisher", ""),
                        "library": row.get("library", ""),
                        "image_url": row.get("image_url", ""),
                        "isbn": row.get("isbn", ""),
                        "provider": row.get("provider", ""),
                        "platform": row.get("platform", ""),
                        "library_code": lib_code,
                    }
        elif path.name == "seoul_ebook_db.json":
            with path.open("r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception:
                    continue
            for row in data:
                yield {
                    "title": row.get("title", ""),
                    "author": row.get("author", ""),
                    "publisher": row.get("publisher", ""),
                    "library": row.get("library", ""),
                    "image_url": row.get("image_url", ""),
                    "isbn": row.get("isbn", ""),
                    "provider": row.get("provider", ""),
                    "platform": row.get("platform", ""),
                    "library_code": "seoul",
                }


def bulk_insert(conn: sqlite3.Connection):
    cur = conn.cursor()
    buf = []
    for idx, row in enumerate(iter_rows(), 1):
        buf.append([row.get(col, "") for col in COLUMNS])
        if len(buf) >= 5000:
            cur.executemany(
                "INSERT INTO books (title, author, publisher, library, image_url, isbn, provider, platform, library_code) VALUES (?,?,?,?,?,?,?,?,?)",
                buf,
            )
            buf.clear()
    if buf:
        cur.executemany(
            "INSERT INTO books (title, author, publisher, library, image_url, isbn, provider, platform, library_code) VALUES (?,?,?,?,?,?,?,?,?)",
            buf,
        )
    conn.commit()
    cur.execute("INSERT INTO books_fts (rowid, title, author, publisher, library, provider, platform, isbn, library_code) SELECT id, title, author, publisher, library, provider, platform, isbn, library_code FROM books;")
    conn.commit()


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)
        bulk_insert(conn)
        cur = conn.execute("SELECT COUNT(*) FROM books;")
        total = cur.fetchone()[0]
        print(f"[완료] 총 {total}권 SQLite에 적재됨 -> {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
