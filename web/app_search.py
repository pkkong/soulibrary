import os
import json
import re
import sqlite3
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from config import LIBRARIES, PLATFORM_LABELS, LIBRARY_SHORT

app = Flask(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT_DIR, "data", "library_split.db")
LEGACY_DB = os.path.join(ROOT_DIR, "data", "library.db")
DB_PATH = os.environ.get("LIBRARY_DB_PATH", DEFAULT_DB if os.path.exists(DEFAULT_DB) else LEGACY_DB)


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    try:
        conn.execute("PRAGMA busy_timeout = 30000")
    except Exception:
        pass
    conn.row_factory = sqlite3.Row
    return conn


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
    text = re.sub(r"[\\s\\[\\]\\(\\){}<>.,/|\\\\\\-_:;\"'`~!?]", "", text)
    return text


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


def get_counts():
    lib_total = len(LIBRARIES)
    book_total = None
    if os.path.exists(DB_PATH):
        conn = get_db()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM books;")
            book_total = cur.fetchone()[0]
        finally:
            conn.close()
    return lib_total, book_total


def get_book_detail(book_id: int):
    conn = get_db()
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
            libraries.append(meta)
            platform = meta.get("platform_code") or "Unknown"
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


@app.route('/')
def index():
    lib_total, book_total = get_counts()
    return render_template('index.html', library_count=lib_total, book_count=book_total, lib_url_map={})


@app.route('/book/<int:book_id>')
def book_detail(book_id: int):
    detail = get_book_detail(book_id)
    if not detail:
        return render_template("book.html", book=None, error="해당 도서를 찾을 수 없습니다."), 404
    return render_template("book.html", book=detail, error=None)


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
    conn = get_db()
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
                "book_id": row["id"],
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
                    meta = LIB_NAME_LOOKUP.get(lib_name)
                    if meta:
                        meta = {
                            "code": lib_code or None,
                            "name": lib_name or lib_code,
                            "short": meta.get("short", lib_name or lib_code),
                            "homepage_url": "#",
                            "platform_code": meta.get("platform_code", "Unknown"),
                            "platform_label": meta.get("platform_label", "기타"),
                        }
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
                "book_id": item.get("book_id"),
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
        return jsonify({"error": "검색 처리 오류 발생"})
    finally:
        conn.close()


if __name__ == '__main__':
    port = int(os.environ.get("LIBRARY_SEARCH_PORT", "5001"))
    app.run(host='0.0.0.0', port=port)
