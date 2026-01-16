# web/app.py (SQLite 기반 경량 검색)

import os
import json
import re
from db import get_db, using_postgres
import threading
import datetime
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from config import LIBRARIES, STATUS_FILE, PLATFORM_LABELS, LIBRARY_SHORT

try:
    from crawler_manager import CRAWLER_STATUS, start_crawling, check_library_update
except ImportError:
    CRAWLER_STATUS = {}

    def start_crawling(code, cb=None): return False
    def check_library_update(code): return (0, -1)

app = Flask(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT_DIR, "data", "library_split.db")
LEGACY_DB = os.path.join(ROOT_DIR, "data", "library.db")
DB_PATH = os.environ.get("LIBRARY_DB_PATH", DEFAULT_DB if os.path.exists(DEFAULT_DB) else LEGACY_DB)
IS_SPLIT_DB = True  # 기본은 split DB 사용
db_lock = threading.Lock()
DATA_DIR = Path(ROOT_DIR) / "data"


def get_db_conn():
    return get_db(DB_PATH)


def load_counts():
    counts = {}
    if not using_postgres() and not os.path.exists(DB_PATH):
        return counts
    conn = get_db_conn()
    try:
        cur = conn.execute("SELECT library_code, COUNT(*) FROM holdings GROUP BY library_code;")
        for code, cnt in cur.fetchall():
            counts[code] = cnt
    finally:
        conn.close()
    return counts


LIB_COUNTS = load_counts()
# 원격 총권수 체크 결과 유지용
REMOTE_COUNTS_CACHE = {}
# Persist remote count checks to disk so admin page can show last results after reloads.
REMOTE_COUNTS_FILE = os.path.join(DATA_DIR, "remote_counts.json")


def load_remote_counts():
    if os.path.exists(REMOTE_COUNTS_FILE):
        try:
            with open(REMOTE_COUNTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_remote_counts(cache):
    try:
        with open(REMOTE_COUNTS_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


REMOTE_COUNTS_CACHE = load_remote_counts()

# SQLite 신선도 확인 후 준비

LIB_NAME_TO_CODE = {info["library_name"]: code for code, info in LIBRARIES.items()}

# 도서관 이름/단축명/코드 -> URL 매핑
LIB_URL_MAP = {}
for code, info in LIBRARIES.items():
    lib_name = info["library_name"]
    short = LIBRARY_SHORT.get(code, lib_name)
    url = info.get("homepage_url", "#")
    for key in {lib_name, short, code}:
        LIB_URL_MAP[key] = url

LIB_META_BY_NAME = {}
for code, info in LIBRARIES.items():
    lib_name = info["library_name"]
    platform_code = info.get("platform", "Unknown")
    LIB_META_BY_NAME[lib_name] = {
        "code": code,
        "name": lib_name,
        "short": LIBRARY_SHORT.get(code, lib_name),
        "homepage_url": info.get("homepage_url", "#"),
        "platform_code": platform_code,
        "platform_label": PLATFORM_LABELS.get(platform_code, "기타"),
    }

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

PROVIDER_MAP = {
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

LIB_NAME_LOOKUP = {}
for code, info in LIBRARIES.items():
    lib_name = info["library_name"]
    short = LIBRARY_SHORT.get(code, lib_name)
    platform_code = info.get("platform", "Unknown")
    platform_label = PLATFORM_LABELS.get(platform_code, "기타")
    LIB_NAME_LOOKUP[lib_name] = {"short": short, "platform_label": platform_label}

PLATFORM_PRIORITY = {
    "Kyobo_New": 0,
    "Kyobo": 1,
    "YES24": 2,
    "FxLibrary": 3,
    "Mixed": 4,
    "Aladin": 5,
    "Unknown": 9,
}
TYPE_PRIORITY = {
    "scrapy": 0,
    "custom": 1,
    "odcloud": 2,
}


def group_platforms(libs):
    buckets = {}
    for lib_name in libs:
        meta = LIB_NAME_LOOKUP.get(lib_name, {})
        label = meta.get("platform_label", "기타")
        short = meta.get("short", lib_name)
        buckets.setdefault(label, []).append(short)
    return buckets


def normalize_title(text):
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"\[.*?\]|\(.*?\)", "", text)
    text = re.sub(r"(\d)\s*(권|부|호|화)", r"\1", text)
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
    roles = r"(지음|글|저|지음/그림|그림|옮김|엮음|역)"
    text = re.sub(roles, "", text)
    text = re.sub(r"[^\w\s]", "", text).lower().strip()
    text = re.sub(r"\s+", "", text)
    return text


def normalize_search_text(text: str) -> str:
    """Normalize query for prefix search on precomputed columns."""
    if not text:
        return ""
    text = str(text).lower().strip()
    text = re.sub(r"[\u200b\ufeff]", "", text)
    text = re.sub(r"[\\s\\[\\]\\(\\){}<>.,/|\\\\\\-_:;\"'`~!?]", "", text)
    return text


def normalize_provider(raw_value):
    if raw_value:
        key = str(raw_value).strip()
        norm = PROVIDER_MAP.get(key) or PROVIDER_MAP.get(key.lower())
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


def reload_database_safely(lib_code=None, success=True):
    # 크롤 종료 후 count만 갱신 (SQLite 재구축은 별도 스크립트)
    global LIB_COUNTS
    LIB_COUNTS = load_counts()


def get_counts():
    lib_total = len(LIBRARIES)
    book_total = None
    if using_postgres() or os.path.exists(DB_PATH):
        conn = get_db_conn()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM books;")
            book_total = cur.fetchone()[0]
        finally:
            conn.close()
    return lib_total, book_total


def build_admin_rows():
    # 매 요청마다 최신 로컬 카운트 로드 (서버 시작 시 0으로 고정되는 문제 방지)
    local_counts = load_counts()
    rows = []
    for code, info in LIBRARIES.items():
        status = CRAWLER_STATUS.get(code, {"status": "-", "msg": "", "last_run": "-"})
        local_count = local_counts.get(code, 0)
        remote_meta = REMOTE_COUNTS_CACHE.get(code, {})
        rows.append({
            "code": code,
            "name": info.get("library_name", info.get("name", code)),
            "short": LIBRARY_SHORT.get(code, ""),
            "platform_label": PLATFORM_LABELS.get(info.get("platform", "Unknown"), "기타"),
            "service_type": info.get("service_type", ""),
            "crawl_type": info.get("type", ""),
            "count": local_count,
            "remote_count": remote_meta.get("remote_count"),
            "remote_checked_at": remote_meta.get("checked_at"),
            "recommend_update": remote_meta.get("recommend_update", False),
            "status": status.get("status", "-"),
            "msg": status.get("msg", ""),
            "last_run": status.get("last_run", "-"),
            "homepage": info.get("homepage_url", "#")
        })
    def sort_key(r):
        cfg = LIBRARIES[r["code"]]
        type_key = cfg.get("type", "zzz")
        platform_code = cfg.get("platform", "Unknown")
        return (
            TYPE_PRIORITY.get(type_key, 9),
            PLATFORM_PRIORITY.get(platform_code, 99) if type_key == "scrapy" else 99,
            r["name"],
        )
    return sorted(rows, key=sort_key)


@app.route('/')
def index():
    lib_total, book_total = get_counts()
    return render_template('index.html', library_count=lib_total, book_count=book_total, lib_url_map=LIB_URL_MAP)


@app.route('/search')
def search():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify([])

    field = request.args.get('field', 'title_author')
    norm_query = normalize_search_text(query)
    if not norm_query:
        return jsonify([])

    FINAL_LIMIT = 1200
    pattern = f"%{norm_query}%"
    conn = get_db_conn()
    try:
        select_base = "SELECT id, title, author, publisher, image_url, isbn FROM books WHERE "
        clauses = []
        params = []
        if field in ("title", "title_author"):
            clauses.append(select_base + "title_norm LIKE ?")
            params.append(pattern)
        if field in ("author", "title_author"):
            clauses.append(select_base + "author_norm LIKE ?")
            params.append(pattern)
        if field == "publisher":
            clauses.append(select_base + "publisher_norm LIKE ?")
            params.append(pattern)
        if not clauses:
            clauses.append(select_base + "title_norm LIKE ?")
            params.append(pattern)
        sql = " UNION ALL ".join(clauses) + " LIMIT ?"
        params.append(FINAL_LIMIT * 3)
        cur = conn.execute(sql, params)
        rows = cur.fetchall()

        book_ids = [r["id"] for r in rows]
        holdings_map = {}
        if book_ids:
            placeholders = ",".join("?" for _ in book_ids)
            hcur = conn.execute(
                f"SELECT book_id, library_code, library, provider, platform, image_url, isbn FROM holdings WHERE book_id IN ({placeholders})",
                book_ids,
            )
            for h in hcur.fetchall():
                holdings_map.setdefault(h["book_id"], []).append(h)

        grouped = {}
        for row in rows:
            title = row["title"] or ""
            author = row["author"] or ""
            norm_key = (normalize_title(title), normalize_author(author), normalize_title(row["publisher"] or ""))
            item = grouped.setdefault(norm_key, {
                "title": title,
                "author": author,
                "publisher": row["publisher"] or "",
                "provider": "",
                "image_url": row["image_url"] or "",
                "libraries": [],
                "platforms": set(),
            })
            for h in holdings_map.get(row["id"], []):
                prov = normalize_provider(h["provider"] or "")
                if prov and not item["provider"]:
                    item["provider"] = prov
                lib_code = h["library_code"] or ""
                lib_name = h["library"] or ""
                item["libraries"].append({"name": lib_name, "code": lib_code})
                plat = h["platform"] or ""
                if plat:
                    item["platforms"].add(plat)
                if not item["image_url"] and h["image_url"]:
                    item["image_url"] = h["image_url"]
        results = []
        for item in grouped.values():
            lib_details = []
            platforms = set()
            for lib in item["libraries"]:
                lib_code = lib.get("code") or ""
                lib_name = lib.get("name") or ""
                meta = LIB_META_BY_CODE.get(lib_code) if lib_code else None
                if not meta:
                    meta = LIB_META_BY_NAME.get(lib_name)
                if meta:
                    lib_details.append(meta)
                    platforms.add(meta["platform_code"])
                else:
                    short = LIBRARY_SHORT.get(lib_code, lib_name)
                    lib_details.append({
                        "code": lib_code or None,
                        "name": lib_name or lib_code,
                        "short": short or lib_name or lib_code,
                        "homepage_url": "#",
                        "platform_code": "Unknown",
                        "platform_label": "기타",
                    })
            if not platforms:
                for meta in lib_details:
                    platforms.add(meta.get("platform_code", "Unknown"))
            provider = item["provider"] or provider_from_platforms(platforms or item["platforms"])
            results.append({
                "title": item["title"],
                "author": item["author"],
                "publisher": item["publisher"],
                "provider": provider,
                "image_url": item["image_url"],
                "libraries": lib_details,
                "platforms": list(platforms or item["platforms"]),
            })
        return jsonify(results[:FINAL_LIMIT])
    except Exception as e:
        print(f"[오류] 검색 실패: {e}")
        return jsonify({"error": "검색 중 오류 발생"})
    finally:
        conn.close()


@app.route('/admin')
def admin_page():
    lib_total, book_total = get_counts()
    rows = build_admin_rows()
    return render_template('admin.html', status=CRAWLER_STATUS, library_count=lib_total, book_count=book_total, rows=rows)


@app.route('/admin/run/<lib_code>', methods=['POST'])
def run_crawler(lib_code):
    if start_crawling(lib_code, on_complete_callback=reload_database_safely):
        return jsonify({"success": True, "msg": f"{LIBRARIES[lib_code]['name']} 수행"})
    else:
        return jsonify({"success": False, "msg": "이미 실행 중이거나 실패"})


@app.route('/admin/status')
def get_status():
    return jsonify(CRAWLER_STATUS)


from crawler_manager import set_auto_crawl

@app.route('/admin/auto-crawl', methods=['POST'])
def toggle_auto_crawl():
    data = request.get_json()
    is_active = data.get('active', False)
    current_state = set_auto_crawl(is_active)
    msg = "자동 갱신 ON" if current_state else "자동 갱신 OFF"
    return jsonify({"success": True, "active": current_state, "msg": msg})


@app.route('/admin/check-totals', methods=['POST'])
def check_totals():
    global LIB_COUNTS, REMOTE_COUNTS_CACHE
    # 최신 로컬 카운트 로드
    LIB_COUNTS = load_counts()
    results = {}
    checked_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for code, info in LIBRARIES.items():
        try:
            local_from_file, remote_from_site = check_library_update(code)
            local_count = LIB_COUNTS.get(code, local_from_file if local_from_file >= 0 else 0)
            remote_val = remote_from_site if remote_from_site >= 0 else None
            rec_needed = remote_val is not None and remote_val != local_count
            REMOTE_COUNTS_CACHE[code] = {
                "remote_count": remote_val,
                "recommend_update": rec_needed,
                "checked_at": checked_at,
            }
            results[code] = {
                "remote_count": remote_val,
                "recommend_update": rec_needed,
                "local_count": local_count,
                "checked_at": checked_at,
            }
        except Exception as e:
            results[code] = {"remote_count": None, "recommend_update": False, "error": str(e), "checked_at": checked_at}
    save_remote_counts(REMOTE_COUNTS_CACHE)
    return jsonify({"success": True, "data": results})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
