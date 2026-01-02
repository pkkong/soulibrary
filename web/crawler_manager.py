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

import requests

# Ensure project root is on sys.path so that "crawler.*" imports work when running from /web
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config import LIBRARIES, CRAWLER_DIR, STATUS_FILE
from crawler.odcloud_downloader import get_odcloud_total_count

ROOT_DIR = os.path.dirname(CRAWLER_DIR)
status_lock = threading.Lock()
auto_crawl_active = False


class TLSAdapter(requests.adapters.HTTPAdapter):
    """Custom TLS adapter to allow weaker ciphers/seclevel for legacy servers."""

    def __init__(self, ssl_context=None, **kwargs):
        self.ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs["ssl_context"] = self.ssl_context
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


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
            print(f"[??? ?? ??] {name} ???? {res.status_code}")
            return -1
        total = _parse_total(res.text)
        if total >= 0:
            return total
    except Exception as e:
        print(f"[??? ?? ??] {name} ?? ??: {e}")
    return -1


def check_library_update(lib_code):
    """
    ??? ????: ?? vs ?? ?? ??
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
                    msg = f"??:{local} vs ??:{remote}"
                    print(f"[{config['name']}] ???? ??: {msg}")
                    with status_lock:
                        CRAWLER_STATUS[lib_code]["msg"] = msg
                    save_status()
                    run_spider_background(lib_code)
                    time.sleep(5)
                else:
                    with status_lock:
                        CRAWLER_STATUS[lib_code]["msg"] = "?? ??"
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
        CRAWLER_STATUS[lib_code]["msg"] = "??? ?"
    save_status()

    print(f"[START] {lib_config['name']} ??? ??")

    try:
        subprocess.run(cmd, cwd=CRAWLER_DIR, check=True)
        try:
            rebuild_cmd = ["python", "scripts/build_sqlite.py"]
            subprocess.run(rebuild_cmd, cwd=ROOT_DIR, check=True)
        except Exception as e:
            print(f"[??] SQLite ??? ??: {e}")
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = "done"
            CRAWLER_STATUS[lib_code]["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            CRAWLER_STATUS[lib_code]["msg"] = "?? ??"
        save_status()
        if on_complete_callback:
            on_complete_callback(lib_code, success=True)

    except Exception as e:
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = "failed"
            CRAWLER_STATUS[lib_code]["msg"] = str(e)
        save_status()
        if on_complete_callback:
            on_complete_callback(lib_code, success=False)


def start_crawling(lib_code, on_complete_callback=None):
    with status_lock:
        if "running" in CRAWLER_STATUS.get(lib_code, {}).get("status", ""):
            return False
    t = threading.Thread(target=run_spider_background, args=(lib_code, on_complete_callback))
    t.start()
    return True


def set_auto_crawl(is_active):
    global auto_crawl_active
    auto_crawl_active = is_active
    return auto_crawl_active
