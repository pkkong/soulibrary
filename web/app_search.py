import os
import json
import re
import time
import traceback
from db import get_db, using_postgres
from pathlib import Path
from urllib.parse import urlparse, urlencode
from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
from config import LIBRARIES, PLATFORM_LABELS, LIBRARY_SHORT

app = Flask(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT_DIR, "data", "library_split.db")
LEGACY_DB = os.path.join(ROOT_DIR, "data", "library.db")
DB_PATH = os.environ.get("LIBRARY_DB_PATH", DEFAULT_DB if os.path.exists(DEFAULT_DB) else LEGACY_DB)
STATUS_TTL_SEC = int(os.environ.get("KYOBO_STATUS_TTL", "120"))
STATUS_CACHE = {}


def get_db_conn():
    return get_db(DB_PATH)


def normalize_title(text):
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"\[.*?\]|\(.*?\)", "", text)
    text = re.sub(r"(\d)\s*(권|冊|권수)", r"\1", text)
    text = re.sub(r"[^\w\s]", "", text).strip()
    text = re.sub(r"\s+", "", text)
    return text


def normalize_author(text):
    if not text:
        return ""
    text = str(text)
    text = re.sub(r"[<>\(\)\[\]]", " ", text)
    split_chars = r"[,/|]"
    if re.search(split_chars, text):
        text = re.split(split_chars, text, 1)[0]
    roles = r"(지음|글|그림|그림책|옮김|엮음|편집)"
    text = re.sub(roles, "", text)
    text = re.sub(r"[^\w\s]", "", text).lower().strip()
    text = re.sub(r"\s+", "", text)
    return text


def normalize_search_text(text: str) -> str:
    if not text:
        return ""
    text = str(text).lower().strip()
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[\s\[\]\(\){}<>.,/|\\\-_:\;\"'`~!?]", "", text)
    return text


def normalize_search_tokens(text: str) -> list[str]:
    if not text:
        return []
    raw = str(text).lower().strip()
    raw = re.sub(r"[\u200b\ufeff]", "", raw)
    parts = re.split(r"[\s\[\]\(\){}<>.,/|\\\-_:\;\"'`~!?]+", raw)
    tokens = []
    for part in parts:
        norm = normalize_search_text(part)
        if norm:
            tokens.append(norm)
    return tokens


def normalize_provider(raw_value):
    mapping = {
        "교보문고": "교보",
        "교보": "교보",
        "kyobo": "교보",
        "교보도서관": "교보",
        "yes24": "YES24",
        "YES24": "YES24",
        "예스24": "YES24",
        "예스이십사": "YES24",
        "예스": "YES24",
        "aladin": "알라딘",
        "알라딘": "알라딘",
    }
    if raw_value:
        key = str(raw_value).strip()
        norm = mapping.get(key) or mapping.get(key.lower())
        return norm or key
    return ""


def provider_from_platforms(platforms):
    for code in platforms:
        if code in {"Kyobo", "Kyobo_New"}:
            return "교보"
        if code == "YES24":
            return "YES24"
        if code == "Aladin":
            return "알라딘"
        if code == "Bookcube":
            return "북큐브"
    return "기타"





def platform_to_provider_label(platform_code: str) -> str:
    if not platform_code:
        return "기타"
    code = str(platform_code)
    if code in {"Kyobo", "Kyobo_New"}:
        return "교보"
    if code == "YES24":
        return "YES24"
    if code == "Bookcube":
        return "북큐브"
    if code == "Aladin":
        return "알라딘"
    return "기타"


def _kyobo_base_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code)
    if not info:
        return ""
    raw_url = info.get("homepage_url") or info.get("url_prefix") or info.get("total_count_url")
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _parse_kyobo_status(html: str):
    if not html:
        return None
    match = re.search(r'<p class="use">.*?</p>', html, re.S)
    text = match.group(0) if match else html
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    numbers = re.search(r"대출\s*:\s*([\d,]+)\s*/\s*([\d,]+)\s*예약\s*:\s*([\d,]+)", text)
    if not numbers:
        return None
    loaned = int(numbers.group(1).replace(",", ""))
    total = int(numbers.group(2).replace(",", ""))
    reserved = int(numbers.group(3).replace(",", ""))
    return {"loaned": loaned, "total": total, "reserved": reserved}
def get_counts():
    lib_total = len(LIBRARIES)
    book_total = None
    if using_postgres() or os.path.exists(DB_PATH):
        conn = get_db_conn()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM books;")
            row = cur.fetchone()
            if using_postgres():
                book_total = row["count"] if row else 0
            else:
                book_total = row[0] if row else 0
        finally:
            conn.close()
    return lib_total, book_total


def get_holdings_total():
    total = None
    if using_postgres() or os.path.exists(DB_PATH):
        conn = get_db_conn()
        try:
            cur = conn.execute("SELECT COUNT(*) AS count FROM holdings;")
            row = cur.fetchone()
            if using_postgres():
                total = row["count"] if row else 0
            else:
                total = row[0] if row else 0
        finally:
            conn.close()
    return total


def get_library_holdings_counts():
    results = []
    if using_postgres() or os.path.exists(DB_PATH):
        conn = get_db_conn()
        try:
            cur = conn.execute(
                "SELECT library, COUNT(*) AS count FROM holdings "
                "WHERE library IS NOT NULL AND library != '' "
                "GROUP BY library;"
            )
            rows = cur.fetchall()
            if using_postgres():
                results = [
                    {"library": r.get("library") or "", "count": r.get("count") or 0}
                    for r in rows
                ]
            else:
                results = [{"library": r[0] or "", "count": r[1] or 0} for r in rows]
        finally:
            conn.close()
    return results


def get_book_detail(book_id: int):
    conn = get_db_conn()
    try:
        cur = conn.execute(
            "SELECT id, title, author, publisher, image_url, isbn FROM books WHERE id=?",
            (book_id,),
        )
        book = cur.fetchone()
        if not book:
            return None

        hcur = conn.execute(
            "SELECT library_code, library, provider, platform, image_url, isbn FROM holdings WHERE book_id=?",
            (book_id,),
        )
        holdings = [dict(r) for r in hcur.fetchall()]

        kyobo_count = 0
        yes24_count = 0
        other_count = 0
        libraries = []
        for h in holdings:
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
                }
            entry = dict(meta)
            entry["platform_code"] = h.get("platform") or entry.get("platform_code") or "Unknown"
            libraries.append(entry)
            platform = entry.get("platform_code") or "Unknown"
            if platform in {"Kyobo", "Kyobo_New"}:
                kyobo_count += 1
            elif platform == "YES24":
                yes24_count += 1
            else:
                other_count += 1

        return {
            "id": book["id"],
            "title": book["title"] or "",
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
        "platform_code": platform_code,
        "platform_label": PLATFORM_LABELS.get(platform_code, "기타"),
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
        label = "북큐브"
    if code == "Aladin":
        label = "알라딘"
    PROVIDER_LABEL_TO_PLATFORMS.setdefault(label, set()).add(code)
if "기타" not in PROVIDER_LABEL_TO_PLATFORMS:
    PROVIDER_LABEL_TO_PLATFORMS["기타"] = {"FxLibrary", "Mixed", "Unknown"}


@app.route('/')
def index():
    lib_total, book_total = get_counts()
    desc = ""
    if lib_total:
        desc = f"{lib_total}개 도서관"
    return render_template(
        'index.html',
        library_count=lib_total,
        book_count=book_total,
        lib_url_map={},
        show_topbar=True,
        topbar_desc=desc,
        active_tab="home",
    )


@app.route('/search')



def search_page():
    lib_total, book_total = get_counts()
    desc = ""
    if lib_total:
        desc = f"{lib_total}개 도서관"
    return render_template(
        "search.html",
        library_count=lib_total,
        book_count=book_total,
        lib_url_map={},
        show_topbar=False,
        topbar_desc="",
        active_tab="search",
    )


@app.route('/guide')
def guide_page():
    lib_total, book_total = get_counts()
    holdings_total = get_holdings_total()
    library_counts = get_library_holdings_counts()
    library_counts = sorted(library_counts, key=lambda item: (item.get("library") or ""))
    library_url_map = {info.get("library_name"): info.get("homepage_url") for info in LIBRARIES.values()}
    return render_template(
        "guide.html",
        library_count=lib_total,
        book_count=book_total,
        holdings_total=holdings_total,
        library_counts=library_counts,
        library_url_map=library_url_map,
        show_topbar=True,
        topbar_desc=f"{lib_total}개 도서관" if lib_total else "",
        active_tab="guide",
    )


@app.route('/robots.txt')
def robots_txt():
    return send_from_directory(os.path.join(app.root_path, "static"), "robots.txt")


@app.route('/sitemap.xml')
def sitemap_xml():
    return send_from_directory(os.path.join(app.root_path, "static"), "sitemap.xml")


@app.route('/naver502d24e941f50b3d3341745ef4de5f43.html')
def naver_verify():
    return send_from_directory(os.path.join(app.root_path, "static"), "naver502d24e941f50b3d3341745ef4de5f43.html")


@app.route('/naver520d24e941f50b3d3341745ef4de5f43.html')
def naver_verify_alt():
    return send_from_directory(os.path.join(app.root_path, "static"), "naver520d24e941f50b3d3341745ef4de5f43.html")


@app.route('/book/<int:book_id>')
def book_detail(book_id: int):
    detail = get_book_detail(book_id)
    if not detail:
        return render_template(
            "book.html",
            book=None,
            error="해당 도서를 찾을 수 없습니다.",
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


@app.route("/api/kyobo_status")
def api_kyobo_status():
    library_code = (request.args.get("library_code") or "").strip()
    brcd = (request.args.get("brcd") or "").strip()
    ctts_dvsn_code = (request.args.get("ctts_dvsn_code") or "").strip()
    ctgr_id = (request.args.get("ctgr_id") or "").strip()
    sntn_auth_code = (request.args.get("sntn_auth_code") or "").strip()
    if not library_code or not brcd or not ctts_dvsn_code or not ctgr_id:
        return jsonify({"error": "missing_params"}), 400

    cache_key = (library_code, brcd, ctts_dvsn_code, ctgr_id, sntn_auth_code)
    cached = STATUS_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached["ts"] < STATUS_TTL_SEC:
        return jsonify(cached["data"])

    base_url = _kyobo_base_url(library_code)
    if not base_url:
        return jsonify({"error": "unsupported_library"}), 404

    params = {
        "cttsDvsnCode": ctts_dvsn_code,
        "brcd": brcd,
        "ctgrId": ctgr_id,
    }
    if sntn_auth_code:
        params["sntnAuthCode"] = sntn_auth_code
    detail_url = f"{base_url}/elibrary-front/content/contentView.ink?{urlencode(params)}"
    try:
        res = requests.get(
            detail_url,
            timeout=7,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
        )
        res.raise_for_status()
        status = _parse_kyobo_status(res.text)
        if not status:
            return jsonify({"error": "parse_failed"}), 502
        payload = {"library_code": library_code, "brcd": brcd, "status": status}
        STATUS_CACHE[cache_key] = {"ts": now, "data": payload}
        return jsonify(payload)
    except Exception:
        return jsonify({"error": "fetch_failed"}), 502


@app.route('/api/search')
def search():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify({"total": 0, "items": []})

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

    def build_where(tokens):
        if not tokens:
            return "1=0", []
        groups = []
        params = []
        for token in tokens:
            pattern = f"%{token}%"
            clauses = []
            if use_trgm:
                if len(token) < 3:
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

    conn = get_db_conn()
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
            where_sql = f"{where_sql} AND EXISTS (SELECT 1 FROM holdings h2 WHERE h2.book_id = b.id AND {' AND '.join(filter_clauses)})"
            params = params + filter_params

        count_row = conn.execute(
            f"SELECT COUNT(*) AS total FROM books b WHERE {where_sql}",
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
            SELECT
                b.id,
                b.title,
                b.author,
                b.publisher,
                b.image_url,
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
            FROM books b
            LEFT JOIN holdings h ON h.book_id = b.id
            WHERE {where_sql}
            GROUP BY b.id, b.title, b.author, b.publisher, b.image_url
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
                f"SELECT DISTINCT h.platform FROM holdings h JOIN books b ON b.id = h.book_id WHERE {where_sql}",
                params,
            )
            for r in pcur.fetchall():
                raw = r["platform"] if using_postgres() else r[0]
                providers.add(platform_to_provider_label(raw))
            lcur = conn.execute(
                f"SELECT DISTINCT h.library_code, h.library FROM holdings h JOIN books b ON b.id = h.book_id WHERE {where_sql}",
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
                "title": row["title"] or "",
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

    conn = get_db_conn()
    try:
        placeholders = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"SELECT id, title, author, publisher, image_url FROM books WHERE id IN ({placeholders})",
            ids,
        )
        rows = cur.fetchall()
        results = []
        for r in rows:
            results.append(
                {
                    "book_id": r["id"],
                    "title": r["title"] or "",
                    "author": r["author"] or "",
                    "publisher": r["publisher"] or "",
                    "image_url": r["image_url"] or "",
                }
            )
        return jsonify(results)
    finally:
        conn.close()


if __name__ == '__main__':
    port = int(os.environ.get("LIBRARY_SEARCH_PORT", "5001"))
    app.run(host='0.0.0.0', port=port)
