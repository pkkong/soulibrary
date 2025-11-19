# web/app.py (도서관 링크 기능 추가된 Full Version)

import os
import pandas as pd
import json
import threading
import re 
from flask import Flask, render_template, request, jsonify
from config import LIBRARIES, STATUS_FILE 

try:
    from crawler_manager import CRAWLER_STATUS, start_crawling
except ImportError:
    CRAWLER_STATUS = {}
    def start_crawling(code, cb=None): return False

app = Flask(__name__)
db_lock = threading.Lock()

DB_FILES = {lib: det["db_file"] for lib, det in LIBRARIES.items()}

# ----------------------------------------------------------------
# 🚨 [신규] 도서관 이름 -> URL 매핑 딕셔너리 생성 (초고속 조회용)
# ----------------------------------------------------------------
LIB_URL_MAP = {}
for lib_code, info in LIBRARIES.items():
    # DB에 저장된 library_name을 키로, homepage_url을 값으로 매핑
    LIB_URL_MAP[info['library_name']] = info.get('homepage_url', '#')

# ----------------------------------------------------------------

def first_valid_image(series):
    for img in series:
        if img and pd.notna(img): return img
    return "" 

def normalize_title(text):
    if not text or pd.isna(text): return ""
    text = str(text).lower()
    text = re.sub(r'\[.*?\]|\(.*?\)', '', text) 
    text = re.sub(r'(\d)\s*(권|부|편|화)', r'\1', text)
    text = re.sub(r'[^\w\s]', '', text).strip()
    text = re.sub(r'\s+', '', text)
    return text

def normalize_author(text):
    if not text or pd.isna(text): return ""
    text = str(text)
    text = re.sub(r'[<>()\[\]]', ' ', text)
    split_chars = r'[,/|]'
    if re.search(split_chars, text):
        text = re.split(split_chars, text, 1)[0]
    roles = r'(원작|지음|지은이|저|엮음|그림|글|옮김|역|저자)'
    text = re.sub(roles, '', text)
    text = re.sub(r'[^\w\s]', '', text).lower().strip()
    text = re.sub(r'\s+', '', text)
    return text

# 🚨 [신규] 도서관 목록을 [{name: '...', url: '...'}, ...] 형태로 변환하는 함수
def build_library_objects(series):
    unique_libs = series.unique()
    result = []
    for lib_name in unique_libs:
        result.append({
            'name': lib_name,
            'url': LIB_URL_MAP.get(lib_name, '#') # 매핑된 URL이 없으면 #
        })
    return result


def load_database():
    all_data = []
    print("--- [시스템] 통합 DB 로딩 중... ---")
    STANDARD_COLUMNS = ['title', 'author', 'publisher', 'library', 'image_url', 'isbn']
    
    for lib_code, db_file in DB_FILES.items(): 
        if not os.path.exists(db_file): continue
        try:
            print(f"📄 읽는 중: {os.path.basename(db_file)}")
            if db_file.endswith(".csv"):
                df = pd.read_csv(db_file, dtype=str).fillna("")
            elif db_file.endswith(".json"):
                df = pd.read_json(db_file, dtype=str).fillna("")
            
            lib_config = LIBRARIES[lib_code]
            prefix = lib_config.get("url_prefix")

            if 'image_url' in df.columns:
                if prefix: 
                    df['image_url'] = df['image_url'].apply(lambda x: f"{prefix}{x}" if str(x).startswith('/') else x)
                elif "sen_" in lib_code: 
                    df['image_url'] = df['image_url'].apply(lambda x: x.replace("http://", "https://") if str(x).startswith('http://') else x)
            
            for col in STANDARD_COLUMNS:
                if col not in df.columns: df[col] = "" 
            
            df = df[STANDARD_COLUMNS]
            all_data.append(df)
        except Exception as e:
            print(f"[오류] 로딩 실패 ({db_file}): {e}")

    if not all_data: return pd.DataFrame()

    master_db = pd.concat(all_data, ignore_index=True)
    master_db['isbn'] = master_db['isbn'].fillna("").astype(str)
    print(f"--- [완료] 총 {len(master_db)}권 통합 DB 준비됨. ---")
    return master_db

def reload_database_safely(lib_code=None, success=True):
    if not success: return
    global library_db
    print(f"--- [{lib_code}] DB 리로드 시작 ---")
    new_db = load_database()
    with db_lock: library_db = new_db
    print(f"--- DB 리로드 완료 ---")

library_db = load_database()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search')
def search():
    query = request.args.get('query', '').strip()
    if not query: return jsonify([])

    RAW_LIMIT = 1500  
    FINAL_LIMIT = 300 

    with db_lock:
        if library_db.empty: return jsonify([])
        try:
            raw_results = library_db[
                library_db['title'].str.contains(query, case=False) | 
                library_db['author'].str.contains(query, case=False)
            ].head(RAW_LIMIT).copy()
            
            if raw_results.empty: return jsonify([])

            # 정규화
            raw_results['norm_title'] = raw_results['title'].apply(normalize_title)
            raw_results['norm_author'] = raw_results['author'].apply(normalize_author)
            
            # 통합 그룹핑
            grouped_results = raw_results.groupby(
                ['norm_title', 'norm_author']
            ).agg(
                title=('title', 'first'), 
                author=('author', 'first'),
                publisher=('publisher', 'first'),
                image_url=('image_url', first_valid_image),
                
                # 🚨 [수정] 도서관 목록을 URL 포함 객체 리스트로 변환
                library=('library', build_library_objects) 
                
            ).reset_index()

            final_results = grouped_results.drop(
                columns=['norm_title', 'norm_author']
            ).head(FINAL_LIMIT)
            
            return jsonify(final_results.to_dict('records')) 
        
        except Exception as e:
            print(f"[오류] 검색 중: {e}")
            return jsonify({"error": "검색 중 오류 발생"})

@app.route('/admin')
def admin_page():
    return render_template('admin.html', status=CRAWLER_STATUS)

@app.route('/admin/run/<lib_code>', methods=['POST'])
def run_crawler(lib_code):
    if start_crawling(lib_code, on_complete_callback=reload_database_safely):
        return jsonify({"success": True, "msg":f"{LIBRARIES[lib_code]['name']} 시작"})
    else:
        return jsonify({"success": False, "msg": "이미 실행 중"})

@app.route('/admin/status')
def get_status():
    return jsonify(CRAWLER_STATUS)

# (자동갱신용 라우트, import 필요하면 추가하세요)
from crawler_manager import set_auto_crawl 
@app.route('/admin/auto-crawl', methods=['POST'])
def toggle_auto_crawl():
    data = request.get_json()
    is_active = data.get('active', False)
    current_state = set_auto_crawl(is_active)
    msg = "✅ 자동 갱신 ON" if current_state else "🛑 자동 갱신 OFF"
    return jsonify({"success": True, "active": current_state, "msg": msg})

if __name__ == '__main__':
    # host='0.0.0.0'은 "누구나 접속 들어오세요"라는 뜻입니다.
    app.run(host='0.0.0.0', port=5000)