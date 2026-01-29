import os
import json
import re
import time
import ssl
import traceback
from db import get_db, using_postgres
from pathlib import Path
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
from flask import Flask, render_template, request, jsonify, send_from_directory
import requests
import urllib3
from config import LIBRARIES, PLATFORM_LABELS, LIBRARY_SHORT

app = Flask(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT_DIR, "data", "library_split.db")
LEGACY_DB = os.path.join(ROOT_DIR, "data", "library.db")
DB_PATH = os.environ.get("LIBRARY_DB_PATH", DEFAULT_DB if os.path.exists(DEFAULT_DB) else LEGACY_DB)
STATUS_TTL_SEC = int(os.environ.get("KYOBO_STATUS_TTL", "120"))
STATUS_CACHE = {}
STATUS_SESSION = None
HOLDINGS_COLUMNS = None
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TLSAdapter(requests.adapters.HTTPAdapter):
    """Allow weaker TLS ciphers for legacy library servers."""

    def __init__(self, ssl_context=None, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _get_status_session():
    global STATUS_SESSION
    if STATUS_SESSION:
        return STATUS_SESSION
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    except Exception:
        pass
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    session = requests.Session()
    session.trust_env = False
    session.mount("https://", TLSAdapter(ssl_context=ctx))
    STATUS_SESSION = session
    return STATUS_SESSION


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
    except Exception:
        HOLDINGS_COLUMNS = set()
    return HOLDINGS_COLUMNS


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


def _build_kyobo_detail_url(library_code: str, params: dict) -> str:
    base_url = _kyobo_base_url(library_code)
    if not base_url:
        return ""
    info = LIBRARIES.get(library_code) or {}
    content_path = info.get("content_path") or "/elibrary-front/content/contentView.ink"
    if not content_path.startswith("/"):
        content_path = "/" + content_path
    return f"{base_url}{content_path}?{urlencode(params)}"


def _http_fallback(url: str) -> str:
    if url.startswith("https://"):
        return "http://" + url[len("https://"):]
    return url


def _yes24_base_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code)
    if not info:
        return ""
    raw_url = info.get("homepage_url") or info.get("total_count_url")
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _yes24_list_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code) or {}
    url = info.get("total_count_url")
    if url:
        return url.split("#", 1)[0]
    base_url = _yes24_base_url(library_code)
    if not base_url:
        return ""
    return f"{base_url}/ebook/?mode=total&sort=pubdt&cate_id=&page_num=1"


def _bookcube_base_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code)
    if not info:
        return ""
    raw_url = info.get("homepage_url") or info.get("total_count_url")
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _bookcube_list_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code) or {}
    url = info.get("total_count_url")
    if url:
        return url.split("#", 1)[0]
    base_url = _bookcube_base_url(library_code)
    if not base_url:
        return ""
    return f"{base_url}/FxLibrary/product/list/?itemdv=1&sort=3&page=1&itemCount=20&pageCount=10&category=&middlecategory=&cateopt=total&group_num=recommand&catenavi=main&category_type=book&searchoption=&keyoption=&keyoption2=&keyword=&listfilter=all_list&selectview=list_on&searchType=&name=&publisher=&author=&terminal="


def _bookcube_page_size(list_url: str) -> int:
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    value = (qs.get("itemCount") or [""])[0]
    try:
        size = int(value)
        return max(1, size)
    except Exception:
        return 20


def _bookcube_page_url(list_url: str, page: int) -> str:
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["page"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _bookcube_status_list_url(list_url: str) -> str:
    if not list_url:
        return list_url
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["itemCount"] = ["200"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _bookcube_search_list_url(list_url: str, keyword: str, keyoption2: str = "1") -> str:
    if not list_url or not keyword:
        return list_url
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["page"] = ["1"]
    qs["itemCount"] = ["200"]
    qs["searchType"] = ["search"]
    qs["searchoption"] = ["1"]
    qs["keyoption2"] = [keyoption2]
    qs["keyword"] = [keyword]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _parse_bookcube_status(html: str, content_id: str):
    if not html or not content_id:
        return None
    blocks = re.findall(r"<li class=\"item\".*?</li>", html, re.S)
    for block in blocks:
        if content_id not in block:
            continue
        text = re.sub(r"<[^>]+>", " ", block)
        text = re.sub(r"\s+", " ", text)
        loan_match = re.search(r"대출\s*([0-9,]+)\s*/\s*([0-9,]+)", text)
        reserve_match = re.search(r"예약\s*([0-9,]+)", text)
        if loan_match:
            return {
                "loaned": int(loan_match.group(1).replace(",", "")),
                "total": int(loan_match.group(2).replace(",", "")),
                "reserved": int(reserve_match.group(1).replace(",", "")) if reserve_match else 0,
            }

    idx = html.find(content_id)
    if idx == -1:
        return None
    start = max(idx - 4000, 0)
    end = min(idx + 4000, len(html))
    chunk = html[start:end]
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = re.sub(r"\s+", " ", text)
    loan_match = re.search(r"대출\s*([0-9,]+)\s*/\s*([0-9,]+)", text)
    reserve_match = re.search(r"예약\s*([0-9,]+)", text)
    if loan_match:
        return {
            "loaned": int(loan_match.group(1).replace(",", "")),
            "total": int(loan_match.group(2).replace(",", "")),
            "reserved": int(reserve_match.group(1).replace(",", "")) if reserve_match else 0,
        }
    return None


def _parse_bookcube_detail_status(html: str):
    if not html:
        return None
    def _sanitize_status(status):
        if not status:
            return None
        if status.get("loaned") == 0 and status.get("total") == 0 and status.get("reserved") == 0:
            return None
        return status
    # Try state list block first
    block_match = re.search(r"<ul[^>]*class=[\"']state[\"'][^>]*>(.*?)</ul>", html, re.I | re.S)
    block = block_match.group(1) if block_match else ""
    if block:
        m = re.search(r"<p[^>]*>\\s*대출\\s*</p>\\s*([0-9,]+)\\s*/\\s*([0-9,]+)", block, re.I)
        r = re.search(r"<p[^>]*>\\s*예약\\s*</p>\\s*([0-9,]+)", block, re.I)
        if m:
            return _sanitize_status({
                "loaned": int(m.group(1).replace(",", "")),
                "total": int(m.group(2).replace(",", "")),
                "reserved": int(r.group(1).replace(",", "")) if r else 0,
            })
        m = re.search(r"대출[^0-9]*([0-9,]+)\\s*/\\s*([0-9,]+)", block, re.I | re.S)
        r = re.search(r"예약[^0-9]*([0-9,]+)", block, re.I | re.S)
        if m:
            return _sanitize_status({
                "loaned": int(m.group(1).replace(",", "")),
                "total": int(m.group(2).replace(",", "")),
                "reserved": int(r.group(1).replace(",", "")) if r else 0,
            })
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    loan_match = re.search(r"대출\s*([0-9,]+)\s*/\s*([0-9,]+)", text)
    reserve_match = re.search(r"예약\s*([0-9,]+)", text)
    if loan_match:
        return _sanitize_status({
            "loaned": int(loan_match.group(1).replace(",", "")),
            "total": int(loan_match.group(2).replace(",", "")),
            "reserved": int(reserve_match.group(1).replace(",", "")) if reserve_match else 0,
        })
    return None


def _gangnam_list_url(library_code: str) -> str:
    info = LIBRARIES.get(library_code) or {}
    url = info.get("total_count_url")
    if url:
        return url
    base_url = info.get("homepage_url")
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/elibbook/book_category.asp?mode=&page_num=1&branch=99&supply_code=&strSort=p&ldav="


def _gangnam_page_url(list_url: str, page: int) -> str:
    parsed = urlparse(list_url)
    qs = parse_qs(parsed.query)
    qs["page_num"] = [str(page)]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def _parse_gangnam_status(html: str, content_id: str):
    if not html or not content_id:
        return None
    needle = f"book_num={content_id}"
    idx = html.find(needle)
    if idx == -1:
        return None
    start = max(idx - 5000, 0)
    end = min(idx + 5000, len(html))
    chunk = html[start:end]
    text = re.sub(r"<[^>]+>", " ", chunk)
    text = re.sub(r"\s+", " ", text)
    owned_match = re.search(r"보유\s*(\d+)", text)
    loan_match = re.search(r"대출\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if not loan_match or not owned_match:
        return None
    return {
        "owned": int(owned_match.group(1)),
        "loaned": int(loan_match.group(1)),
        "reserved": int(reserve_match.group(1)) if reserve_match else 0,
    }


def _parse_gangnam_detail_status(html: str):
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    owned_match = re.search(r"보유\s*(\d+)", text)
    loan_match = re.search(r"대출\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if not loan_match or not owned_match:
        return None
    return {
        "owned": int(owned_match.group(1)),
        "loaned": int(loan_match.group(1)),
        "reserved": int(reserve_match.group(1)) if reserve_match else 0,
    }


def _parse_yes24_status(html: str, goods_id: str = ""):
    if not html:
        return None
    # 1) Detail page: a single stat block.
    stat_match = re.search(r'<div class="stat[^"]*">.*?</div>', html, re.S)
    if stat_match:
        stat_html = stat_match.group(0)
        def pick(label):
            m = re.search(rf"<li>\s*{label}\s*<strong>(\d+)</strong>", stat_html)
            return int(m.group(1)) if m else 0
        return {
            "owned": pick("보유"),
            "loaned": pick("대출"),
            "reserved": pick("예약"),
        }

    # 2) List page: find the block by goods_id.
    if goods_id:
        parts = html.split('<div class="bx')
        for part in parts[1:]:
            block = '<div class="bx' + part
            if f"goods_id={goods_id}" not in block:
                continue
            stat_match = re.search(r'<div class="stat">.*?</div>', block, re.S)
            if not stat_match:
                return None
            stat_html = stat_match.group(0)
            def pick(label):
                m = re.search(rf"<li>\s*{label}\s*<strong>(\d+)</strong>", stat_html)
                return int(m.group(1)) if m else 0
            return {
                "owned": pick("보유"),
                "loaned": pick("대출"),
                "reserved": pick("예약"),
            }
    return None


def _to_int(value, default=0):
    try:
        return int(str(value).replace(",", "").strip())
    except Exception:
        return default


def _parse_seoul_status(data: dict):
    contents = data.get("Contents") if isinstance(data, dict) else None
    if isinstance(contents, list) and contents:
        contents = contents[0]
    if not isinstance(contents, dict):
        return None
    return {
        "loaned": _to_int(contents.get("currentLoanCount")),
        "total": _to_int(contents.get("contentsCopys")),
        "reserved": _to_int(contents.get("currentResvCount")),
    }


def _parse_sen_status(data: dict):
    contents = data.get("Contents") if isinstance(data, dict) else None
    if isinstance(contents, list) and contents:
        contents = contents[0]
    if isinstance(contents, dict):
        return {
            "loaned": _to_int(contents.get("currentLoanCount")),
            "total": _to_int(contents.get("contentsCopys")),
            "reserved": _to_int(contents.get("currentResvCount")),
        }
    return {
        "loaned": _to_int(data.get("currentLoanCount")),
        "total": _to_int(data.get("contentsCopys")),
        "reserved": _to_int(data.get("currentResvCount")),
    }


def _parse_eunpyeong_status(data: dict):
    contents = data.get("Contents") if isinstance(data, dict) else None
    if isinstance(contents, dict):
        return {
            "loaned": _to_int(contents.get("ContentLoanCount")),
            "total": _to_int(contents.get("Copys")),
            "reserved": _to_int(contents.get("ContentResevCount")),
        }
    return None


def _parse_eunpyeong_html_status(html: str):
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    loan_match = re.search(r"대출\s*(\d+)\s*/\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if loan_match:
        return {
            "loaned": int(loan_match.group(1)),
            "total": int(loan_match.group(2)),
            "reserved": int(reserve_match.group(1)) if reserve_match else 0,
        }
    return None


def _parse_dobong_status(html: str):
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    loan_match = re.search(r"대출\s*(\d+)\s*/\s*(\d+)", text)
    reserve_match = re.search(r"예약\s*(\d+)", text)
    if loan_match:
        return {
            "loaned": int(loan_match.group(1)),
            "total": int(loan_match.group(2)),
            "reserved": int(reserve_match.group(1)) if reserve_match else 0,
        }
    rent_match = re.search(r'class=["\']rentEbook["\'][^>]*>\s*(\d+)\s*<', html, re.I)
    reserve_match = re.search(r'class=["\']reserveEbook["\'][^>]*>\s*(\d+)\s*<', html, re.I)
    total_match = re.search(r'class=["\']book_present["\'][^>]*>.*?/\\s*(\d+)', html, re.I | re.S)
    if rent_match and total_match:
        return {
            "loaned": int(rent_match.group(1)),
            "total": int(total_match.group(1)),
            "reserved": int(reserve_match.group(1)) if reserve_match else 0,
        }
    return None
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

        group_expr = "COALESCE(merge_group_id, canonical_id, CAST(id AS TEXT)) || ':' || COALESCE(publisher_norm, '')"
        group_row = conn.execute(
            f"SELECT {group_expr} AS group_id FROM books WHERE id=?",
            (book_id,),
        ).fetchone()
        group_id = group_row["group_id"] if group_row else str(book_id)

        optional_cols = ["brcd", "ctts_dvsn_code", "ctgr_id", "sntn_auth_code", "goods_id", "content_id"]
        available = _get_holdings_columns(conn)
        selected_optional = [col for col in optional_cols if col in available]
        base_cols = ["library_code", "library", "provider", "platform", "image_url", "isbn"]
        columns_sql = ", ".join(base_cols + selected_optional)
        hcur = conn.execute(
            f"""
            SELECT {columns_sql}
            FROM holdings
            WHERE book_id IN (
                SELECT id FROM books WHERE {group_expr} = ?
            )
            """,
            (group_id,),
        )
        holdings = [dict(r) for r in hcur.fetchall()]

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
                    "service_type": "Unknown",
                }
            entry = dict(meta)
            entry["platform_code"] = h.get("platform") or entry.get("platform_code") or "Unknown"
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
                    entry["detail_url"] = _build_kyobo_detail_url(lib_code, params)
            if lib_code == "dobong" and entry["brcd"]:
                entry["detail_url"] = (
                    "https://elib.dobong.kr/Kyobo_T3_Mobile/Phone/Main/Ebook_Detail.asp"
                    f"?type=EBOOK&barcode={entry['brcd']}&classCode=&keyWord=&product_cd=001"
                    "&kiduse_yn=N&borrowRadio=&sortType=1"
                )
            if entry["platform_code"] == "YES24" and entry["goods_id"]:
                base_url = _yes24_base_url(lib_code)
                if base_url:
                    entry["detail_url"] = f"{base_url}/ebook/detail/?goods_id={entry['goods_id']}"
            if entry["platform_code"] == "Bookcube" and entry["content_id"]:
                base_url = _bookcube_base_url(lib_code)
                if base_url:
                    entry["detail_url"] = f"{base_url}/FxLibrary/product/view/?num={entry['content_id']}&category=&category_type=book"
            if lib_code == "gangnam" and entry["content_id"]:
                base_url = _bookcube_base_url(lib_code)
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
                    "http://epbook.eplib.or.kr:8100/ebookPlatform/Homepage/ContentsDetail.do"
                    f"?contentKey={entry['content_id']}&libCode=111042&userId=null"
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
            score += 1 if item.get("detail_url") else 0
            return score

        deduped = {}
        for item in libraries:
            key = _entry_key(item)
            prev = deduped.get(key)
            if not prev or _entry_score(item) > _entry_score(prev):
                deduped[key] = item
        libraries = list(deduped.values())

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
        session = _get_status_session()
        res = session.get(
            detail_url,
            timeout=7,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
            verify=False,
        )
        if res.status_code != 200:
            raise RuntimeError("status_code")
        status = _parse_kyobo_status(res.text)
        if not status:
            raise RuntimeError("parse_failed")
    except Exception:
        try:
            fallback_url = _http_fallback(detail_url)
            res = session.get(
                fallback_url,
                timeout=7,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
            )
            if res.status_code != 200:
                raise RuntimeError("status_code")
            status = _parse_kyobo_status(res.text)
        except Exception:
            return jsonify({"error": "fetch_failed"}), 502
    try:
        if not status:
            return jsonify({"error": "parse_failed"}), 502
        payload = {"library_code": library_code, "brcd": brcd, "status": status}
        STATUS_CACHE[cache_key] = {"ts": now, "data": payload}
        return jsonify(payload)
    except Exception:
        return jsonify({"error": "fetch_failed"}), 502


@app.route("/api/yes24_status")
def api_yes24_status():
    library_code = (request.args.get("library_code") or "").strip()
    goods_id = (request.args.get("goods_id") or "").strip()
    debug = request.args.get("debug") == "1"
    if not library_code or not goods_id:
        return jsonify({"error": "missing_params"}), 400

    cache_key = ("yes24", library_code, goods_id)
    cached = STATUS_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached["ts"] < STATUS_TTL_SEC and not debug:
        return jsonify(cached["data"])

    base_url = _yes24_base_url(library_code)
    if not base_url:
        return jsonify({"error": "unsupported_library"}), 404
    detail_url = f"{base_url}/ebook/detail/?goods_id={goods_id}"
    list_url = _yes24_list_url(library_code)
    if not list_url:
        list_url = ""

    try:
        status = None
        source = None
        attempted = []
        for url, kind in ((list_url, "list"), (detail_url, "detail")):
            if not url:
                continue
            for candidate in (url, _http_fallback(url)):
                attempted.append(candidate)
                try:
                    res = _get_status_session().get(
                        candidate,
                        timeout=7,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
                        verify=False,
                    )
                    res.raise_for_status()
                    status = _parse_yes24_status(res.text, goods_id)
                    if status:
                        source = f"{kind}:{'http' if candidate.startswith('http://') else 'https'}"
                        break
                except Exception:
                    status = None
            if status:
                break
        if not status:
            payload = {"error": "parse_failed"}
            if debug:
                payload.update({"library_code": library_code, "goods_id": goods_id, "attempted": attempted})
            return jsonify(payload), 502
        payload = {"library_code": library_code, "goods_id": goods_id, "status": status}
        if debug:
            payload.update({"source": source, "attempted": attempted})
        STATUS_CACHE[cache_key] = {"ts": now, "data": payload}
        return jsonify(payload)
    except Exception:
        payload = {"error": "fetch_failed"}
        if debug:
            payload.update({"library_code": library_code, "goods_id": goods_id})
        return jsonify(payload), 502


@app.route("/api/bookcube_status")
def api_bookcube_status():
    library_code = (request.args.get("library_code") or "").strip()
    content_id = (request.args.get("content_id") or "").strip()
    debug = request.args.get("debug") == "1"
    if not library_code or not content_id:
        return jsonify({"error": "missing_params"}), 400

    cache_key = ("bookcube", library_code, content_id)
    cached = STATUS_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached["ts"] < STATUS_TTL_SEC and not debug:
        return jsonify(cached["data"])

    list_url = _bookcube_list_url(library_code)
    if not list_url:
        return jsonify({"error": "unsupported_library"}), 404

    list_url = _bookcube_status_list_url(list_url)
    page_size = _bookcube_page_size(list_url)
    max_pages = int(os.environ.get("BOOKCUBE_STATUS_MAX_PAGES", "10"))
    status = None
    source = None
    attempted = []
    try:
        title = ""
        conn = None
        try:
            conn = get_db_conn()
            cur = conn.execute(
                "SELECT b.title FROM holdings h JOIN books b ON b.id = h.book_id "
                "WHERE h.library_code = ? AND h.content_id = ? LIMIT 1",
                (library_code, content_id),
            )
            row = cur.fetchone()
            title = (row.get("title") if row else "") or ""
        except Exception:
            title = ""
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        if title:
            search_url = _bookcube_search_list_url(list_url, title)
            attempted.append(search_url)
            res = _get_status_session().get(
                search_url,
                timeout=7,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
                verify=False,
            )
            res.raise_for_status()
            if "euc-kr" in (res.headers.get("Content-Type", "").lower()):
                res.encoding = "euc-kr"
            status = _parse_bookcube_status(res.text, content_id)
            if status:
                source = "search:title"

        if not status:
            first_url = _bookcube_page_url(list_url, 1)
            attempted.append(first_url)
            res = _get_status_session().get(
                first_url,
                timeout=7,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
                verify=False,
            )
            res.raise_for_status()
            if "euc-kr" in (res.headers.get("Content-Type", "").lower()):
                res.encoding = "euc-kr"
            status = _parse_bookcube_status(res.text, content_id)
            if status:
                source = "list"

        if not status:
            total_count = None
            m = re.search(r"총\\s*([\\d,]+)종", res.text)
            if m:
                try:
                    total_count = int(m.group(1).replace(",", ""))
                except Exception:
                    total_count = None
            total_pages = None
            if total_count:
                total_pages = max(1, (total_count + page_size - 1) // page_size)
            if total_pages is None:
                total_pages = max_pages

            for page in range(2, min(total_pages, max_pages) + 1):
                url = _bookcube_page_url(list_url, page)
                attempted.append(url)
                res = _get_status_session().get(
                    url,
                    timeout=7,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
                    verify=False,
                )
                res.raise_for_status()
                if "euc-kr" in (res.headers.get("Content-Type", "").lower()):
                    res.encoding = "euc-kr"
                status = _parse_bookcube_status(res.text, content_id)
                if status:
                    source = "list"
                    break

        if not status:
            detail_url = f"{_bookcube_base_url(library_code)}/FxLibrary/product/view/?num={content_id}&category=&category_type=book"
            attempted.append(detail_url)
            res = _get_status_session().get(
                detail_url,
                timeout=7,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
                verify=False,
            )
            res.raise_for_status()
            if "euc-kr" in (res.headers.get("Content-Type", "").lower()):
                res.encoding = "euc-kr"
            status = _parse_bookcube_detail_status(res.text)
            if status:
                source = "detail"

        if not status:
            payload = {"error": "parse_failed"}
            if debug:
                payload.update({"library_code": library_code, "content_id": content_id, "attempted": attempted})
            return jsonify(payload), 502
        payload = {"library_code": library_code, "content_id": content_id, "status": status}
        if debug:
            payload.update({"source": source, "attempted": attempted})
        STATUS_CACHE[cache_key] = {"ts": now, "data": payload}
        return jsonify(payload)
    except Exception:
        payload = {"error": "fetch_failed"}
        if debug:
            payload.update({"library_code": library_code, "content_id": content_id, "attempted": attempted})
        return jsonify(payload), 502


@app.route("/api/gangnam_status")
def api_gangnam_status():
    library_code = (request.args.get("library_code") or "").strip()
    content_id = (request.args.get("content_id") or "").strip()
    debug = request.args.get("debug") == "1"
    if not library_code or not content_id:
        return jsonify({"error": "missing_params"}), 400

    cache_key = ("gangnam", library_code, content_id)
    cached = STATUS_CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached["ts"] < STATUS_TTL_SEC:
        return jsonify(cached["data"])

    list_url = _gangnam_list_url(library_code)
    if not list_url:
        return jsonify({"error": "unsupported_library"}), 404

    max_pages = int(os.environ.get("GANGNAM_STATUS_MAX_PAGES", "20"))
    status = None
    attempted = []
    try:
        first_url = _gangnam_page_url(list_url, 1)
        attempted.append(first_url)
        res = _get_status_session().get(
            first_url,
            timeout=7,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
            verify=False,
        )
        res.raise_for_status()
        if "euc-kr" in (res.headers.get("Content-Type", "").lower()):
            res.encoding = "euc-kr"
        status = _parse_gangnam_status(res.text, content_id)

        if not status:
            total_pages = None
            m = re.search(r"<strong>\\s*([\\d,]+)\\s*</strong>\\s*건", res.text)
            if m:
                try:
                    total_count = int(m.group(1).replace(",", ""))
                    total_pages = max(1, (total_count + 19) // 20)
                except Exception:
                    total_pages = None
            if total_pages is None:
                total_pages = max_pages
            for page in range(2, min(total_pages, max_pages) + 1):
                url = _gangnam_page_url(list_url, page)
                attempted.append(url)
                res = _get_status_session().get(
                    url,
                    timeout=7,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
                    verify=False,
                )
                res.raise_for_status()
                if "euc-kr" in (res.headers.get("Content-Type", "").lower()):
                    res.encoding = "euc-kr"
                status = _parse_gangnam_status(res.text, content_id)
                if status:
                    break

        if not status:
            detail_url = f"{_bookcube_base_url(library_code)}/elibbook/book_detail.asp?book_num={content_id}"
            attempted.append(detail_url)
            res = _get_status_session().get(
                detail_url,
                timeout=7,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SoulibStatus/1.0)"},
                verify=False,
            )
            res.raise_for_status()
            if "euc-kr" in (res.headers.get("Content-Type", "").lower()):
                res.encoding = "euc-kr"
            status = _parse_gangnam_detail_status(res.text)

        if not status:
            payload = {"error": "parse_failed"}
            if debug:
                payload.update({"library_code": library_code, "content_id": content_id, "attempted": attempted})
            return jsonify(payload), 502
        payload = {"library_code": library_code, "content_id": content_id, "status": status}
        STATUS_CACHE[cache_key] = {"ts": now, "data": payload}
        return jsonify(payload)
    except Exception:
        payload = {"error": "fetch_failed"}
        if debug:
            payload.update({"library_code": library_code, "content_id": content_id, "attempted": attempted})
        return jsonify(payload), 502


@app.route("/api/seoul_status")
def api_seoul_status():
    content_id = (request.args.get("content_id") or "").strip()
    if not content_id:
        return jsonify({"error": "missing_content_id"}), 400

    cache_key = f"seoul:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    try:
        session = _get_status_session()
        url = f"https://elib.seoul.go.kr/api/contents/{content_id}"
        res = session.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        status = _parse_seoul_status(data)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"content_id": content_id, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception:
        return jsonify({"content_id": content_id, "status": None}), 502


@app.route("/api/sen_status")
def api_sen_status():
    library_code = (request.args.get("library_code") or "").strip()
    content_id = (request.args.get("content_id") or "").strip()
    if not library_code:
        return jsonify({"error": "missing_library_code"}), 400
    if library_code == "sen_subs":
        status = {"loaned": 0, "total": 1, "reserved": 0}
        return jsonify({"library_code": library_code, "content_id": content_id, "status": status})
    if not content_id:
        return jsonify({"error": "missing_content_id"}), 400

    cache_key = f"sen:{library_code}:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    try:
        session = _get_status_session()
        url = f"https://e-lib.sen.go.kr/api/contents/{content_id}/TY01"
        res = session.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        status = _parse_sen_status(data)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"library_code": library_code, "content_id": content_id, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception:
        return jsonify({"library_code": library_code, "content_id": content_id, "status": None}), 502


@app.route("/api/eunpyeong_status")
def api_eunpyeong_status():
    content_id = (request.args.get("content_id") or "").strip()
    debug = request.args.get("debug") == "1"
    if not content_id:
        return jsonify({"error": "missing_content_id"}), 400

    cache_key = f"eunpyeong:{content_id}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    attempted = []
    try:
        session = _get_status_session()
        url = "http://epbook.eplib.or.kr:8100/ebookPlatform/Homepage/ContentsDetail.do"
        params = {"contentKey": content_id, "libCode": "111042", "userId": "null"}
        attempted.append(url)
        res = session.get(
            url,
            params=params,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        res.raise_for_status()
        status = None
        data = None
        try:
            data = res.json()
        except Exception:
            data = None
        if data is not None:
            status = _parse_eunpyeong_status(data)
        if not status:
            status = _parse_eunpyeong_html_status(res.text)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"content_id": content_id, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception:
        payload = {"content_id": content_id, "status": None}
        if debug:
            payload.update({"attempted": attempted})
        return jsonify(payload), 502


@app.route("/api/dobong_status")
def api_dobong_status():
    brcd = (request.args.get("brcd") or "").strip()
    debug = request.args.get("debug") == "1"
    if not brcd:
        return jsonify({"error": "missing_brcd"}), 400

    cache_key = f"dobong:{brcd}"
    cached = STATUS_CACHE.get(cache_key)
    if cached and (time.time() - cached["time"]) < STATUS_TTL_SEC:
        return jsonify(cached["payload"])

    attempted = []
    try:
        session = _get_status_session()
        url = "https://elib.dobong.kr/Kyobo_T3_Mobile/Phone/Main/Ebook_Detail.asp"
        params = {
            "type": "EBOOK",
            "barcode": brcd,
            "classCode": "",
            "keyWord": "",
            "product_cd": "001",
            "kiduse_yn": "N",
            "borrowRadio": "",
            "sortType": "1",
        }
        attempted.append(url)
        res = session.get(url, params=params, timeout=15)
        res.raise_for_status()
        status = _parse_dobong_status(res.text)
        if not status:
            raise RuntimeError("status_missing")
        payload = {"brcd": brcd, "status": status}
        STATUS_CACHE[cache_key] = {"time": time.time(), "payload": payload}
        return jsonify(payload)
    except Exception:
        payload = {"brcd": brcd, "status": None}
        if debug:
            payload.update({"attempted": attempted})
        return jsonify(payload), 502


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

        group_expr = "COALESCE(b.merge_group_id, b.canonical_id, CAST(b.id AS TEXT)) || ':' || COALESCE(b.publisher_norm, '')"
        count_row = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM (
                SELECT DISTINCT {group_expr} AS group_id
                FROM books b
                WHERE {where_sql}
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
            FROM rep r
            JOIN books b ON b.id = r.rep_id
            LEFT JOIN group_books gb ON gb.group_id = r.group_id
            LEFT JOIN holdings h ON h.book_id = gb.id
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
                f"""
                WITH group_books AS (
                    SELECT b.id
                    FROM books b
                    WHERE {where_sql}
                )
                SELECT DISTINCT h.platform
                FROM holdings h
                JOIN group_books gb ON gb.id = h.book_id
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
