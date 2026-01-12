import requests
import pandas as pd
import time
import os
# (XML 파서 'ET'는 필요 없습니다)

# 저장 경로
OUTPUT_FILE = "../data/sen_owned_db.csv" # "소장형" 전용 DB 파일

# API 설정 (소장형 1개만)
URL_OWNED = "https://e-lib.sen.go.kr/api/contents/page-data"
CONTENT_TYPE_OWNED = "TY01"
LABEL = "소장형"

def download_sen_api(url, content_type, label):
    """
    '소장형' API를 1000개씩 반복 호출하여 다운로드합니다.
    (JSON 파싱으로 되돌린 버전)
    """
    all_books = []
    page = 1
    per_page = 1000 # 1000개씩 요청
    
    print(f"--- [서울시교육청] '{label}' ({content_type}) API 다운로드 시작 ---")

    while True:
        # [핵심] 모든 파라미터 전송
        params = {
            "contentType": content_type, "majorCategory": "", "subCategory": "",
            "tinyCategory": "", "ownerCategory": "", "innerSearchYN": "N",
            "innerKeyword": "", "orderOption": "1", "typeOption": "1",
            "currentCount": page,
            "pageCount": per_page,
            "loanable": "N",
            "_": int(time.time() * 1000) 
        }
        
        try:
            print(f"Page {page} ({per_page}개씩) 요청 중... ", end="")
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "https://e-lib.sen.go.kr/"
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=60)
            response.raise_for_status()
            
            # ★★★ JSON으로 파싱 (이게 정답) ★★★
            data = response.json()
            
            # JSON 키 경로로 '책 목록' 찾기
            book_list = [] # ★★★ 변수 이름 원복 ★★★
            if 'pageData' in data and 'contents' in data['pageData']:
                 book_list = data['pageData']['contents'].get('ContentDataList', [])
            
            if not book_list:
                print("데이터 없음. (완료)")
                break
                
            print(f"성공! ({len(book_list)}권)")
            
            # JSON에서 데이터 뽑기
            for book_json in book_list:
                all_books.append({
                    'title': book_json.get('title'),
                    'author': book_json.get('author'),
                    'publisher': book_json.get('publisher'),
                    'image_url': book_json.get('coverUrl'), 
                    'library_type': book_json.get('contentsTypeDesc'), 
                    'vendor': book_json.get('ownerDesc') 
                })
            
            # ★★★ 변수 이름 원복 ★★★
            if len(book_list) < per_page:
                print(f"--- '{label}' 수집 완료 ---")
                break
            
            page += 1
            time.sleep(1) # 1000개씩이니 1초 쉬기
            
        except Exception as e:
            print(f"\n[오류] Page {page} 요청 실패: {e}")
            break

    return all_books

def save_to_csv(books):
    if not books:
        print("저장할 데이터가 없습니다.")
        return

    print(f"\n데이터 통합 및 저장 중... (총 {len(books)}권)")
    df = pd.DataFrame(books)
    
    # 더 풍부한 도서관 이름 생성
    try:
        df['library'] = df.apply(lambda row: f"서울시교육청 ({row['library_type']} / {row['vendor']})", axis=1)
    except:
        df['library'] = '서울시교육청 (소장형)'
    
    final_df = df[['title', 'author', 'publisher', 'library', 'image_url']]
    
    final_df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
    print(f"✅ 저장 완료: {OUTPUT_FILE}")

# --- 메인 실행 ---
if __name__ == "__main__":
    # 1. 소장형(TY01)만 다운로드
    owned_data = download_sen_api(URL_OWNED, CONTENT_TYPE_OWNED, LABEL)
    
    # 2. 저장
    save_to_csv(owned_data)
