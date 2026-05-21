import os
import time
import re
import json
import secrets
import traceback
import random
from urllib.parse import urlencode

from db import get_db, using_postgres
from flask import Flask, render_template, request, jsonify, send_from_directory, Response, abort, url_for, redirect
from werkzeug.middleware.proxy_fix import ProxyFix
from blog_comments import create_blog_comment, get_blog_comments
from blog_posts import get_blog_post, get_blog_posts
from config import LIBRARIES, PLATFORM_LABELS, LIBRARY_SHORT
from seo_books import get_seo_book_by_slug, get_seo_books
from utils.normalize import (
    normalize_title,
    normalize_author,
    normalize_search_text,
    normalize_search_tokens,
    normalize_provider,
)
from utils.providers import provider_from_platforms, platform_to_provider_label
from data_quality_admin import data_quality_bp
from live_search_routes import live_search_bp
from report_routes import report_bp
from live_search.service import live_search as run_live_search
from status_api_routes import (
    bookcube_base_url,
    build_kyobo_detail_url,
    status_api_bp,
    yes24_base_url,
)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.register_blueprint(data_quality_bp)
app.register_blueprint(status_api_bp)
app.register_blueprint(live_search_bp)
app.register_blueprint(report_bp)


@app.after_request
def add_html_no_cache_headers(response):
    if response.content_type and response.content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT_DIR, "data", "library_split.db")
LEGACY_DB = os.path.join(ROOT_DIR, "data", "library.db")
DB_PATH = os.environ.get("LIBRARY_DB_PATH", DEFAULT_DB if os.path.exists(DEFAULT_DB) else LEGACY_DB)
SHARED_SHELVES_FILE = os.environ.get("SHARED_SHELVES_FILE", os.path.join(ROOT_DIR, "data", "shared_shelves.json"))
SHARED_SHELVES_STORAGE = os.environ.get("SHARED_SHELVES_STORAGE", "json").strip().lower()
MAX_SHARED_SHELF_BOOKS = 200
SHARED_SHELF_SLUG_LENGTH = 16
LIB_DETAIL_TTL_SEC = int(os.environ.get("LIB_DETAIL_TTL", "300"))
LIB_DETAIL_CACHE = {}
SITEMAP_PAGE_SIZE = min(int(os.environ.get("SITEMAP_PAGE_SIZE", "50000")), 50000)
SITEMAP_TTL_SEC = int(os.environ.get("SITEMAP_TTL", "21600"))
SITEMAP_CACHE = {"ts": 0, "count": 0, "pages": 0}
SITEMAP_PAGE_CACHE = {}
HOLDINGS_COLUMNS = None
SHARED_SHELVES_TABLE_READY = False
SUBSCRIPTION_TAG_PATTERN = re.compile(r"\s*\[구독형전자책\]\s*")


def _get_holdings_columns(conn):
    global HOLDINGS_COLUMNS
    if HOLDINGS_COLUMNS is not None:
        return HOLDINGS_COLUMNS
    try:
        cur = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='holdings';"
        )
        rows = cur.fetchall()
        HOLDINGS_COLUMNS = {r.get("column_name") for r in rows if r.get("column_name")}
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())
        HOLDINGS_COLUMNS = set()
    return HOLDINGS_COLUMNS


def get_db_conn():
    return get_db(DB_PATH)


def legacy_db_available():
    return using_postgres() or os.path.exists(DB_PATH)


def clean_display_title(value):
    text = str(value or "")
    text = SUBSCRIPTION_TAG_PATTERN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_shared_text(value, limit=200):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _shared_shelves_use_postgres():
    if SHARED_SHELVES_STORAGE == "postgres":
        return True
    if SHARED_SHELVES_STORAGE == "json":
        return False
    return using_postgres()


def _require_shared_shelves_postgres_config():
    if not using_postgres():
        raise RuntimeError("SHARED_SHELVES_STORAGE=postgres requires DATABASE_URL or DB_HOST.")


def _shared_shelf_timestamp(value):
    if not value:
        return ""
    if hasattr(value, "isoformat"):
        return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return str(value)


def _shared_shelf_from_row(row):
    if not row:
        return None
    books = row.get("books") or []
    if isinstance(books, str):
        try:
            books = json.loads(books)
        except Exception:
            books = []
    return {
        "slug": row.get("slug") or "",
        "title": row.get("title") or "공유 서재",
        "description": row.get("description") or "",
        "books": books if isinstance(books, list) else [],
        "view_count": int(row.get("view_count") or 0),
        "created_at": _shared_shelf_timestamp(row.get("created_at")),
        "updated_at": _shared_shelf_timestamp(row.get("updated_at")),
    }


def _ensure_shared_shelves_table(conn):
    global SHARED_SHELVES_TABLE_READY
    if SHARED_SHELVES_TABLE_READY:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS shared_shelves (
            id BIGSERIAL PRIMARY KEY,
            slug VARCHAR(40) NOT NULL UNIQUE,
            title TEXT NOT NULL,
            description TEXT,
            books JSONB NOT NULL,
            view_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at TIMESTAMPTZ
        );
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shared_shelves_slug ON shared_shelves(slug);")
    conn.commit()
    SHARED_SHELVES_TABLE_READY = True


def _generate_shared_shelf_slug():
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(SHARED_SHELF_SLUG_LENGTH))


def _load_shared_shelves():
    if not os.path.exists(SHARED_SHELVES_FILE):
        return {}
    try:
        with open(SHARED_SHELVES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"[shelf warning] shared shelf load failed: {e}")
    return {}


def _save_shared_shelves(data):
    os.makedirs(os.path.dirname(SHARED_SHELVES_FILE), exist_ok=True)
    tmp_path = f"{SHARED_SHELVES_FILE}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SHARED_SHELVES_FILE)


def _create_shared_shelf_json(title, description, books):
    store = _load_shared_shelves()
    slug = _generate_shared_shelf_slug()
    while slug in store:
        slug = _generate_shared_shelf_slug()
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    shelf = {
        "slug": slug,
        "title": title,
        "description": description,
        "books": books,
        "view_count": 0,
        "created_at": created_at,
        "updated_at": created_at,
    }
    store[slug] = shelf
    _save_shared_shelves(store)
    return shelf


def _get_shared_shelf_json(slug, increment_view=False):
    store = _load_shared_shelves()
    shelf = store.get(slug)
    if not shelf:
        return None
    if increment_view:
        shelf["view_count"] = int(shelf.get("view_count") or 0) + 1
        store[slug] = shelf
        _save_shared_shelves(store)
    return shelf


def _create_shared_shelf_postgres(title, description, books):
    _require_shared_shelves_postgres_config()
    conn = get_db_conn()
    try:
        _ensure_shared_shelves_table(conn)
        for _ in range(5):
            slug = _generate_shared_shelf_slug()
            existing = conn.execute("SELECT 1 AS exists FROM shared_shelves WHERE slug = ?", (slug,)).fetchone()
            if existing:
                continue
            cur = conn.execute(
                """
                INSERT INTO shared_shelves (slug, title, description, books)
                VALUES (?, ?, ?, ?::jsonb)
                RETURNING slug, title, description, books, view_count, created_at, updated_at;
                """,
                (slug, title, description, json.dumps(books, ensure_ascii=False)),
            )
            row = cur.fetchone()
            conn.commit()
            return _shared_shelf_from_row(row)
        raise RuntimeError("shared shelf slug generation failed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_shared_shelf_postgres(slug, increment_view=False):
    _require_shared_shelves_postgres_config()
    conn = get_db_conn()
    try:
        _ensure_shared_shelves_table(conn)
        if increment_view:
            cur = conn.execute(
                """
                UPDATE shared_shelves
                   SET view_count = view_count + 1
                 WHERE slug = ? AND deleted_at IS NULL
             RETURNING slug, title, description, books, view_count, created_at, updated_at;
                """,
                (slug,),
            )
            row = cur.fetchone()
            conn.commit()
            return _shared_shelf_from_row(row)
        cur = conn.execute(
            """
            SELECT slug, title, description, books, view_count, created_at, updated_at
              FROM shared_shelves
             WHERE slug = ? AND deleted_at IS NULL;
            """,
            (slug,),
        )
        return _shared_shelf_from_row(cur.fetchone())
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_shared_shelf(title, description, books):
    if _shared_shelves_use_postgres():
        return _create_shared_shelf_postgres(title, description, books)
    return _create_shared_shelf_json(title, description, books)


def _get_shared_shelf(slug, increment_view=False):
    if _shared_shelves_use_postgres():
        return _get_shared_shelf_postgres(slug, increment_view=increment_view)
    return _get_shared_shelf_json(slug, increment_view=increment_view)


def _normalize_shared_book(raw):
    if not isinstance(raw, dict):
        return None
    title = _clean_shared_text(raw.get("title"), 160)
    if not title:
        return None
    counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
    def _count_value(key):
        try:
            return max(0, int(counts.get(key) or 0))
        except Exception:
            return 0
    return {
        "key": _clean_shared_text(raw.get("key"), 160),
        "title": title,
        "author": _clean_shared_text(raw.get("author"), 120),
        "publisher": _clean_shared_text(raw.get("publisher"), 120),
        "image_url": _clean_shared_text(raw.get("image_url"), 500),
        "live_detail_key": _clean_shared_text(raw.get("live_detail_key"), 80),
        "live_detail_url": _clean_shared_text(raw.get("live_detail_url"), 500),
        "book_id": raw.get("book_id") if isinstance(raw.get("book_id"), int) else None,
        "counts": {
            "kyobo": _count_value("kyobo"),
            "yes24": _count_value("yes24"),
            "other": _count_value("other"),
            "total": _count_value("total"),
        },
        "note": _clean_shared_text(raw.get("note"), 500),
    }


def _shared_shelf_public_url(slug):
    return _public_url(f"/shelf/{slug}")


def _sitemap_base_url():
    base = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("SITEMAP_BASE_URL")
    if base:
        return base.rstrip("/")
    return request.url_root.rstrip("/")


def _public_url(path="/"):
    base = _sitemap_base_url()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def _seo_book_live_detail_url(book):
    params = {
        "title": book["title"],
        "author": book.get("author") or "",
        "publisher": book.get("publisher") or "",
    }
    return f"/api/live_book_detail?{urlencode(params)}"


def _seo_book_structured_data(book, canonical_url):
    data = {
        "@context": "https://schema.org",
        "@type": "Book",
        "name": book["title"],
        "url": canonical_url,
        "description": book["summary"],
    }
    if book.get("author"):
        data["author"] = {"@type": "Person", "name": book["author"]}
    if book.get("publisher"):
        data["publisher"] = {"@type": "Organization", "name": book["publisher"]}
    return data


def _sitemap_stats():
    now = time.time()
    cached = SITEMAP_CACHE
    if cached["pages"] and (now - cached["ts"]) < SITEMAP_TTL_SEC:
        return cached["count"], cached["pages"]
    if not legacy_db_available():
        SITEMAP_CACHE.update({"ts": now, "count": 0, "pages": 0})
        return 0, 0
    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[db warning] sitemap book index unavailable: {e}")
        SITEMAP_CACHE.update({"ts": now, "count": 0, "pages": 0})
        return 0, 0
    try:
        cur = conn.execute("SELECT COUNT(*) AS count FROM books;")
        row = cur.fetchone()
        total = row["count"] if row and row.get("count") is not None else 0
    except Exception as e:
        print(f"[db warning] sitemap book index unavailable: {e}")
        total = 0
    finally:
        conn.close()
    pages = (total + SITEMAP_PAGE_SIZE - 1) // SITEMAP_PAGE_SIZE if total else 0
    SITEMAP_CACHE.update({"ts": now, "count": total, "pages": pages})
    return total, pages


def _sitemap_page_ids(page: int):
    now = time.time()
    cached = SITEMAP_PAGE_CACHE.get(page)
    if cached and (now - cached["ts"]) < SITEMAP_TTL_SEC:
        return cached["ids"]
    if not legacy_db_available():
        return []
    offset = (page - 1) * SITEMAP_PAGE_SIZE
    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[db warning] sitemap book page unavailable: {e}")
        return []
    try:
        cur = conn.execute(
            "SELECT id FROM books ORDER BY id LIMIT ? OFFSET ?",
            (SITEMAP_PAGE_SIZE, offset),
        )
        rows = cur.fetchall()
        ids = [r["id"] if isinstance(r, dict) else r[0] for r in rows]
    except Exception as e:
        print(f"[db warning] sitemap book page unavailable: {e}")
        ids = []
    finally:
        conn.close()
    SITEMAP_PAGE_CACHE[page] = {"ts": now, "ids": ids}
    return ids




def get_counts():
    lib_total = len(LIBRARIES)
    book_total = None
    if using_postgres() or os.path.exists(DB_PATH):
        conn = None
        try:
            conn = get_db_conn()
            cur = conn.execute("SELECT COUNT(*) FROM books;")
            row = cur.fetchone()
            if using_postgres():
                book_total = row["count"] if row else 0
            else:
                book_total = row[0] if row else 0
        except Exception as e:
            print(f"[db warning] book count unavailable: {e}")
        finally:
            if conn:
                conn.close()
    return lib_total, book_total


def get_book_detail(book_id: int):
    conn = get_db_conn()
    try:
        cur = conn.execute(
            "SELECT id, title, author, publisher, image_url, isbn, merge_group_id, canonical_id, publisher_norm "
            "FROM books WHERE id=?",
            (book_id,),
        )
        book = cur.fetchone()
        if not book:
            return None
        merge_group_id = book.get("merge_group_id") if isinstance(book, dict) else book["merge_group_id"]
        canonical_id = book.get("canonical_id") if isinstance(book, dict) else book["canonical_id"]
        publisher_norm = book.get("publisher_norm") if isinstance(book, dict) else book["publisher_norm"]

        optional_cols = ["brcd", "ctts_dvsn_code", "ctgr_id", "sntn_auth_code", "goods_id", "content_id"]
        available = _get_holdings_columns(conn)
        selected_optional = [col for col in optional_cols if col in available]
        base_cols = ["library_code", "library", "provider", "platform", "image_url", "isbn"]
        columns_sql = ", ".join(base_cols + selected_optional)
        ids = []
        params = []
        if merge_group_id:
            where = "merge_group_id = ?"
            params.append(merge_group_id)
        elif canonical_id:
            where = "canonical_id = ?"
            params.append(canonical_id)
        else:
            where = "id = ?"
            params.append(book_id)
        if publisher_norm is None:
            where = f"{where} AND publisher_norm IS NULL"
        else:
            where = f"{where} AND publisher_norm = ?"
            params.append(publisher_norm)
        bcur = conn.execute(f"SELECT id FROM books WHERE {where}", params)
        ids = [r["id"] for r in bcur.fetchall()]
        if not ids:
            ids = [book_id]
        placeholders = ",".join("?" for _ in ids)
        hcur = conn.execute(
            f"SELECT {columns_sql} FROM holdings WHERE book_id IN ({placeholders})",
            ids,
        )
        holdings = [dict(r) for r in hcur.fetchall()]

        # Deduplicate by library_code, prefer rows with more identifiers.
        best_by_code = {}
        for h in holdings:
            lib_code = (h.get("library_code") or "").strip()
            score = 0
            for key in ("content_id", "goods_id", "brcd", "ctts_dvsn_code", "ctgr_id", "sntn_auth_code"):
                if (h.get(key) or "").strip():
                    score += 1
            prev = best_by_code.get(lib_code)
            if not prev or score > prev["score"]:
                best_by_code[lib_code] = {"score": score, "row": h}
        deduped_holdings = [v["row"] for v in best_by_code.values()]

        libraries = []
        for h in deduped_holdings:
            lib_code = (h.get("library_code") or "").strip()
            meta = LIB_META_BY_CODE.get(lib_code)
            if not meta:
                meta = {
                    "code": lib_code or None,
                    "name": h.get("library") or lib_code,
                    "short": LIBRARY_SHORT.get(lib_code, h.get("library") or lib_code),
                    "homepage_url": "#",
                    "platform_code": "Unknown",
                    "platform_label": "기타",
                    "service_type": "Unknown",
                }
            entry = dict(meta)
            entry["platform_code"] = h.get("platform") or entry.get("platform_code") or "Unknown"
            entry["image_url"] = h.get("image_url") or ""
            entry["isbn"] = h.get("isbn") or ""
            entry["brcd"] = h.get("brcd") or ""
            entry["ctts_dvsn_code"] = h.get("ctts_dvsn_code") or ""
            entry["ctgr_id"] = h.get("ctgr_id") or ""
            entry["sntn_auth_code"] = h.get("sntn_auth_code") or ""
            entry["goods_id"] = h.get("goods_id") or ""
            entry["content_id"] = h.get("content_id") or ""
            if entry["platform_code"] in {"Kyobo", "Kyobo_New"}:
                params = {
                    "cttsDvsnCode": entry["ctts_dvsn_code"],
                    "brcd": entry["brcd"],
                    "ctgrId": entry["ctgr_id"],
                }
                if entry["sntn_auth_code"]:
                    params["sntnAuthCode"] = entry["sntn_auth_code"]
                if all(params.values()):
                    entry["detail_url"] = build_kyobo_detail_url(lib_code, params)
            if lib_code == "dobong" and entry["brcd"]:
                entry["detail_url"] = (
                    "https://elib.dobong.kr/Kyobo_T3_Mobile/Phone/Main/Ebook_Detail.asp"
                    f"?type=EBOOK&barcode={entry['brcd']}&classCode=&keyWord=&product_cd=001"
                    "&kiduse_yn=N&borrowRadio=&sortType=1"
                )
            if entry["platform_code"] == "YES24" and entry["goods_id"]:
                base_url = yes24_base_url(lib_code)
                if base_url:
                    entry["detail_url"] = f"{base_url}/ebook/detail/?goods_id={entry['goods_id']}"
            if entry["platform_code"] == "Bookcube" and entry["content_id"]:
                base_url = bookcube_base_url(lib_code)
                if base_url:
                    entry["detail_url"] = f"{base_url}/FxLibrary/product/view/?num={entry['content_id']}&category=&category_type=book"
            if lib_code == "gangnam" and entry["content_id"]:
                base_url = bookcube_base_url(lib_code)
                if base_url:
                    entry["detail_url"] = f"{base_url}/elibbook/book_detail.asp?book_num={entry['content_id']}"
            if lib_code == "seoul" and entry["content_id"]:
                entry["detail_url"] = f"https://elib.seoul.go.kr/contents/detail?no={entry['content_id']}"
            if lib_code == "sen_owned" and entry["content_id"]:
                entry["detail_url"] = f"https://e-lib.sen.go.kr/contents/detail?no={entry['content_id']}&type=TY01"
            if lib_code == "sen_subs" and entry["content_id"]:
                entry["detail_url"] = f"https://e-lib.sen.go.kr/contents/detail?no={entry['content_id']}&type=TY02"
            if lib_code == "eunpyeong" and entry["content_id"]:
                entry["detail_url"] = (
                    "https://epbook.eplib.or.kr/ebookPlatform/home/detail.do"
                    f"?no={entry['content_id']}"
                )
            libraries.append(entry)

        def _entry_key(item):
            return (
                item.get("code") or item.get("name") or "",
                item.get("platform_code") or "Unknown",
                item.get("service_type") or "Unknown",
            )

        def _entry_score(item):
            score = 0
            platform = item.get("platform_code") or "Unknown"
            if platform in {"Kyobo", "Kyobo_New"}:
                score += 2 if item.get("brcd") else 0
                score += 1 if item.get("ctts_dvsn_code") else 0
                score += 1 if item.get("ctgr_id") else 0
            elif platform == "YES24":
                score += 2 if item.get("goods_id") else 0
            else:
                score += 2 if item.get("content_id") else 0
            score += 1 if item.get("image_url") else 0
            score += 1 if item.get("isbn") else 0
            score += 1 if item.get("detail_url") else 0
            return score

        deduped = {}
        for item in libraries:
            key = _entry_key(item)
            prev = deduped.get(key)
            if not prev or _entry_score(item) > _entry_score(prev):
                deduped[key] = item
        libraries = [item for item in deduped.values() if _entry_score(item) > 0]

        kyobo_count = 0
        yes24_count = 0
        other_count = 0
        for item in libraries:
            platform = item.get("platform_code") or "Unknown"
            if platform in {"Kyobo", "Kyobo_New"}:
                kyobo_count += 1
            elif platform == "YES24":
                yes24_count += 1
            else:
                other_count += 1

        return {
            "id": book["id"],
            "title": clean_display_title(book["title"] or ""),
            "author": book["author"] or "",
            "publisher": book["publisher"] or "",
            "image_url": book["image_url"] or "",
            "isbn": book["isbn"] or "",
            "libraries": libraries,
            "counts": {
                "kyobo": kyobo_count,
                "yes24": yes24_count,
                "other": other_count,
                "total": len(libraries),
            },
        }
    finally:
        conn.close()


def get_book_meta(book_id: int):
    conn = get_db_conn()
    try:
        cur = conn.execute(
            "SELECT id, title, author, publisher, image_url, isbn FROM books WHERE id=?",
            (book_id,),
        )
        book = cur.fetchone()
        if not book:
            return None
        return {
            "id": book["id"],
            "title": clean_display_title(book["title"] or ""),
            "author": book["author"] or "",
            "publisher": book["publisher"] or "",
            "image_url": book["image_url"] or "",
            "isbn": book["isbn"] or "",
            "libraries": [],
            "counts": {"kyobo": 0, "yes24": 0, "other": 0, "total": 0},
        }
    finally:
        conn.close()


LIB_NAME_LOOKUP = {}
for code, info in LIBRARIES.items():
    lib_name = info["library_name"]
    short = LIBRARY_SHORT.get(code, lib_name)
    platform_code = info.get("platform", "Unknown")
    platform_label = PLATFORM_LABELS.get(platform_code, "기타")
    LIB_NAME_LOOKUP[lib_name] = {"short": short, "platform_code": platform_code, "platform_label": platform_label}

LIB_META_BY_CODE = {}
for code, info in LIBRARIES.items():
    lib_name = info["library_name"]
    platform_code = info.get("platform", "Unknown")
    LIB_META_BY_CODE[code] = {
        "code": code,
        "name": lib_name,
        "short": LIBRARY_SHORT.get(code, lib_name),
        "homepage_url": info.get("homepage_url", "#"),
        "content_path": info.get("content_path", ""),
        "platform_code": platform_code,
        "platform_label": PLATFORM_LABELS.get(platform_code, "기타"),
        "service_type": info.get("service_type", "Unknown"),
    }


LIB_SHORT_TO_CODES = {}
for code, info in LIBRARIES.items():
    short = LIBRARY_SHORT.get(code, info.get("library_name") or code)
    LIB_SHORT_TO_CODES.setdefault(short, set()).add(code)
LIB_SHORT_TO_CODES = {k: sorted(v) for k, v in LIB_SHORT_TO_CODES.items()}

PROVIDER_LABEL_TO_PLATFORMS = {}
for code, label in PLATFORM_LABELS.items():
    if code in {"Kyobo", "Kyobo_New"}:
        label = "교보"
    if code == "Bookcube":
        label = "기타"
    if code == "Aladin":
        label = "알라딘"
    PROVIDER_LABEL_TO_PLATFORMS.setdefault(label, set()).add(code)
if "기타" not in PROVIDER_LABEL_TO_PLATFORMS:
    PROVIDER_LABEL_TO_PLATFORMS["기타"] = {"FxLibrary", "Mixed", "Unknown"}


@app.route('/')
def index():
    seo_pool = get_seo_books()
    seo_badges = random.sample(seo_pool, min(5, len(seo_pool)))
    return render_template(
        "index.html",
        seo_books=seo_badges,
        show_topbar=False,
        topbar_desc="",
        active_tab="home",
    )


@app.route('/search')



def search_page():
    return render_template(
        "search.html",
        library_count=len(LIBRARIES),
        book_count=None,
        lib_url_map={},
        show_topbar=False,
        topbar_desc="",
        active_tab="search",
    )


@app.route("/blog")
def blog_page():
    return render_template(
        "blog.html",
        posts=get_blog_posts(),
        show_topbar=False,
        topbar_desc="",
        active_tab="blog",
    )


def _blog_post_response(post, comment_error="", saved_comment=None, status_code=200):
    comments = []
    comments_unavailable = False
    comments_notice = ""
    try:
        comments = get_blog_comments(post["slug"])
    except Exception as exc:
        comments_unavailable = True
        comments_notice = "댓글 목록을 잠시 불러오지 못했습니다."
        print(f"[blog comment warning] list unavailable for {post['slug']}: {exc}")

    if saved_comment:
        saved_id = saved_comment.get("id")
        comments = [
            saved_comment,
            *[comment for comment in comments if comment.get("id") != saved_id],
        ]

    return render_template(
        "blog_post.html",
        post=post,
        comments=comments,
        comments_unavailable=comments_unavailable,
        comments_notice=comments_notice,
        comment_error=comment_error,
        saved_comment=saved_comment,
        show_topbar=False,
        topbar_desc="",
        active_tab="blog",
        canonical_url=_public_url(f"/blog/{post['slug']}"),
        meta_title=f"{post['title']} - Soulib 블로그",
        meta_description=post.get("description") or "",
        og_title=f"{post['title']} - Soulib 블로그",
        og_description=post.get("description") or "",
    ), status_code


@app.route("/blog/<slug>", methods=["GET", "POST"])
def blog_post_page(slug):
    post = get_blog_post(slug)
    if not post:
        abort(404)
    if request.method == "POST":
        if (request.form.get("website") or "").strip():
            return redirect(url_for("blog_post_page", slug=post["slug"]))
        author = request.form.get("author") or ""
        message = request.form.get("message") or ""
        try:
            comment = create_blog_comment(
                post["slug"],
                post["title"],
                author,
                message,
                request.headers.get("User-Agent") or "",
            )
            return _blog_post_response(post, saved_comment=comment, status_code=201)
        except ValueError as exc:
            return _blog_post_response(post, comment_error=str(exc), status_code=400)
        except Exception as exc:
            print(f"[blog comment error] create failed for {post['slug']}: {exc}")
            return _blog_post_response(
                post,
                comment_error="댓글을 저장하지 못했습니다. 잠시 후 다시 시도해주세요.",
                status_code=500,
            )
    return _blog_post_response(post)


@app.route("/discover")
def discover_page():
    return redirect(url_for("blog_page"), code=301)


@app.route("/books/<slug>")
def seo_book_page(slug):
    seo_book = get_seo_book_by_slug(slug)
    if not seo_book:
        abort(404)

    canonical_url = _public_url(f"/books/{slug}")
    target = {
        "title": seo_book["title"],
        "author": seo_book.get("author") or "",
        "publisher": seo_book.get("publisher") or "",
    }
    book = {
        **target,
        "image_url": "",
        "counts": {"kyobo": 0, "yes24": 0, "other": 0, "total": 0},
        "libraries": [],
        "library_groups": [],
        "counts_partial": True,
    }
    detail_hydrate_url = _seo_book_live_detail_url(seo_book)
    meta_title = f"{seo_book['title']} 전자도서관 검색 - 서울 전자도서관 통합검색"
    return render_template(
        "live_book.html",
        book=book,
        seo_book=seo_book,
        error=None,
        detail_hydrate_url=detail_hydrate_url,
        show_topbar=False,
        topbar_desc="",
        active_tab="search",
        canonical_url=canonical_url,
        meta_title=meta_title,
        meta_description=seo_book["summary"],
        og_title=meta_title,
        og_description=seo_book["summary"],
        og_url=canonical_url,
        structured_data=_seo_book_structured_data(seo_book, canonical_url),
    )


@app.route('/my-shelf')
def my_shelf_page():
    return render_template(
        "my_shelf.html",
        show_topbar=False,
        topbar_desc="",
        active_tab="shelf",
    )


@app.route("/api/shelves/share", methods=["POST"])
def api_share_shelf():
    payload = request.get_json(silent=True) or {}
    list_meta = payload.get("list") if isinstance(payload.get("list"), dict) else {}
    books_raw = payload.get("books") if isinstance(payload.get("books"), list) else []
    books = []
    seen = set()
    for raw in books_raw[:MAX_SHARED_SHELF_BOOKS]:
        book = _normalize_shared_book(raw)
        if not book:
            continue
        dedupe_key = book.get("key") or f"{book['title']}|{book.get('author')}|{book.get('publisher')}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        books.append(book)
    if not books:
        return jsonify({"error": "공유할 책이 없습니다."}), 400

    title = _clean_shared_text(list_meta.get("name") or payload.get("title"), 80) or "공유 서재"
    description = _clean_shared_text(list_meta.get("description") or payload.get("description"), 300)
    try:
        shelf = _create_shared_shelf(title, description, books)
    except Exception as e:
        print(f"[shelf error] shared shelf create failed: {e}")
        print(traceback.format_exc())
        return jsonify({"error": "공유 서재 저장소에 연결하지 못했습니다."}), 503
    return jsonify({"slug": shelf["slug"], "url": _shared_shelf_public_url(shelf["slug"]), "shelf": shelf}), 201


@app.route("/shelf/<slug>")
def shared_shelf_page(slug):
    slug = _clean_shared_text(slug, 40)
    try:
        shelf = _get_shared_shelf(slug, increment_view=True)
    except Exception as e:
        print(f"[shelf error] shared shelf read failed: {e}")
        print(traceback.format_exc())
        return render_template(
            "shared_shelf.html",
            shelf=None,
            error="공유 서재 저장소에 연결하지 못했습니다.",
            show_topbar=False,
            topbar_desc="",
            active_tab="shelf",
        ), 503
    if not shelf:
        return render_template(
            "shared_shelf.html",
            shelf=None,
            error="공유 서재를 찾지 못했습니다.",
            show_topbar=False,
            topbar_desc="",
            active_tab="shelf",
        ), 404
    return render_template(
        "shared_shelf.html",
        shelf=shelf,
        error=None,
        show_topbar=False,
        topbar_desc="",
        active_tab="shelf",
    )


@app.route('/robots.txt')
def robots_txt():
    return send_from_directory(os.path.join(app.root_path, "static"), "robots.txt")


@app.route("/favicon.ico")
def favicon_ico():
    return send_from_directory(os.path.join(app.root_path, "static", "img"), "favicon.ico")


@app.route("/sitemap.xml")
def sitemap_index():
    base = _sitemap_base_url()
    _, pages = _sitemap_stats()
    today = time.strftime("%Y-%m-%d")
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    parts.append(f"<sitemap><loc>{base}/sitemap-static.xml</loc><lastmod>{today}</lastmod></sitemap>")
    for page in range(1, pages + 1):
        parts.append(
            f"<sitemap><loc>{base}/sitemap-books-{page}.xml</loc><lastmod>{today}</lastmod></sitemap>"
        )
    parts.append("</sitemapindex>")
    xml = "\n".join(parts)
    return Response(xml, mimetype="application/xml")


@app.route("/sitemap-static.xml")
def sitemap_static():
    base = _sitemap_base_url()
    today = time.strftime("%Y-%m-%d")
    urls = [f"{base}/", f"{base}/search", f"{base}/blog", f"{base}/reports"]
    urls.extend(f"{base}/blog/{post['slug']}" for post in get_blog_posts())
    urls.extend(f"{base}/books/{book['slug']}" for book in get_seo_books())
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for url in urls:
        parts.append(f"<url><loc>{url}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>")
    parts.append("</urlset>")
    xml = "\n".join(parts)
    return Response(xml, mimetype="application/xml")


@app.route("/sitemap-books-<int:page>.xml")
def sitemap_books(page: int):
    _, pages = _sitemap_stats()
    if page < 1 or page > pages:
        return Response("not found", status=404, mimetype="text/plain")
    base = _sitemap_base_url()
    today = time.strftime("%Y-%m-%d")
    ids = _sitemap_page_ids(page)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    parts.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for book_id in ids:
        parts.append(
            f"<url><loc>{base}/book/{book_id}</loc>"
            f"<lastmod>{today}</lastmod><changefreq>weekly</changefreq></url>"
        )
    parts.append("</urlset>")
    xml = "\n".join(parts)
    return Response(xml, mimetype="application/xml")


@app.route('/naver502d24e941f50b3d3341745ef4de5f43.html')
def naver_verify():
    return send_from_directory(os.path.join(app.root_path, "static"), "naver502d24e941f50b3d3341745ef4de5f43.html")


@app.route('/naver520d24e941f50b3d3341745ef4de5f43.html')
def naver_verify_alt():
    return send_from_directory(os.path.join(app.root_path, "static"), "naver520d24e941f50b3d3341745ef4de5f43.html")


@app.route('/book/<int:book_id>')
def book_detail(book_id: int):
    if not legacy_db_available():
        return redirect(url_for("search_page"), code=301)
    try:
        detail = get_book_meta(book_id)
    except Exception as e:
        print(f"[db warning] legacy book detail unavailable for {book_id}: {e}")
        detail = None
    if not detail:
        return render_template(
            "book.html",
            book=None,
            error="이전 상세 페이지는 현재 지원하지 않습니다. 검색에서 다시 조회해주세요.",
            show_topbar=False,
            topbar_desc="",
            active_tab="search",
        ), 404
    return render_template(
        "book.html",
        book=detail,
        error=None,
        show_topbar=False,
        topbar_desc="",
        active_tab="search",
    )


@app.route("/api/book_libraries")
def api_book_libraries():
    raw_id = (request.args.get("book_id") or "").strip()
    try:
        book_id = int(raw_id)
    except Exception:
        return jsonify({"error": "invalid_book_id"}), 400

    if not legacy_db_available():
        return jsonify({"error": "legacy_detail_unavailable", "libraries": [], "counts": {}}), 404

    cached = LIB_DETAIL_CACHE.get(book_id)
    now = time.time()
    if cached and now - cached["ts"] < LIB_DETAIL_TTL_SEC:
        return jsonify(cached["payload"])

    try:
        detail = get_book_detail(book_id)
    except Exception as e:
        print(f"[db warning] legacy book libraries unavailable for {book_id}: {e}")
        return jsonify({"error": "legacy_detail_unavailable", "libraries": [], "counts": {}}), 404
    if not detail:
        return jsonify({"error": "not_found"}), 404
    payload = {
        "book_id": detail["id"],
        "counts": detail.get("counts") or {},
        "libraries": detail.get("libraries") or [],
    }
    LIB_DETAIL_CACHE[book_id] = {"ts": now, "payload": payload}
    return jsonify(payload)


@app.route('/api/search')
def search():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({"total": 0, "items": []})

    try:
        limit = int(request.args.get('limit', '20'))
    except ValueError:
        limit = 20
    try:
        offset = int(request.args.get('offset', '0'))
    except ValueError:
        offset = 0

    try:
        return jsonify(
            run_live_search(
                query=query,
                field=(request.args.get("field") or "title_author").strip(),
                providers_raw=(request.args.get("providers") or "").strip(),
                libraries_raw=(request.args.get("libraries") or "").strip(),
                limit=limit,
                offset=offset,
                refine=(request.args.get("refine") or "").strip(),
            )
        )
    except Exception as exc:
        print(f"[live search compatibility error] {exc}")
        print(traceback.format_exc())
        return jsonify({"error": "실시간 검색 처리 오류 발생", "total": 0, "items": []}), 502

    field = request.args.get('field', 'title_author')
    refine = request.args.get('refine', '').strip()
    query_tokens = normalize_search_tokens(query)
    if not query_tokens:
        return jsonify({"total": 0, "items": []})
    refine_tokens = normalize_search_tokens(refine) if refine else []
    providers_raw = request.args.get('providers', '').strip()
    libraries_raw = request.args.get('libraries', '').strip()
    providers_selected = [p for p in providers_raw.split(",") if p]
    libraries_selected = [l for l in libraries_raw.split(",") if l]

    try:
        limit = int(request.args.get('limit', '200'))
    except ValueError:
        limit = 200
    try:
        offset = int(request.args.get('offset', '0'))
    except ValueError:
        offset = 0
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    use_trgm = using_postgres()
    valid_holding_h = (
        "COALESCE(NULLIF(TRIM(h.image_url), ''), NULLIF(TRIM(h.isbn), ''), "
        "NULLIF(TRIM(h.brcd), ''), NULLIF(TRIM(h.goods_id), ''), NULLIF(TRIM(h.content_id), '')) IS NOT NULL"
    )
    valid_holding_h2 = (
        "COALESCE(NULLIF(TRIM(h2.image_url), ''), NULLIF(TRIM(h2.isbn), ''), "
        "NULLIF(TRIM(h2.brcd), ''), NULLIF(TRIM(h2.goods_id), ''), NULLIF(TRIM(h2.content_id), '')) IS NOT NULL"
    )

    def build_where(tokens):
        if not tokens:
            return "1=0", []
        groups = []
        params = []
        multi_token = len(tokens) > 1
        for token in tokens:
            pattern = f"%{token}%"
            clauses = []
            if use_trgm:
                if len(token) < 3 and not multi_token:
                    pattern = f"{token}%"
                if field in ("title", "title_author"):
                    clauses.append("(b.title_norm LIKE ?)")
                    params.append(pattern)
                if field in ("author", "title_author"):
                    clauses.append("(b.author_norm LIKE ?)")
                    params.append(pattern)
                if field == "publisher":
                    clauses.append("(b.publisher_norm LIKE ?)")
                    params.append(pattern)
            else:
                if field in ("title", "title_author"):
                    clauses.append("(b.title_norm LIKE ?)")
                    params.append(pattern)
                if field in ("author", "title_author"):
                    clauses.append("(b.author_norm LIKE ?)")
                    params.append(pattern)
                if field == "publisher":
                    clauses.append("(b.publisher_norm LIKE ?)")
                    params.append(pattern)
            if not clauses:
                clauses.append("(b.title_norm LIKE ?)")
                params.append(pattern)
            groups.append("(" + " OR ".join(clauses) + ")")
        return "(" + " AND ".join(groups) + ")", params

    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[search db warning] {e}")
        return jsonify({"error": "DB 연결 실패", "total": 0, "items": []}), 503
    try:
        where_sql, params = build_where(query_tokens)
        if refine_tokens:
            refine_sql, refine_params = build_where(refine_tokens)
            where_sql = f"{where_sql} AND {refine_sql}"
            params = params + refine_params
        filter_clauses = []
        filter_params = []
        if libraries_selected:
            lib_codes = []
            for label in libraries_selected:
                lib_codes.extend(LIB_SHORT_TO_CODES.get(label, []))
            if lib_codes:
                placeholders = ",".join("?" for _ in lib_codes)
                filter_clauses.append(f"h2.library_code IN ({placeholders})")
                filter_params.extend(lib_codes)
        if providers_selected:
            platform_codes = set()
            include_other = False
            for label in providers_selected:
                if label == "기타":
                    include_other = True
                platform_codes.update(PROVIDER_LABEL_TO_PLATFORMS.get(label, set()))
            provider_parts = []
            if platform_codes:
                placeholders = ",".join("?" for _ in sorted(platform_codes))
                provider_parts.append(f"h2.platform IN ({placeholders})")
                filter_params.extend(sorted(platform_codes))
            if include_other:
                other_platforms = sorted(PROVIDER_LABEL_TO_PLATFORMS.get("기타", set()))
                if other_platforms:
                    placeholders = ",".join("?" for _ in other_platforms)
                    provider_parts.append(f"h2.platform IN ({placeholders})")
                    filter_params.extend(other_platforms)
                provider_parts.append("(h2.platform IS NULL OR h2.platform = '')")
            if provider_parts:
                filter_clauses.append("(" + " OR ".join(provider_parts) + ")")

        if filter_clauses:
            where_sql = (
                f"{where_sql} AND EXISTS ("
                f"SELECT 1 FROM holdings h2 "
                f"WHERE h2.book_id = b.id AND {valid_holding_h2} AND {' AND '.join(filter_clauses)}"
                f")"
            )
            params = params + filter_params

        group_expr = "COALESCE(b.merge_group_id, b.canonical_id, CAST(b.id AS TEXT)) || ':' || COALESCE(b.publisher_norm, '')"
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM (
                SELECT DISTINCT {group_expr} AS group_id
                FROM books b
                WHERE {where_sql}
                  AND EXISTS (
                      SELECT 1 FROM holdings h
                      WHERE h.book_id = b.id
                        AND {valid_holding_h}
                  )
            ) t
            """,
            params,
        ).fetchone()
        total = count_row["total"] if count_row and count_row["total"] else 0

        trgm_query = "".join(query_tokens)
        order_sql = "lib_count DESC, b.title ASC"
        order_params = []
        if use_trgm and trgm_query:
            if field == "title":
                order_sql = "similarity(b.title_norm, ?) DESC, lib_count DESC, b.title ASC"
                order_params = [trgm_query]
            elif field == "author":
                order_sql = "similarity(b.author_norm, ?) DESC, lib_count DESC, b.title ASC"
                order_params = [trgm_query]
            elif field == "publisher":
                order_sql = "similarity(b.publisher_norm, ?) DESC, lib_count DESC, b.title ASC"
                order_params = [trgm_query]
            else:
                order_sql = "GREATEST(similarity(b.title_norm, ?), similarity(b.author_norm, ?)) DESC, lib_count DESC, b.title ASC"
                order_params = [trgm_query, trgm_query]

        paged_sql = f"""
            WITH group_books AS (
                SELECT b.id, {group_expr} AS group_id
                FROM books b
                WHERE {where_sql}
            ),
            rep AS (
                SELECT
                    gb.group_id,
                    COALESCE(
                        MIN(CASE WHEN b.canonical_id = b.merge_group_id THEN b.id END),
                        MIN(b.id)
                    ) AS rep_id
                FROM books b
                JOIN group_books gb ON gb.id = b.id
                GROUP BY gb.group_id
            )
            SELECT
                b.id,
                b.title,
                b.author,
                b.publisher,
                COALESCE(NULLIF(b.image_url, ''), MAX(NULLIF(h.image_url, ''))) AS image_url,
                COUNT(DISTINCT h.library_code) AS lib_count,
                COUNT(DISTINCT CASE
                    WHEN h.platform IN ('Kyobo', 'Kyobo_New') THEN h.library_code
                END) AS kyobo_count,
                COUNT(DISTINCT CASE
                    WHEN h.platform = 'YES24' THEN h.library_code
                END) AS yes24_count,
                COUNT(DISTINCT CASE
                    WHEN h.library_code IS NOT NULL
                        AND (h.platform IS NULL OR h.platform = '' OR h.platform NOT IN ('Kyobo', 'Kyobo_New', 'YES24'))
                    THEN h.library_code
                END) AS other_count
            FROM rep r
            JOIN books b ON b.id = r.rep_id
            LEFT JOIN group_books gb ON gb.group_id = r.group_id
            LEFT JOIN holdings h ON h.book_id = gb.id AND {valid_holding_h}
            GROUP BY b.id, b.title, b.author, b.publisher, b.image_url
            HAVING COUNT(DISTINCT h.library_code) > 0
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
        """
        paged_params = params + order_params + [limit, offset]
        cur = conn.execute(paged_sql, paged_params)
        rows = cur.fetchall()

        filter_providers = []
        filter_libraries = []
        if total > 0:
            providers = set()
            libraries = set()
            pcur = conn.execute(
                f"""
                WITH group_books AS (
                    SELECT b.id
                    FROM books b
                    WHERE {where_sql}
                )
                SELECT DISTINCT h.platform
                FROM holdings h
                JOIN group_books gb ON gb.id = h.book_id
                WHERE {valid_holding_h}
                """,
                params,
            )
            for r in pcur.fetchall():
                raw = r["platform"] if using_postgres() else r[0]
                providers.add(platform_to_provider_label(raw))
            lcur = conn.execute(
                f"""
                WITH group_books AS (
                    SELECT b.id
                    FROM books b
                    WHERE {where_sql}
                )
                SELECT DISTINCT h.library_code, h.library
                FROM holdings h
                JOIN group_books gb ON gb.id = h.book_id
                WHERE {valid_holding_h}
                """,
                params,
            )
            for r in lcur.fetchall():
                if using_postgres():
                    code = r.get("library_code")
                    name = r.get("library")
                else:
                    code = r[0] if len(r) > 0 else None
                    name = r[1] if len(r) > 1 else None
                if code:
                    meta = LIB_META_BY_CODE.get(code)
                    libraries.add(meta.get("short") if meta else code)
                elif name:
                    meta = LIB_NAME_LOOKUP.get(name)
                    libraries.add(meta.get("short") if meta else name)
            filter_providers = sorted(providers)
            filter_libraries = sorted(libraries)

        results = []
        for row in rows:
            kyobo_count = row.get("kyobo_count") or 0
            yes24_count = row.get("yes24_count") or 0
            other_count = row.get("other_count") or 0
            total_libs = row.get("lib_count") or (kyobo_count + yes24_count + other_count)
            results.append({
                "book_id": row["id"],
                "title": clean_display_title(row["title"] or ""),
                "author": row["author"] or "",
                "publisher": row["publisher"] or "",
                "image_url": row["image_url"] or "",
                "counts": {
                    "kyobo": kyobo_count,
                    "yes24": yes24_count,
                    "other": other_count,
                    "total": total_libs,
                },
            })
        return jsonify({"total": total, "items": results, "filters": {"providers": filter_providers, "libraries": filter_libraries}})
    except Exception as e:
        print(f"[status error] {e}")
        print(traceback.format_exc())
        print(f"[오류] 검색 실패: {e}")
        print(traceback.format_exc())
        return jsonify({"error": "검색 처리 오류 발생"})
    finally:
        conn.close()


@app.route("/api/books")
def api_books():
    raw_ids = (request.args.get("ids") or "").strip()
    if not raw_ids:
        return jsonify([])

    if not legacy_db_available():
        return jsonify([])

    ids = []
    for part in raw_ids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue

    if not ids:
        return jsonify([])

    try:
        conn = get_db_conn()
    except Exception as e:
        print(f"[books db warning] {e}")
        return jsonify([])
    try:
        placeholders = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"""
            SELECT id, title, author, publisher, image_url, merge_group_id, canonical_id, publisher_norm
            FROM books
            WHERE id IN ({placeholders})
            """,
            ids,
        )
        rows = cur.fetchall()
        by_id = {}
        for row in rows:
            row_id = row.get("id")
            if row_id is not None:
                by_id[int(row_id)] = row

        results = []
        seen_groups = set()
        for requested_id in ids:
            r = by_id.get(requested_id)
            if not r:
                continue
            group_id = r.get("merge_group_id") or r.get("canonical_id") or r.get("id")
            publisher_norm = r.get("publisher_norm") or ""
            group_key = f"{group_id}:{publisher_norm}"
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)
            results.append(
                {
                    "book_id": r["id"],
                    "title": clean_display_title(r["title"] or ""),
                    "author": r["author"] or "",
                    "publisher": r["publisher"] or "",
                    "image_url": r["image_url"] or "",
                }
            )
        return jsonify(results)
    finally:
        conn.close()


if __name__ == '__main__':
    port = int(os.environ.get("LIBRARY_SEARCH_PORT") or os.environ.get("PORT", "5001"))
    app.run(host='0.0.0.0', port=port)
