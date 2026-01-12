"""
Convert source CSV/JSON files into a unified SQLite DB with FTS5.

Run:
    python scripts/build_sqlite.py

Output:
    data/library.db with books, books_fts (FTS), and libraries metadata.
"""

import csv
import json
import os
import sqlite3
import sys
import re
import time
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent
SOURCE_DATA = ROOT / "data"
DEFAULT_DB_PATH = SOURCE_DATA / "library.db"
DB_PATH = Path(os.environ.get("LIBRARY_DB_PATH", DEFAULT_DB_PATH))
TMP_DB_SUFFIX = ".building"
DATA = SOURCE_DATA  # backward compatibility alias

# Import library metadata from web.config
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
from web.config import LIBRARIES, PLATFORM_LABELS, LIBRARY_SHORT

# Book columns
COLUMNS = [
    "title",
    "author",
    "publisher",
    "library",
    "image_url",
    "isbn",
    "provider",
    "platform",
    "library_code",
    "title_norm",
    "author_norm",
    "publisher_norm",
]


def normalize_text(value: str) -> str:
    """Lowercase and strip spaces/punctuation for prefix search."""
    if not value:
        return ""
    text = str(value).lower()
    text = re.sub(r"[\u200b\ufeff]", "", text)  # zero-width chars
    text = re.sub(r"[\\s\\[\\]\\(\\){}<>.,/|\\\\\\-_:;\"'`~!?]", "", text)
    return text


def init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS books;
        DROP TABLE IF EXISTS books_fts;
        DROP TABLE IF EXISTS libraries;
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
            library_code TEXT,
            title_norm TEXT,
            author_norm TEXT,
            publisher_norm TEXT
        );
        CREATE VIRTUAL TABLE books_fts USING fts5(
            title, author, publisher, library, provider, platform, isbn, library_code,
            content='books', content_rowid='id', tokenize='unicode61'
        );
        CREATE INDEX idx_books_title_norm ON books(title_norm);
        CREATE INDEX idx_books_author_norm ON books(author_norm);
        CREATE INDEX idx_books_publisher_norm ON books(publisher_norm);
        CREATE TABLE libraries (
            code TEXT PRIMARY KEY,
            name TEXT,
            library_name TEXT,
            short_name TEXT,
            platform TEXT,
            platform_label TEXT,
            service_type TEXT,
            homepage_url TEXT,
            type TEXT,
            db_file TEXT,
            total_count_url TEXT,
            url_prefix TEXT
        );
        """
    )
    conn.commit()


def iter_rows():
    """Yield normalized rows from all source files."""
    for path in SOURCE_DATA.iterdir():
        if path.name.endswith("_db.csv"):
            lib_code = path.stem.replace("_db", "")
            if lib_code in {"songpa", "yangcheon"}:
                continue
            if path.stat().st_size == 0:
                continue
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = row.get("title", "")
                    author = row.get("author", "")
                    publisher = row.get("publisher", "")
                    yield {
                        "title": title,
                        "author": author,
                        "publisher": publisher,
                        "library": row.get("library", ""),
                        "image_url": row.get("image_url", ""),
                        "isbn": row.get("isbn", ""),
                        "provider": row.get("provider", ""),
                        "platform": row.get("platform", ""),
                        "library_code": lib_code,
                        "title_norm": normalize_text(title),
                        "author_norm": normalize_text(author),
                        "publisher_norm": normalize_text(publisher),
                    }


def bulk_insert(conn: sqlite3.Connection):
    cur = conn.cursor()
    buf = []
    for idx, row in enumerate(iter_rows(), 1):
        buf.append([row.get(col, "") for col in COLUMNS])
        if len(buf) >= 5000:
            cur.executemany(
                """
                INSERT INTO books (
                    title, author, publisher, library, image_url, isbn, provider, platform, library_code,
                    title_norm, author_norm, publisher_norm
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                buf,
            )
            buf.clear()
    if buf:
        cur.executemany(
            """
            INSERT INTO books (
                title, author, publisher, library, image_url, isbn, provider, platform, library_code,
                title_norm, author_norm, publisher_norm
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            buf,
        )
    conn.commit()
    cur.execute(
        "INSERT INTO books_fts (rowid, title, author, publisher, library, provider, platform, isbn, library_code) "
        "SELECT id, title, author, publisher, library, provider, platform, isbn, library_code FROM books;"
    )
    conn.commit()


def insert_libraries(conn: sqlite3.Connection):
    cur = conn.cursor()
    rows = []
    for code, cfg in LIBRARIES.items():
        platform = cfg.get("platform", "Unknown")
        platform_label = PLATFORM_LABELS.get(platform, "기타")
        rows.append(
            (
                code,
                cfg.get("name", cfg.get("library_name", code)),
                cfg.get("library_name", cfg.get("name", code)),
                LIBRARY_SHORT.get(code, cfg.get("library_name", code)),
                platform,
                platform_label,
                cfg.get("service_type", ""),
                cfg.get("homepage_url", ""),
                cfg.get("type", ""),
                cfg.get("db_file", ""),
                cfg.get("total_count_url", ""),
                cfg.get("url_prefix", ""),
            )
        )
    cur.executemany(
        """
        INSERT INTO libraries (
            code, name, library_name, short_name, platform, platform_label, service_type, homepage_url, type, db_file, total_count_url, url_prefix
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    conn.commit()


def _atomic_replace(src: Path, dest: Path, retries: int = 10, delay: float = 0.5):
    for attempt in range(retries):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


def main():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = DB_PATH.with_suffix(DB_PATH.suffix + TMP_DB_SUFFIX)
    if tmp_db.exists():
        try:
            tmp_db.unlink()
        except Exception:
            pass
    conn = sqlite3.connect(tmp_db)
    try:
        init_db(conn)
        bulk_insert(conn)
        insert_libraries(conn)
        cur = conn.execute("SELECT COUNT(*) FROM books;")
        total = cur.fetchone()[0]
    finally:
        conn.close()

    _atomic_replace(tmp_db, DB_PATH)
    print(f"[완료] 총 {total}권 SQLite로 재생성 -> {DB_PATH}")


if __name__ == "__main__":
    main()
