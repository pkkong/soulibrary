# -*- coding: utf-8 -*-
import requests
import pandas as pd
import time

OUTPUT_FILE = "../data/sen_subs_db.csv"

URL_SUBS = "https://e-lib.sen.go.kr/api/contents/catesearch"
CONTENT_TYPE_SUBS = "TY02"
LABEL = "Subscription"
LIBRARY_NAME = "서울시교육청 (구독)"
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

    try:
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

            print(f"Page {page} ({per_page} items)... ", end="")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Referer": "https://e-lib.sen.go.kr/",
            }

            response = requests.get(url, params=params, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()

            book_list = []
            if "CategoryDataList" in data:
                book_list = data["CategoryDataList"].get("responses", [])
            elif "contents" in data:
                book_list = data["contents"].get("ContentDataList", [])

            if not book_list:
                print("No data. (stop)")
                break

            print(f"OK! ({len(book_list)})")

            for book_json in book_list:
                if book_json.get("ucm_file_type") == "AUDIO":
                    continue

                all_books.append({
                    "title": book_json.get("ucm_title") or "",
                    "author": book_json.get("ucm_writer") or "",
                    "publisher": book_json.get("ucp_brand") or "",
                    "library": "서울시교육청 (구독)",
                    "image_url": book_json.get("ucm_cover_url") or "",
                    "isbn": _extract_isbn(book_json),
                    "provider": book_json.get("ucm_publisher") or "",
                    "platform": "서울시교육청",
                })

            if len(book_list) < per_page:
                print(f"--- '{label}' done ---")
                break

            page += 1
            time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n[Stop] Ctrl+C, saving {len(all_books)} rows.")

    except Exception as e:
        print(f"\n[Error] Page {page} failed: {e}")
        print(f"Saving {len(all_books)} rows.")

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
        "provider",
        "platform",
    ]]

    final_df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    print(f"Saved: {OUTPUT_FILE}")


if __name__ == "__main__":
    subs_data = download_sen_api(URL_SUBS, CONTENT_TYPE_SUBS, LABEL)
    save_to_csv(subs_data)
