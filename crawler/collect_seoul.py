import csv
import math
import requests

# API 설정
API_KEY = "745942496d6b6f6e383774624c4c56"
SERVICE_NAME = "SeoulLibraryBookSearchInfo"
BASE_URL = f"http://openapi.seoul.go.kr:8088/{API_KEY}/json/{SERVICE_NAME}"
BOOKS_PER_PAGE = 1000  # API 허용 최대 페이지 크기

# 출력 파일(관별 CSV 규칙에 맞춤: seoul_db.csv -> library_code == 'seoul')
OUTPUT_FILE = "../data/seoul_db.csv"

# EBOOK 필터
EBOOK_FILTER_CODE = "ze"  # BIB_TYPE == "ze"
FILTER_PATH = f" / / / /{EBOOK_FILTER_CODE}/"


def get_total_ebook_count():
    """전자책 전체 건수를 조회한다."""
    try:
        test_url = f"{BASE_URL}/1/1/{FILTER_PATH}"
        print(f"API 총건수 조회 요청... ({test_url})")
        response = requests.get(test_url, timeout=10)
        response.raise_for_status()

        data = response.json()
        if SERVICE_NAME in data:
            total_count = data[SERVICE_NAME].get("list_total_count")
            if total_count:
                return total_count
        print("경고: 'list_total_count'를 찾지 못함")
        return None
    except Exception as e:
        print(f"API 총건수 조회 실패: {e}")
        return None


def download_all_ebooks(total_ebook_count):
    """총건수 기준으로 페이지를 나눠 전부 내려받는다."""
    total_pages = math.ceil(total_ebook_count / BOOKS_PER_PAGE)
    print(f"총 {total_ebook_count}건 전자책을 {total_pages}회 호출로 내려받습니다...")

    final_ebook_list = []

    for i in range(total_pages):
        start_index = (i * BOOKS_PER_PAGE) + 1
        end_index = (i + 1) * BOOKS_PER_PAGE
        end_index = min(end_index, total_ebook_count)

        request_url = f"{BASE_URL}/{start_index}/{end_index}/{FILTER_PATH}"
        print(f"({i+1}/{total_pages}) 구간 요청: {start_index}~{end_index}")

        try:
            response = requests.get(request_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            books_in_page = data.get(SERVICE_NAME, {}).get("row", [])

            if not books_in_page:
                print(f"  -> {i+1} 구간 응답 없음. (총 {total_pages} 중)")
                continue

            print(f"  -> 전자책 {len(books_in_page)}건 수집")
            for book in books_in_page:
                final_ebook_list.append(
                    {
                        "title": book.get("TITLE"),
                        "author": book.get("AUTHOR"),
                        "publisher": book.get("PUBLER"),
                        "library": "서울도서관 (API)",
                        "image_url": "",
                        "isbn": "",
                        "provider": "",
                        "platform": "Mixed",
                    }
                )

        except Exception as e:
            print(f"  -> {i+1} 구간 요청 실패: {e}")

    return final_ebook_list


def save_ebooks_to_csv(final_ebook_list):
    """전자책 리스트를 CSV로 저장한다."""
    if not final_ebook_list:
        print("저장할 전자책 데이터가 없습니다.")
        return

    print(f"\n총 {len(final_ebook_list)}건 전자책을 CSV로 저장합니다...")

    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["title", "author", "publisher", "library", "image_url", "isbn", "provider", "platform"],
        )
        writer.writeheader()
        writer.writerows(final_ebook_list)

    print(f"\n완료! '{OUTPUT_FILE}'에 {len(final_ebook_list)}건 저장.")


if __name__ == "__main__":
    print("--- 서울도서관 API 전자책 DB 수집 ---")
    total_ebook_count = get_total_ebook_count()

    if total_ebook_count:
        final_ebook_list = download_all_ebooks(total_ebook_count)
        save_ebooks_to_csv(final_ebook_list)
    else:
        print("총건수 조회 실패로 종료합니다.")
