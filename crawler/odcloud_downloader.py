# crawler/odcloud_downloader.py (ISBN 수집 기능 추가)

import requests
import pandas as pd
import os
import sys
import json

# [중요] web 폴더의 config를 import하기 위한 설정
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    # 1. web/config.py에서 설정값들을 가져옴
    from web.config import LIBRARIES, ODCLOUD_API_KEY
except ImportError:
    print("="*50)
    print(" [오류] web/config.py 파일을 찾을 수 없습니다. ")
    print("="*50)
    sys.exit(1)

def download_odcloud_books(lib_code, config):
    """
    config 정보를 바탕으로 Odcloud API에서 데이터를 다운로드합니다.
    """
    all_books = []
    page = 1
    per_page = 1000 
    
    base_url = config['api_url']
    lib_name = config['name']
    
    print(f"--- [{lib_name}] Odcloud API 데이터 다운로드 시작 ---")
    print(f"API URL: {base_url}")

    while True:
        params = {
            "page": page,
            "perPage": per_page,
            "serviceKey": ODCLOUD_API_KEY # 2. config에서 불러온 공통 키
        }
        
        try:
            print(f"Page {page} 요청 중... ", end="")
            response = requests.get(base_url, params=params)
            
            if response.status_code != 200:
                print(f"\n[오류] 상태 코드 {response.status_code}")
                break
                
            data = response.json()
            
            current_list = data.get('data', [])
            total_count = data.get('totalCount', 0)
            
            if not current_list:
                print("데이터 없음. (완료)")
                break
                
            print(f"성공! ({len(current_list)}권)")
            all_books.extend(current_list)
            
            if len(all_books) >= total_count:
                print(f"--- 총 {total_count}권 수집 완료 ---")
                break
            
            page += 1
            
        except Exception as e:
            print(f"\n[오류] Page {page} 요청 실패: {e}")
            break

    return all_books

def save_to_csv(books, config):
    """
    config 정보를 바탕으로 데이터를 CSV로 저장합니다.
    (ISBN 수집 로직 추가됨)
    """
    if not books:
        print("저장할 데이터가 없습니다.")
        return

    print(f"\n총 {len(books)}권 데이터 필터링 및 저장 중...")
    
    df = pd.DataFrame(books)
    
    # 1. (기존) 컬럼 매핑
    rename_map = config.get('column_map', {})
    df = df.rename(columns=rename_map)
    
    # 2. 👈 [핵심] ISBN 컬럼 매핑 (신규)
    isbn_map_key = config.get('isbn_map') # 예: "국제표준도서번호"
    
    if isbn_map_key and isbn_map_key in df.columns:
        print(f"-> '{isbn_map_key}' 컬럼에서 ISBN 정보 수집...")
        df = df.rename(columns={isbn_map_key: 'isbn'})
    else:
        # isbn_map이 None이거나, API 결과에 해당 컬럼이 없으면
        df['isbn'] = "" # 👈 ISBN 컬럼을 빈 칸으로 생성

    # 3. (기존) 오디오북 필터링
    filter_col = config.get('format_filter_column')
    
    if filter_col and filter_col in df.columns:
        ebook_df = df[~df[filter_col].str.contains("오디오", case=False, na=False)].copy()
        print(f"-> 오디오북 제외 후: {len(ebook_df)}권 (전자책)")
    else:
        print("[알림] 오디오북 필터링이 설정되지 않았거나 컬럼이 없습니다. 전체 저장합니다.")
        ebook_df = df

    # 4. (기존) 필수 컬럼 채우기
    # 👈 [수정] 'isbn'을 표준 컬럼 리스트에 추가
    standard_columns = ['title', 'author', 'publisher', 'library', 'image_url', 'isbn']
    
    for col in standard_columns:
        if col not in ebook_df.columns:
            ebook_df[col] = "" # 정보 없으면 빈 칸
    
    ebook_df['library'] = config['library_name'] 
    
    # 5. 👈 [수정] 최종 저장할 컬럼 목록에 'isbn' 추가
    final_df = ebook_df[standard_columns]
    
    output_file = config['db_file'] 
    
    final_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"✅ 저장 완료: {output_file}")



# crawler/odcloud_downloader.py (맨 아래에 추가)

def get_odcloud_total_count(config):
    """
    [스마트 업데이트용]
    데이터를 다운로드하지 않고, API에 접속해 '전체 도서 개수'만 확인해서 반환합니다.
    """
    base_url = config['api_url']
    # 1개만 요청해서 헤더 정보(totalCount)만 봅니다.
    params = {
        "page": 1,
        "perPage": 1, 
        "serviceKey": ODCLOUD_API_KEY
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=5)
        if response.status_code != 200:
            return -1 # 에러 발생 시 -1 반환
            
        data = response.json()
        # API마다 totalCount 키가 다를 수 있으니 안전하게 가져옵니다.
        total_count = data.get('totalCount', data.get('currentCount', 0))
        return int(total_count)
        
    except Exception as e:
        print(f"[확인 실패] {config['name']} : {e}")
        return -1




# --- 메인 실행 ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(" [오류] 실행할 도서관 코드를 입력해야 합니다.")
        print(f" 예: python {sys.argv[0]} seongbuk")
        sys.exit(1)
        
    lib_code = sys.argv[1] # "seongbuk"
    
    if lib_code not in LIBRARIES or LIBRARIES[lib_code].get('type') != 'odcloud':
        print(f" [오류] '{lib_code}'는 web/config.py에 정의되지 않았거나 'odcloud' 타입이 아닙니다.")
        sys.exit(1)
        
    config = LIBRARIES[lib_code]
    
    books = download_odcloud_books(lib_code, config)
    save_to_csv(books, config)






