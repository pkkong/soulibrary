# -*- coding: utf-8 -*-
import requests
import pandas as pd
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUTPUT_FILE = DATA_DIR / "sen_owned_db.csv"

URL_OWNED = "https://e-lib.sen.go.kr/api/contents/page-data"
CONTENT_TYPE_OWNED = "TY01"
LABEL = "Owned"
LIBRARY_NAME = "서울시교육청 (소장)"
PLATFORM_NAME = "서울시교육청"


def _extract_isbn(book_json):
    return (
        book_json.get("isbn")
        or book_json.get("isbn13")
        or book_json.get("isbn10")
        or ""
    )


def download_sen_api(url, content_type, label):
    all_books = []
    page = 1
    per_page = 1000

    print(f"--- [서울시교육청] '{label}' ({content_type}) API crawl ---")

    while True:
        params = {
            "contentType": content_type,
            "majorCategory": "",
            "subCategory": "",
            "tinyCategory": "",
            "ownerCategory": "",
            "innerSearchYN": "N",
            "innerKeyword": "",
            "orderOption": "1",
            "typeOption": "1",
            "currentCount": page,
            "pageCount": per_page,
            "loanable": "N",
            "_": int(time.time() * 1000),
        }

        try:
            print(f"Page {page} ({per_page} items)... ", end="")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "https://e-lib.sen.go.kr/",
            }

            response = requests.get(url, params=params, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()

            book_list = []
            if "pageData" in data and "contents" in data["pageData"]:
                book_list = data["pageData"]["contents"].get("ContentDataList", [])

            if not book_list:
                print("No data. (stop)")
                break

            print(f"OK! ({len(book_list)})")

            for book_json in book_list:
                all_books.append({
                    "title": book_json.get("title") or "",
                    "author": book_json.get("author") or "",
                    "publisher": book_json.get("publisher") or "",
                    "library": "서울시교육청 (소장)",
                    "image_url": book_json.get("coverUrl") or "",
                    "isbn": _extract_isbn(book_json),
                    "content_id": book_json.get("contentsKey") or "",
                    "provider": book_json.get("ownerDesc") or "",
                    "platform": "서울시교육청",
                })

            if len(book_list) < per_page:
                print(f"--- '{label}' done ---")
                break

            page += 1
            time.sleep(1)

        except Exception as e:
            print(f"\n[Error] Page {page} failed: {e}")
            break

    return all_books


def save_to_csv(books):
    if not books:
        print("No data to save.")
        return

    print(f"\nSaving CSV... ({len(books)} rows)")
    df = pd.DataFrame(books)

    final_df = df[[
        "title",
        "author",
        "publisher",
        "library",
        "image_url",
        "isbn",
        "content_id",
        "provider",
        "platform",
    ]]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    owned_data = download_sen_api(URL_OWNED, CONTENT_TYPE_OWNED, LABEL)
    save_to_csv(owned_data)
