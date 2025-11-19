import requests
import json
import math
import os

# 1. 'k'를 'b'로 수정한 ★올바른★ 인증키
API_KEY = "745942496d6b6f6e383774624c4c56"

# 2. API 요청 정보 (json 요청)
SERVICE_NAME = "SeoulLibraryBookSearchInfo"
BASE_URL = f"http://openapi.seoul.go.kr:8088/{API_KEY}/json/{SERVICE_NAME}"
BOOKS_PER_PAGE = 1000  # API가 한 번에 주는 최대 개수

# collect_seoul.py 상단
OUTPUT_FILE = "../data/seoul_ebook_db.json"

# 4. 우리가 찾은 '전자책 꼬리표' (요청인자)
EBOOK_FILTER_CODE = "ze" # BIB_TYPE == "ze"

# 5. 우리가 찾은 '필터 경로' (테스트 2-A 성공)
FILTER_PATH = f" / / / /{EBOOK_FILTER_CODE}/" # (앞뒤 공백과 /가 중요)

def get_total_ebook_count():
    """ 
    [필터 적용] '전자책'('ze')의 총 개수가 몇 개인지 확인합니다.
    """
    try:
        # 우리가 '테스트 2-A'에서 성공한 그 주소 (1~1권 요청)
        # ★★★ 1/1/ 뒤에 '/'를 추가했습니다. ★★★
        test_url = f"{BASE_URL}/1/1/{FILTER_PATH}"

        print(f"API '전자책' 총 개수 확인 중... (요청: {test_url})")
        response = requests.get(test_url, timeout=10)
        response.raise_for_status() 

        data = response.json()

        if SERVICE_NAME in data:
            total_count = data[SERVICE_NAME].get('list_total_count')
            if total_count:
                return total_count

        print(f"오류: 'list_total_count'를 찾을 수 없습니다.")
        return None

    except Exception as e:
        print(f"API 총 개수 확인 중 오류: {e}")
        return None

def download_all_ebooks(total_ebook_count):
    """
    '전자책' 총 개수(29,409)만큼, 1000개씩 '반복' 호출하여 다운로드합니다.
    """

    # 29,409권을 1000개씩 받으려면 30번 반복
    total_pages = math.ceil(total_ebook_count / BOOKS_PER_PAGE)

    print(f"총 {total_ebook_count}권의 '전자책' 데이터를 {total_pages}번에 나눠서 다운로드합니다...")

    final_ebook_list = [] # '전자책'만 저장할 리스트

    for i in range(total_pages):
        start_index = (i * BOOKS_PER_PAGE) + 1
        end_index = (i + 1) * BOOKS_PER_PAGE

        if end_index > total_ebook_count:
            end_index = total_ebook_count

        # *** 여기가 핵심 (필터 적용된 요청) ***
        # ★★★ {start_index}/{end_index}/ 뒤에 '/'를 추가했습니다. ★★★
        request_url = f"{BASE_URL}/{start_index}/{end_index}/{FILTER_PATH}"

        print(f"({i+1}/{total_pages}) 페이지 다운로드 중... ( {start_index}~{end_index} )")

        try:
            response = requests.get(request_url, timeout=30)
            response.raise_for_status()

            data = response.json()

            # 'row' 안에 (필터링된) 책 목록이 들어있음
            books_in_page = data.get(SERVICE_NAME, {}).get('row', [])

            if not books_in_page:
                print(f"  -> {i+1} 페이지에 데이터가 없습니다. (혹시 {total_pages}페이지가 마지막?)")
                continue # 다음 페이지로 (혹시 모르니)

            print(f"  -> ★ 전자책 {len(books_in_page)}권 발견! ★")
            for book in books_in_page:
                final_ebook_list.append({
                    'title': book.get('TITLE'),
                    'author': book.get('AUTHOR'),
                    'publisher': book.get('PUBLER'),
                    'library': '서울도서관 (API)'
                })

        except Exception as e:
            print(f"  -> {i+1} 페이지 다운로드 중 오류: {e}")

    return final_ebook_list

def save_ebooks_to_json(final_ebook_list):
    """
    '전자책' 리스트를 JSON 파일로 저장합니다.
    """
    if not final_ebook_list:
        print("저장할 전자책이 없습니다.")
        return

    print(f"\n총 {len(final_ebook_list)}권의 '전자책' 데이터를 저장합니다...")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_ebook_list, f, ensure_ascii=False, indent=2)

    print(f"\n성공! '{OUTPUT_FILE}' 파일에 {len(final_ebook_list)}권의 전자책 DB 저장을 완료했습니다.")


# --- 메인 실행 ---
if __name__ == "__main__":
    print(f"--- 서울도서관 API '전자책(ze)' DB 다운로더 시작 ---")

    # 1. '전자책'의 총 개수 확인 (29,409)
    total_ebook_count = get_total_ebook_count()

    if total_ebook_count:
        # 2. '전자책'만 다운로드 (30번 반복)
        final_ebook_list = download_all_ebooks(total_ebook_count)

        # 3. '전자책'만 JSON으로 저장
        save_ebooks_to_json(final_ebook_list)
    else:
        print("총 개수를 가져오는 데 실패하여 중단합니다.")