"""
LEGACY: SQLite 전용 빌드 스크립트입니다. 현재는 `scripts/load_csv_to_postgres.py` 사용.
Build split SQLite DB with books (deduped) and holdings (per library).

Run:
    python scripts/build_library_split.py

Output:
    data/library_split.db
"""

import csv
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DATA = ROOT / "data"
DEFAULT_DB_PATH = SOURCE_DATA / "library_split.db"
DB_PATH = Path(os.environ.get("LIBRARY_SPLIT_DB_PATH", DEFAULT_DB_PATH))

SKIP_CODES = {"songpa", "yangcheon"}


def normalize_text(value: str) -> str:
    if not value:
        return ""
    text = str(value).lower()
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[\\s\\[\\]\\(\\){}<>.,/|\\\\\\-_:;\"'`~!?]", "", text)
    return text


def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS holdings;
        DROP TABLE IF EXISTS books;
        CREATE TABLE books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        CREATE TABLE holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL,
            library_code TEXT,
            library TEXT,
            provider TEXT,
            platform TEXT,
            image_url TEXT,
            isbn TEXT,
            FOREIGN KEY(book_id) REFERENCES books(id)
        );
        CREATE INDEX idx_holdings_book_id ON holdings(book_id);
        CREATE INDEX idx_books_title_norm ON books(title_norm);
        CREATE INDEX idx_books_author_norm ON books(author_norm);
        CREATE INDEX idx_books_publisher_norm ON books(publisher_norm);
        """
    )
    conn.commit()


def iter_rows():
    for path in SOURCE_DATA.iterdir():
        if not path.name.endswith("_db.csv"):
            continue
        lib_code = path.stem.replace("_db", "")
        if lib_code in SKIP_CODES:
            continue
        if path.stat().st_size == 0:
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = row.get("title", "") or ""
                author = row.get("author", "") or ""
                publisher = row.get("publisher", "") or ""
                yield {
                    "title": title,
                    "author": author,
                    "publisher": publisher,
                    "image_url": row.get("image_url", "") or "",
                    "isbn": row.get("isbn", "") or "",
                    "provider": row.get("provider", "") or "",
                    "platform": row.get("platform", "") or "",
                    "library": row.get("library", "") or "",
                    "library_code": lib_code,
                    "title_norm": normalize_text(title),
                    "author_norm": normalize_text(author),
                    "publisher_norm": normalize_text(publisher),
                }


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=OFF;")
    try:
        init_db(conn)
        cur = conn.cursor()
        book_map = {}
        holdings_buf = []
        total_rows = 0
        for row in iter_rows():
            total_rows += 1
            key = (row["title_norm"], row["author_norm"], row["publisher_norm"])
            book_id = book_map.get(key)
            if not book_id:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO books
                    (title, author, publisher, image_url, isbn, title_norm, author_norm, publisher_norm)
                    VALUES (?,?,?,?,?,?,?,?)
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
                if cur.lastrowid:
                    book_id = cur.lastrowid
                else:
                    cur.execute(
                        "SELECT id FROM books WHERE title_norm=? AND author_norm=?",
                        (row["title_norm"], row["author_norm"]),
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
                )
            )

            if len(holdings_buf) >= 5000:
                cur.executemany(
                    """
                    INSERT INTO holdings
                    (book_id, library_code, library, provider, platform, image_url, isbn)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    holdings_buf,
                )
                holdings_buf.clear()
            if total_rows % 200000 == 0:
                print(f"[진행] {total_rows:,} rows 처리 중...")

        if holdings_buf:
            cur.executemany(
                """
                INSERT INTO holdings
                (book_id, library_code, library, provider, platform, image_url, isbn)
                VALUES (?,?,?,?,?,?,?)
                """,
                holdings_buf,
            )
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM books;")
        books_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM holdings;")
        holdings_total = cur.fetchone()[0]
        print(f"[완료] rows={total_rows:,} books={books_total:,} holdings={holdings_total:,} -> {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
