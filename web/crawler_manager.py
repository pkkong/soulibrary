"""
Crawler manager: run spiders, track status, and check remote total counts.
"""

import datetime
import json
import os
import re
import ssl
import subprocess
import threading
import time
import sys
from pathlib import Path

import urllib3
import requests

# Ensure project root is on sys.path so that "crawler.*" imports work when running from /web
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import LIBRARIES, CRAWLER_DIR, STATUS_FILE
from crawler.odcloud_downloader import get_odcloud_total_count

# Optional API helpers (서울도서관/교육청)
try:
    from crawler.collect_seoul import get_total_ebook_count as get_seoul_total_count
except Exception:
    get_seoul_total_count = None

SEOUL_API_KEY = None
try:
    from web.config import SEOUL_API_KEY as _SEOUL_API_KEY
    SEOUL_API_KEY = _SEOUL_API_KEY
except Exception:
    pass

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT_DIR = os.path.dirname(CRAWLER_DIR)
status_lock = threading.Lock()
auto_crawl_active = False
# 오래된 상태 자동 초기화 기준(초)
RUN_STALE_SECONDS = 60 * 60  # 1시간


class TLSAdapter(requests.adapters.HTTPAdapter):
    """Custom TLS adapter to allow weaker ciphers/seclevel for legacy servers."""

    def __init__(self, ssl_context=None, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


def _parse_dt(text):
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _is_stale_running(info: dict) -> bool:
    """running이 오래 지속되면 stale로 간주."""
    if not info or "running" not in (info.get("status") or "").lower():
        return False
    last = _parse_dt(info.get("last_run") or "")
    if not last:
        return True
    delta = datetime.datetime.now() - last
    return delta.total_seconds() > RUN_STALE_SECONDS


def _normalize_status_text(text: str) -> str:
    if not text:
        return "idle"
    t = str(text).lower()
    if "running" in t:
        return "running"
    if "fail" in t or "오류" in t or "중단" in t:
        return "failed"
    if "완료" in t or "done" in t:
        return "done"
    if "대기" in t or "idle" in t:
        return "idle"
    return text


def load_status():
    default_status = {
        lib: {"name": det["name"], "status": "idle", "last_run": "-", "msg": ""}
        for lib, det in LIBRARIES.items()
    }
    if not os.path.exists(STATUS_FILE):
        return default_status
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for lib, det in LIBRARIES.items():
            if lib in saved:
                saved[lib]["name"] = det["name"]
                # 오래된 running/failed 자동 초기화
                info = saved[lib]
                if _is_stale_running(info):
                    saved[lib]["status"] = "idle"
                    saved[lib]["msg"] = "오래된 실행 자동 초기화"
                    saved[lib]["last_run"] = "-"
                else:
                    saved[lib]["status"] = _normalize_status_text(info.get("status", ""))
                    if saved[lib]["status"] == "done":
                        msg = info.get("msg") or ""
                        if ("업데이트 완료" in msg) or ("?? ??" in msg) or (msg.strip() == ""):
                            saved[lib]["msg"] = "정상 완료"
            else:
                saved[lib] = default_status[lib]
        return saved
    except Exception:
        return default_status


def save_status():
    with status_lock:
        try:
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(CRAWLER_STATUS, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


CRAWLER_STATUS = load_status()


def fetch_total_count_from_page(url, name=""):
    """
    Extract total count number from list page HTML. Return -1 on failure.
    Supports Kyobo/YES24 patterns.
    """

    def _parse_total(html):
        # 1) Kyobo: book_resultTxt block strong numbers
        try:
            import lxml.html

            doc = lxml.html.fromstring(html)
            texts = doc.xpath('//div[contains(@class,"book_resultTxt")]//strong/text()')
            candidates = []
            for t in texts:
                digits = re.sub(r"[^\d,]", "", t)
                if digits:
                    candidates.append(int(digits.replace(",", "")))
            if candidates:
                return max(candidates)
        except Exception:
            pass

        # 2) YES24: patterns like '전체 <em>1234</em>건 ( 3 / 200 )'
        m = re.search(r"<em>\s*([\d,]+)\s*</em>\s*건", html, flags=re.IGNORECASE)
        if m:
            return int(m.group(1).replace(",", ""))

        m = re.search(r"\(\s*\d+\s*/\s*([\d,]+)\s*\)", html)
        if m:
            return int(m.group(1).replace(",", ""))

        # 3) Generic strong + digits
        m = re.search(r"<strong>[\s\u00a0]*([\d,]+)[\s\u00a0]*</strong>\s*?", html)
        if m:
            return int(m.group(1).replace(",", ""))

        # 3-1) Bookcube 스타일: "총 11,140종 (16,713권)"
        m = re.search(r"총\s*([\d,]+)\s*종", html)
        if m:
            return int(m.group(1).replace(",", ""))

        # 4) Plain text: digits near '권' or whitespace
        m = re.search(r"[권\s]\s*([\d,]+)\s*", html)
        if m:
            return int(m.group(1).replace(",", ""))

        return -1

    try:
        parsed = requests.utils.urlparse(url)
        is_guro = "ebook.guro.go.kr" in parsed.netloc

        if is_guro:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
            try:
                ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
            except ssl.SSLError:
                pass
            session = requests.Session()
            adapter = TLSAdapter(ssl_context=ctx)
            session.mount("https://", adapter)
            res = session.get(
                url,
                timeout=8,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
                verify=False,
                allow_redirects=True,
            )
        else:
            res = requests.get(
                url,
                timeout=8,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
            )
        if res.status_code != 200:
            print(f"[원격 합계 확인 실패] {name} 응답 코드 {res.status_code}")
            return -1
        total = _parse_total(res.text)
        if total >= 0:
            return total
    except Exception as e:
        print(f"[원격 합계 확인 실패] {name} 오류: {e}")
    return -1


def fetch_total_count_bookcube(url, name=""):
    """
    Bookcube/FxLibrary 계열: JSON 응답이면 TotalCount 사용, 아니면 HTML에서 '총 11,140종' 패턴 파싱.
    """
    try:
        res = requests.get(
            url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        )
        res.raise_for_status()
        # JSON 우선
        try:
            data = res.json()
            contents = data.get("Contents", {}) if isinstance(data, dict) else {}
            total = contents.get("TotalCount") or contents.get("totalCount")
            if total:
                s = str(total).replace(",", "").strip()
                if s.isdigit():
                    return int(s)
        except Exception:
            pass
        # HTML fallback
        html = res.text
        m = re.search(r"총\s*([\d,]+)\s*종", html)
        if m:
            return int(m.group(1).replace(",", ""))
        # 일반 파서로 재시도
        return fetch_total_count_from_page(url, name)
    except Exception as e:
        print(f"[원격 합계 확인 실패] {name} 오류: {e}")
        return -1


def fetch_total_count_from_api(lib_code, config):
    """
    API 기반 도서관 총권수 구하기. 실패 시 -1.
    """
    try:
        if lib_code == "seoul" and get_seoul_total_count:
            return get_seoul_total_count() or -1

        # 서울교육청 소장/구독: 간단히 totalCount 유사 필드를 시도
        if lib_code in {"sen_owned", "sen_subs"}:
            if lib_code == "sen_owned":
                url = "https://e-lib.sen.go.kr/api/contents/page-data"
                params = {
                    "contentType": "TY01",
                    "pageCount": 20,
                    "currentCount": 1,
                    "loanable": "N",
                    "majorCategory": "",
                    "subCategory": "",
                    "tinyCategory": "",
                    "ownerCategory": "",
                    "innerSearchYN": "N",
                    "innerKeyword": "",
                    "orderOption": "1",
                    "typeOption": "1",
                    "_": int(time.time() * 1000),
                }
            else:
                url = "https://e-lib.sen.go.kr/api/contents/catesearch"
                params = {
                    "contentType": "TY02",
                    "pageCount": 24,     # 기본 리스트 페이지 크기
                    "currentCount": 1,    # 첫 페이지만 조회해 total 수집
                    "loanable": "N",
                    "majorCategory": "",
                    "subCategory": "",
                    "tinyCategory": "",
                    "ownerCategory": "",
                    "innerSearchYN": "N",
                    "innerKeyword": "",
                    "orderOption": "1",
                    "typeOption": "1",
                    "_": int(time.time() * 1000),
                }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://e-lib.sen.go.kr/",
                "Accept": "application/json, text/plain, */*",
            }
            res = requests.get(url, params=params, headers=headers, timeout=15)
            res.raise_for_status()
            try:
                data = res.json()
            except Exception:
                preview = res.text[:300].replace("\n", " ")
                print(f"[total_count api] {lib_code} JSON decode 실패, status={res.status_code}, body={preview}")
                return -1
            # 여러 형태 중 존재하는 필드를 우선 사용
            for path in [
                ("CategoryDataList", "bookTotalCount"),  # 구독형 응답의 총 권수
                ("CategoryDataList", "pageTotalCount"),  # 페이지 수만 있을 때 보조
                ("pageData", "contents", "totalCount"),
                ("totalCount",),
                ("currentCount",),
                ("list_total_count",),
            ]:
                d = data
                try:
                    for key in path:
                        d = d[key]
                except Exception:
                    continue
                if isinstance(d, str):
                    s = d.strip()
                    if s.isdigit():
                        d = int(s)
                    else:
                        continue
                # bookTotalCount가 161816.0처럼 float일 수 있음
                if isinstance(d, (int, float)) and d > 0:
                    return int(d)
            # 여기까지 못 찾으면 로그 남기기
            print(f"[total_count api] {lib_code} 응답에서 총권수 필드를 찾지 못함. keys={list(data.keys()) if isinstance(data, dict) else type(data)}")
    except Exception as e:
        print(f"[total_count api] {lib_code} 실패: {e}")
    # 실패 시 -1
    return -1


def check_library_update(lib_code):
    """
    로컬/원격 권수 비교: 로컬 vs 원격 총 권수
    """
    config = LIBRARIES[lib_code]

    local_count = 0
    if os.path.exists(config["db_file"]):
        try:
            with open(config["db_file"], "rb") as f:
                local_count = sum(1 for _ in f) - 1
        except Exception:
            local_count = 0

    remote_count = -1

    if config["type"] == "odcloud":
        remote_count = get_odcloud_total_count(config)
    elif config["type"] == "custom" and lib_code in {"seoul", "sen_owned", "sen_subs"}:
        remote_count = fetch_total_count_from_api(lib_code, config)
    elif lib_code in {"seongdong", "geumcheon", "eunpyeong"} and config.get("total_count_url"):
        remote_count = fetch_total_count_bookcube(config["total_count_url"], config.get("name", lib_code))
    elif config.get("total_count_url"):
        remote_count = fetch_total_count_from_page(config["total_count_url"], config.get("name", lib_code))

    return local_count, remote_count


def smart_update_loop():
    global auto_crawl_active
    while True:
        if auto_crawl_active:
            print("[auto] Checking libraries for updates...")
            for lib_code, config in LIBRARIES.items():
                supported = (config.get("type") == "odcloud") or (lib_code == "mapo") or config.get("total_count_url")
                if not supported:
                    continue
                if "running" in CRAWLER_STATUS.get(lib_code, {}).get("status", ""):
                    continue

                local, remote = check_library_update(lib_code)
                if remote > 0 and local != remote:
                    msg = f"로컬:{local} vs 원격:{remote}"
                    print(f"[{config['name']}] 권수 차이: {msg}")
                    with status_lock:
                        CRAWLER_STATUS[lib_code]["msg"] = msg
                    save_status()
                    run_spider_background(lib_code)
                    time.sleep(5)
                else:
                    with status_lock:
                        CRAWLER_STATUS[lib_code]["msg"] = "변경 없음"
            save_status()
        time.sleep(3600)


scheduler_thread = threading.Thread(target=smart_update_loop, daemon=True)
scheduler_thread.start()


def run_spider_background(lib_code, on_complete_callback=None):
    global CRAWLER_STATUS
    lib_config = LIBRARIES[lib_code]
    cmd = lib_config["cmd"]

    with status_lock:
        CRAWLER_STATUS[lib_code]["status"] = "running"
        CRAWLER_STATUS[lib_code]["msg"] = "실행 중"
        CRAWLER_STATUS[lib_code]["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_status()

    print(f"[START] {lib_config['name']} 크롤 시작")

    try:
        subprocess.run(cmd, cwd=CRAWLER_DIR, check=True)
            try:
                subprocess.run(rebuild_cmd, cwd=ROOT_DIR, check=True)
            except Exception as e:
                print(f"[주의] SQLite 리빌드 오류: {e}")
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = "done"
            CRAWLER_STATUS[lib_code]["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            CRAWLER_STATUS[lib_code]["msg"] = "정상 완료"
        save_status()
        if on_complete_callback:
            on_complete_callback(lib_code, success=True)

    except Exception as e:
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = "failed"
            CRAWLER_STATUS[lib_code]["msg"] = str(e)
            CRAWLER_STATUS[lib_code]["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_status()
        if on_complete_callback:
            on_complete_callback(lib_code, success=False)


def start_crawling(lib_code, on_complete_callback=None):
    with status_lock:
        info = CRAWLER_STATUS.get(lib_code, {})
        if _is_stale_running(info):
            # 오래된 running -> idle로 초기화 후 진행
            CRAWLER_STATUS[lib_code]["status"] = "idle"
            CRAWLER_STATUS[lib_code]["msg"] = "오래된 실행을 초기화"
        elif "running" in (info.get("status") or ""):
            return False
    t = threading.Thread(target=run_spider_background, args=(lib_code, on_complete_callback))
    t.start()
    return True


def reset_status(lib_code=None):
    """지정 도서관(또는 전체) 상태를 idle로 초기화."""
    targets = [lib_code] if lib_code else list(CRAWLER_STATUS.keys())
    with status_lock:
        for code in targets:
            if code in CRAWLER_STATUS:
                CRAWLER_STATUS[code]["status"] = "idle"
                CRAWLER_STATUS[code]["msg"] = ""
                CRAWLER_STATUS[code]["last_run"] = "-"
        save_status()
    return True


def set_auto_crawl(is_active):
    global auto_crawl_active
    auto_crawl_active = is_active
    return auto_crawl_active
