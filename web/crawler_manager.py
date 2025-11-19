# web/crawler_manager.py (스마트 업데이트 기능 추가)

import subprocess
import threading
import datetime
import os
import json
import time
import pandas as pd
import sys

# crawler 폴더의 모듈을 가져오기 위해 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from crawler.odcloud_downloader import get_odcloud_total_count # 👈 1단계에서 만든 함수 import
from config import LIBRARIES, CRAWLER_DIR, STATUS_FILE

status_lock = threading.Lock()
auto_crawl_active = False # 👈 자동 갱신 On/Off 스위치 (기본값 Off)

# --- (기존 load_status, save_status 함수는 동일하게 유지) ---
def load_status():
    default_status = {lib: {"name": det["name"], "status": "대기", "last_run": "-", "msg": ""} for lib, det in LIBRARIES.items()}
    if not os.path.exists(STATUS_FILE): return default_status
    try:
        with open(STATUS_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        # 병합 로직
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


# --- [신규] 스마트 업데이트 체크 로직 ---
def check_library_update(lib_code):
    """
    특정 도서관의 로컬 DB 개수 vs API 총 개수를 비교합니다.
    """
    config = LIBRARIES[lib_code]
    
    # 1. 로컬 DB 개수 확인
    local_count = 0
    if os.path.exists(config['db_file']):
        try:
            # CSV 파일의 라인 수만 빠르게 셉니다 (헤더 제외)
            with open(config['db_file'], 'rb') as f:
                local_count = sum(1 for _ in f) - 1
        except:
            local_count = 0
            
    # 2. 원격 API 개수 확인
    remote_count = -1
    if config['type'] == 'odcloud':
        remote_count = get_odcloud_total_count(config)
    
    # (Scrapy나 Custom은 로직이 복잡해 일단 패스하거나 별도 구현 필요)
    
    return local_count, remote_count

def smart_update_loop():
    """
    [백그라운드 스레드]
    auto_crawl_active가 True일 때, 주기적으로 도서관 상태를 체크하고 업데이트합니다.
    """
    global auto_crawl_active
    print("🔄 [시스템] 스마트 자동 갱신 스케줄러가 시작되었습니다.")
    
    while True:
        if auto_crawl_active:
            print("🔍 [자동 감지] 전체 도서관 업데이트 확인 중...")
            
            for lib_code, config in LIBRARIES.items():
                # Odcloud 타입만 자동 체크 지원
                if config['type'] != 'odcloud': continue
                
                # 현재 실행 중이면 건너뜀
                if "실행" in CRAWLER_STATUS[lib_code]["status"]: continue

                local, remote = check_library_update(lib_code)
                
                if remote > 0 and local != remote:
                    msg = f"감지됨(로컬:{local} vs 서버:{remote})"
                    print(f"⚡ [{config['name']}] 업데이트 필요! {msg}")
                    
                    # 상태 메시지 업데이트
                    with status_lock:
                        CRAWLER_STATUS[lib_code]["msg"] = msg
                    save_status()
                    
                    # 🚀 [자동 실행] 차이가 나면 크롤러 실행!
                    run_spider_background(lib_code)
                    
                    # 한 번에 너무 많이 실행되지 않게 약간 대기
                    time.sleep(5) 
                else:
                    # 일치하면 메시지 클리어
                    with status_lock:
                        CRAWLER_STATUS[lib_code]["msg"] = "최신 상태"
            
            save_status()
            
        # 1시간(3600초)마다 검사 (테스트할 땐 60초로 줄여보세요)
        time.sleep(3600) 


# 스케줄러 스레드 시작 (서버 켜질 때 1번 실행)
scheduler_thread = threading.Thread(target=smart_update_loop, daemon=True)
scheduler_thread.start()


# --- (기존 run_spider_background, start_crawling 함수) ---
def run_spider_background(lib_code, on_complete_callback=None):
    # ... (기존 코드 유지, 성공 시 msg 초기화 추가) ...
    global CRAWLER_STATUS
    lib_config = LIBRARIES[lib_code]
    cmd = lib_config["cmd"]

    with status_lock:
        CRAWLER_STATUS[lib_code]["status"] = "실행 중..."
        CRAWLER_STATUS[lib_code]["msg"] = "데이터 수집 중..." # 메시지 변경
    save_status()
    
    print(f"🚀 [{lib_config['name']}] 크롤링 시작!")

    try:
        subprocess.run(cmd, cwd=CRAWLER_DIR, check=True)
        
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = "완료 (대기)"
            CRAWLER_STATUS[lib_code]["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            CRAWLER_STATUS[lib_code]["msg"] = "업데이트 완료" # 메시지 변경
        save_status()
        
        if on_complete_callback:
            on_complete_callback(lib_code, success=True)

    except Exception as e:
        with status_lock:
            CRAWLER_STATUS[lib_code]["status"] = f"오류 발생"
            CRAWLER_STATUS[lib_code]["msg"] = str(e)
        save_status()
        if on_complete_callback:
            on_complete_callback(lib_code, success=False)

def start_crawling(lib_code, on_complete_callback=None):
    with status_lock:
        if "실행" in CRAWLER_STATUS.get(lib_code, {}).get("status", ""):
            return False
    t = threading.Thread(target=run_spider_background, args=(lib_code, on_complete_callback))
    t.start()
    return True

# --- [신규] 외부에서 스위치 켜고 끄는 함수 ---
def set_auto_crawl(is_active):
    global auto_crawl_active
    auto_crawl_active = is_active
    return auto_crawl_active