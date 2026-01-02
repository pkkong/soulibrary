"""Download ODCloud datasets and save as CSV with unified schema."""

import os
import sys
import json
import requests
import pandas as pd

# Allow importing web.config when running from crawler/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from web.config import LIBRARIES, ODCLOUD_API_KEY
except ImportError:
    print("=" * 50)
    print(" [오류] web/config.py 파일을 찾을 수 없습니다. ")
    print("=" * 50)
    sys.exit(1)


def download_odcloud_books(lib_code, config):
    """Download all rows from ODCloud API for the given library."""
    all_books = []
    page = 1
    per_page = 1000

    base_url = config["api_url"]
    lib_name = config["name"]

    print(f"--- [{lib_name}] ODCloud API 다운로드 시작 ---")
    print(f"API URL: {base_url}")

    while True:
        params = {
            "page": page,
            "perPage": per_page,
            "serviceKey": ODCLOUD_API_KEY,
        }
        try:
            print(f"Page {page} 요청 중... ", end="")
            response = requests.get(base_url, params=params, timeout=10)

            if response.status_code != 200:
                print(f"\n[오류] 상태 코드 {response.status_code}")
                break

            data = response.json()
            current_list = data.get("data", [])
            total_count = data.get("totalCount", 0)

            if not current_list:
                print("데이터 없음. (완료)")
                break

            print(f"성공! ({len(current_list)}건)")
            all_books.extend(current_list)

            if len(all_books) >= total_count:
                print(f"--- 총 {total_count}건 수집 완료 ---")
                break

            page += 1
        except Exception as e:
            print(f"\n[오류] Page {page} 요청 실패: {e}")
            break

    return all_books


def save_to_csv(books, config, lib_code):
    """Normalize columns and write to CSV with provider/platform/library_code."""
    if not books:
        print("저장할 데이터가 없습니다.")
        return

    print(f"\n총 {len(books)}건 데이터 필터링 및 저장 중...")

    df = pd.DataFrame(books)

    # 1) 컬럼 매핑
    rename_map = config.get("column_map", {})
    df = df.rename(columns=rename_map)

    # 2) ISBN 매핑 (없으면 빈 칸)
    isbn_map_key = config.get("isbn_map")
    if isbn_map_key and isbn_map_key in df.columns:
        print(f"-> '{isbn_map_key}' 컬럼에서 ISBN 정보 수집...")
        df = df.rename(columns={isbn_map_key: "isbn"})
    else:
        df["isbn"] = ""

    # 3) 오디오/음성 필터링 (설정된 경우)
    filter_col = config.get("format_filter_column")
    if filter_col and filter_col in df.columns:
        ebook_df = df[~df[filter_col].str.contains("오디오", case=False, na=False)].copy()
        print(f"-> 오디오/음성 제외 후: {len(ebook_df)}건 (전자책)")
    else:
        print("[알림] 오디오/음성 필터링이 설정되지 않았거나 컬럼이 없습니다. 전체 저장합니다.")
        ebook_df = df

    # 4) 필수 컬럼 + 메타데이터 채우기
    provider = "교보문고" if config.get("platform") == "Kyobo" else (
        "YES24" if config.get("platform") == "YES24" else ""
    )
    standard_columns = [
        "title",
        "author",
        "publisher",
        "library",
        "image_url",
        "isbn",
        "provider",
        "platform",
        "library_code",
    ]

    for col in standard_columns:
        if col not in ebook_df.columns:
            ebook_df[col] = ""

    ebook_df["library"] = config["library_name"]
    ebook_df["provider"] = provider or config.get("platform", "")
    ebook_df["platform"] = config.get("platform", "")
    ebook_df["library_code"] = lib_code

    # 5) 저장
    final_df = ebook_df[standard_columns]
    output_file = config["db_file"]
    final_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {output_file}")


def get_odcloud_total_count(config):
    """Fetch only totalCount from ODCloud API (for admin remote counts)."""
    base_url = config["api_url"]
    params = {
        "page": 1,
        "perPage": 1,
        "serviceKey": ODCLOUD_API_KEY,
    }

    try:
        response = requests.get(base_url, params=params, timeout=5)
        if response.status_code != 200:
            return -1
        data = response.json()
        total_count = data.get("totalCount", data.get("currentCount", 0))
        return int(total_count)
    except Exception as e:
        print(f"[확인 실패] {config['name']} : {e}")
        return -1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(" [오류] 실행할 도서관 코드를 입력해야 합니다.")
        print(f" 예: python {sys.argv[0]} seongbuk")
        sys.exit(1)

    lib_code = sys.argv[1]

    if lib_code not in LIBRARIES or LIBRARIES[lib_code].get("type") != "odcloud":
        print(f" [오류] '{lib_code}'는 web/config.py에 정의되지 않았거나 'odcloud' 타입이 아닙니다.")
        sys.exit(1)

    config = LIBRARIES[lib_code]

    books = download_odcloud_books(lib_code, config)
    save_to_csv(books, config, lib_code)
