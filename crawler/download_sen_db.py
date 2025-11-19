import requests
import pandas as pd
import time
import os
import xml.etree.ElementTree as ET # XML 파서

# 저장 경로
OUTPUT_FILE = "../data/sen_owned_db.csv" # "소장형" 전용 DB 파일

# API 설정 (소장형 1개만)
URL_OWNED = "https://e-lib.sen.go.kr/api/contents/page-data"
CONTENT_TYPE_OWNED = "TY01"
LABEL = "소장형"

def download_sen_api(url, content_type, label):
    """
    '소장형' API를 1000개씩 반복 호출하여 다운로드합니다.
    (아까 성공했던 로직)
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
            
            # XML 파싱
            root = ET.fromstring(response.content)
            
            # XML에서 <ContentDataList> 경로 찾기
            book_list_xml = root.findall(".//contents/ContentDataList")
            if not book_list_xml:
                book_list_xml = root.findall(".//pageData/contents/ContentDataList")
                
            if not book_list_xml:
                print("데이터 없음. (완료)")
                break
                
            print(f"성공! ({len(book_list_xml)}권)")
            
            # XML에서 데이터 뽑기
            for book_xml in book_list_xml:
                all_books.append({
                    'title': book_xml.findtext('title'),
                    'author': book_xml.findtext('author'),
                    'publisher': book_xml.findtext('publisher'),
                    'image_url': book_xml.findtext('coverUrl'), 
                    'library_type': book_xml.findtext('contentsTypeDesc'), 
                    'vendor': book_xml.findtext('ownerDesc') 
                })
            
            # 마지막 페이지 체크
            if len(book_list_xml) < per_page:
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

    # [수정] books가 리스트 2개가 아니라 1개만 들어오므로 [] 제거
    print(f"\n데이터 통합 및 저장 중... (총 {len(books)}권)")
    df = pd.DataFrame(books)
    
    # 더 풍부한 도서관 이름 생성
    try:
        df['library'] = df.apply(lambda row: f"서울시교육청 ({row['library_type']} / {row['vendor']})", axis=1)
    except:
        df['library'] = '서울시교육청 (소장형)'
    
    # 중복 제거 (제목+저자)
    df = df.drop_duplicates(subset=['title', 'author'])
    print(f"-> 중복 제거 후 최종 {len(df)}권")

    final_df = df[['title', 'author', 'publisher', 'library', 'image_url']]
    
    final_df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
    print(f"✅ 저장 완료: {OUTPUT_FILE}")

# --- 메인 실행 ---
if __name__ == "__main__":
    # 1. 소장형(TY01)만 다운로드
    owned_data = download_sen_api(URL_OWNED, CONTENT_TYPE_OWNED, LABEL)
    
    # 2. 저장
    save_to_csv(owned_data)