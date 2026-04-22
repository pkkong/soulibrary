"""
Load CSV data into PostgreSQL with books/holdings split and de-dup logic.

Env:
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
  CSV_DIR (default: data)
  CSV_ONLY (required for partial update; comma-separated list of csv basenames or library codes)
  MIGRATE_DROP (1/true/yes for explicit local full rebuild)
  ALLOW_REMOTE_REBUILD (1/true/yes to bypass remote full rebuild block; discouraged)
"""

import csv
import datetime as dt
import json
import os
import subprocess
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
GUIDE_STATS_SCRIPT = ROOT / "scripts" / "update_guide_stats.py"
GUIDE_STATS_OUTPUT = ROOT / "web" / "static" / "data" / "guide_stats.json"
LOAD_STATE_FILE = ROOT / "data" / "db_apply_state.json"
LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1"}


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


def is_local_db_target() -> bool:
    return DB_HOST.strip().lower() in LOCAL_DB_HOSTS


def allow_remote_rebuild() -> bool:
    return os.environ.get("ALLOW_REMOTE_REBUILD", "").lower() in {"1", "true", "yes"}


def validate_runtime_mode() -> str:
    if DROP_EXISTING and CSV_ONLY_SET:
        raise RuntimeError("CSV_ONLY and MIGRATE_DROP cannot be used together.")
    if not DROP_EXISTING and not CSV_ONLY_SET:
        raise RuntimeError(
            "Unsafe DB update mode blocked. Use CSV_ONLY for partial update or MIGRATE_DROP=1 for explicit local rebuild."
        )
    if DROP_EXISTING and not is_local_db_target() and not allow_remote_rebuild():
        raise RuntimeError(
            "Remote full rebuild is blocked. Rebuild is local-only by default; use partial update instead."
        )
    return "full_rebuild" if DROP_EXISTING else "partial_update"


def should_refresh_guide_stats() -> bool:
    override = os.environ.get("REFRESH_GUIDE_STATS", "").strip().lower()
    if override in {"1", "true", "yes"}:
        return True
    if override in {"0", "false", "no"}:
        return False
    return is_local_db_target()


def target_key() -> str:
    return f"{DB_HOST}:{DB_PORT}/{DB_NAME}"


def _safe_stat(path: Path):
    try:
        return path.stat()
    except Exception:
        return None


def selected_csv_entries():
    entries = []
    for path in sorted(CSV_DIR.iterdir()):
        if not path.name.endswith("_db.csv"):
            continue
        lib_code = path.stem.replace("_db", "")
        if lib_code in SKIP_CODES:
            continue
        if CSV_ONLY_SET and lib_code not in CSV_ONLY_SET:
            continue
        stat = _safe_stat(path)
        if not stat or stat.st_size == 0:
            continue
        entries.append((lib_code, path, stat))
    return entries


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
    for lib_code, path, _stat in selected_csv_entries():
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
    ensure_books_columns(cur)
    ensure_holdings_columns(cur)
    ensure_id_defaults(cur)


def ensure_books_columns(cur):
    for column_name in [
        "canonical_id",
        "merge_group_id",
    ]:
        cur.execute(f"ALTER TABLE books ADD COLUMN IF NOT EXISTS {column_name} TEXT;")


def ensure_holdings_columns(cur):
    for column_name in [
        "canonical_id",
        "brcd",
        "ctts_dvsn_code",
        "ctgr_id",
        "sntn_auth_code",
        "goods_id",
        "content_id",
    ]:
        cur.execute(f"ALTER TABLE holdings ADD COLUMN IF NOT EXISTS {column_name} TEXT;")


def ensure_id_defaults(cur):
    cur.execute("CREATE SEQUENCE IF NOT EXISTS books_id_seq;")
    cur.execute("ALTER SEQUENCE books_id_seq OWNED BY books.id;")
    cur.execute("ALTER TABLE books ALTER COLUMN id SET DEFAULT nextval('books_id_seq'::regclass);")
    cur.execute("SELECT setval('books_id_seq', COALESCE((SELECT MAX(id) FROM books), 0) + 1, false);")

    cur.execute("CREATE SEQUENCE IF NOT EXISTS holdings_id_seq;")
    cur.execute("ALTER SEQUENCE holdings_id_seq OWNED BY holdings.id;")
    cur.execute("ALTER TABLE holdings ALTER COLUMN id SET DEFAULT nextval('holdings_id_seq'::regclass);")
    cur.execute("SELECT setval('holdings_id_seq', COALESCE((SELECT MAX(id) FROM holdings), 0) + 1, false);")


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


def refresh_guide_stats_cache():
    if not should_refresh_guide_stats():
        print("[guide-stats] skipped: remote DB target")
        return
    if not GUIDE_STATS_SCRIPT.exists():
        print(f"[guide-stats] skipped: script not found: {GUIDE_STATS_SCRIPT}")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(GUIDE_STATS_SCRIPT), "--output", str(GUIDE_STATS_OUTPUT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:
        print(f"[guide-stats] skipped: launch failed: {e}")
        return

    if result.returncode != 0:
        print(f"[guide-stats] skipped: exit={result.returncode}")
        if result.stderr:
            print(result.stderr.strip())
        return

    if result.stdout:
        print(result.stdout.strip())


def _load_apply_state():
    if not LOAD_STATE_FILE.exists():
        return {"targets": {}}
    try:
        with LOAD_STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("targets", {})
            return data
    except Exception:
        pass
    return {"targets": {}}


def _write_apply_state(data):
    LOAD_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = LOAD_STATE_FILE.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, LOAD_STATE_FILE)


def record_apply_state(mode: str, entries):
    if not entries:
        return

    state = _load_apply_state()
    targets = state.setdefault("targets", {})
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    key = target_key()

    if mode == "full_rebuild":
        target_state = {
            "db_host": DB_HOST,
            "db_port": DB_PORT,
            "db_name": DB_NAME,
            "last_applied_at": now,
            "last_mode": mode,
            "libraries": {},
        }
    else:
        target_state = targets.get(key) or {
            "db_host": DB_HOST,
            "db_port": DB_PORT,
            "db_name": DB_NAME,
            "libraries": {},
        }
        target_state["last_applied_at"] = now
        target_state["last_mode"] = mode

    libraries = target_state.setdefault("libraries", {})
    for lib_code, path, stat in entries:
        try:
            rel_path = path.relative_to(ROOT)
        except ValueError:
            rel_path = path
        libraries[lib_code] = {
            "csv_path": str(rel_path).replace("\\", "/"),
            "csv_size": int(stat.st_size),
            "csv_mtime_ns": int(stat.st_mtime_ns),
            "csv_mtime": dt.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "applied_at": now,
            "mode": mode,
        }

    targets[key] = target_state
    _write_apply_state(state)
    print(f"[apply-state] recorded target={key} libs={len(entries)} mode={mode}")


def main():
    print(f"[norm] {NORM_RULE_VERSION}")
    mode = validate_runtime_mode()
    target = target_key()
    csv_only_text = ",".join(sorted(CSV_ONLY_SET)) if CSV_ONLY_SET else "(all)"
    print(f"[mode] {mode} target={target} csv_only={csv_only_text}")
    selected_entries = selected_csv_entries()
    conn = connect_pg()
    conn.autocommit = False
    cur = conn.cursor()
    try:
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
        conn.commit()
        try:
            record_apply_state(mode, selected_entries)
        except Exception as exc:
            print(f"[apply-state] skipped: {exc}")
        print(f"[done] rows={total_rows:,} books={books_total:,} holdings={holdings_total:,}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    refresh_guide_stats_cache()


if __name__ == "__main__":
    main()
