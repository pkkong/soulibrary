# web/crawler_manager.py (마포구 스마트 업데이트 포함)

import subprocess
import threading
import datetime
import os
import json
import time
import pandas as pd
import requests # import 추가 확인
import re # import 추가 확인
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crawler.odcloud_downloader import get_odcloud_total_count
from config import LIBRARIES, CRAWLER_DIR, STATUS_FILE

status_lock = threading.Lock()
auto_crawl_active = False

def load_status():
    default_status = {lib: {"name": det["name"], "status": "대기", "last_run": "-", "msg": ""} for lib, det in LIBRARIES.items()}
    if not os.path.exists(STATUS_FILE): return default_status
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        for lib, det in LIBRARIES.items():
            if lib in saved:
                saved[lib]["name"] = det["name"]
                if "실행" in saved[lib]["status"]: saved[lib]["status"] = "대기 (중단됨)"
            else:
                saved[lib] = default_status[lib]
        return saved
    except: return default_status

def save_status():
    with status_lock:
        try:
            with open(STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(CRAWLER_STATUS, f, indent=2, ensure_ascii=False)
        except: pass

CRAWLER_STATUS = load_status()

def check_library_update(lib_code):
    """
    스마트 업데이트: 로컬 vs 원격 개수 비교
    """
    config = LIBRARIES[lib_code]
    
    local_count = 0
    if os.path.exists(config['db_file']):
        try:
            with open(config['db_file'], 'rb') as f:
                local_count = sum(1 for _ in f) - 1
        except: local_count = 0
            
    remote_count = -1
    
    # 1. Odcloud API
    if config['type'] == 'odcloud':
        remote_count = get_odcloud_total_count(config)
        
    # 2. [신규] 마포구 (HTML 파싱)
    elif lib_code == 'mapo':
        try:
            url = "https://ebook.mapo.go.kr/Kyobo_T3/Content/ebook/ebook_Main.asp?product_cd=001&content_all=Y"
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                # 패턴: "총 <strong>5,607</strong>개의 자료"
                match = re.search(r'총\s*<strong>\s*([\d,]+)\s*</strong>', res.text)
                if match:
                    remote_count = int(match.group(1).replace(',', ''))
        except Exception as e:
            print(f"[확인 실패] 마포구: {e}")

    return local_count, remote_count

def smart_update_loop():
    global auto_crawl_active
    while True:
        if auto_crawl_active:
            print("🔍 [자동 감지] 업데이트 확인 중...")
            for lib_code, config in LIBRARIES.items():
                # 지원되는 타입(odcloud, mapo)만 체크
                if config['type'] != 'odcloud' and lib_code != 'mapo': continue
                
                if "실행" in CRAWLER_STATUS[lib_code]["status"]: continue

                local, remote = check_library_update(lib_code)
                
                if remote > 0 and local != remote:
                    msg = f"감지됨(로컬:{local} vs 서버:{remote})"
                    print(f"⚡ [{config['name']}] 업데이트 필요! {msg}")
                    with status_lock: CRAWLER_STATUS[lib_code]["msg"] = msg
                    save_status()
                    run_spider_background(lib_code)
                    time.sleep(5) 
                else:
                    with status_lock: CRAWLER_STATUS[lib_code]["msg"] = "최신 상태"
            save_status()
        time.sleep(3600) 

scheduler_thread = threading.Thread(target=smart_update_loop, daemon=True)
scheduler_thread.start()

def run_spider_background(lib_code, on_complete_callback=None):
    global CRAWLER_STATUS
    lib_config = LIBRARIES[lib_code]
    cmd = lib_config["cmd"]

    with status_lock:
        CRAWLER_STATUS[lib_code]["status"] = "실행 중..."
        CRAWLER_STATUS[lib_code]["msg"] = "데이터 수집 중..."
    save_status()
    
    print(f"🚀 [{lib_config['name']}] 크롤링 시작!")

    try:
        subprocess.run(cmd, cwd=CRAWLER_DIR, check=True)
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = "완료 (대기)"
            CRAWLER_STATUS[lib_code]["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            CRAWLER_STATUS[lib_code]["msg"] = "업데이트 완료"
        save_status()
        if on_complete_callback: on_complete_callback(lib_code, success=True)

    except Exception as e:
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = f"오류 발생"
            CRAWLER_STATUS[lib_code]["msg"] = str(e)
        save_status()
        if on_complete_callback: on_complete_callback(lib_code, success=False)

def start_crawling(lib_code, on_complete_callback=None):
    with status_lock:
        if "실행" in CRAWLER_STATUS.get(lib_code, {}).get("status", ""): return False
    t = threading.Thread(target=run_spider_background, args=(lib_code, on_complete_callback))
    t.start()
    return True

def set_auto_crawl(is_active):
    global auto_crawl_active
    auto_crawl_active = is_active
    return auto_crawl_active