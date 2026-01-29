# -*- coding: utf-8 -*-
import csv
import time
from pathlib import Path
import requests

BASE_URL = "https://elib.seoul.go.kr/api"
CONTENT_TYPE_EBOOK = "EB"
BOOKS_PER_PAGE = 100

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OUTPUT_FILE = DATA_DIR / "seoul_db.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://elib.seoul.go.kr/",
}


def _get_content_list(data):
    if isinstance(data.get("ContentDataList"), list):
        return data.get("ContentDataList", [])
    if isinstance(data.get("ContentDataList"), dict):
        return data.get("ContentDataList", {}).get("responses", [])
    return []


def fetch_categories(session):
    url = f"{BASE_URL}/category/main"
    params = {"contentType": CONTENT_TYPE_EBOOK}
    response = session.get(url, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("ContentDataList", [])


def fetch_category_page(session, category_no, page_no):
    url = f"{BASE_URL}/contents/catesearch"
    params = {
        "libCode": "",
        "majorCategory": category_no,
        "subCategory": "",
        "innerKeyword": "",
        "orderOption": "1",
        "loanable": "",
        "currentCount": page_no,
        "pageCount": BOOKS_PER_PAGE,
        "_": int(time.time() * 1000),
    }
    response = session.get(url, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def download_all_ebooks():
    session = requests.Session()
    session.trust_env = False

    categories = fetch_categories(session)
    if not categories:
        print("No categories found.")
        return []

    print(f"Found {len(categories)} categories.")

    final_ebook_list = []
    seen_keys = set()

    for category in categories:
        category_no = category.get("categoryNo")
        category_name = category.get("categoryName")
        if not category_no:
            continue

        page_no = 1
        total_page = 1
        print(f"[{category_no}] {category_name} start...")

        while page_no <= total_page:
            try:
                data = fetch_category_page(session, category_no, page_no)
                total_page = int(data.get("totalPage") or 1)
                items = _get_content_list(data)

                if not items:
                    print(f"  - Page {page_no} empty.")
                    break

                print(f"  - Page {page_no}/{total_page}: {len(items)} items")
                for item in items:
                    content_key = item.get("contentsKey") or ""
                    if not content_key or content_key in seen_keys:
                        continue

                    seen_keys.add(content_key)
                    final_ebook_list.append(
                        {
                            "title": item.get("title") or "",
                            "author": item.get("author") or "",
                            "publisher": item.get("publisher") or "",
                            "library": "서울도서관",
                            "image_url": item.get("coverUrl") or "",
                            "isbn": item.get("isbn") or "",
                            "content_id": content_key,
                            "provider": item.get("ownerCode") or "",
                            "platform": "서울도서관",
                        }
                    )

                page_no += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"  - Page {page_no} failed: {e}")
                break

    return final_ebook_list


def save_ebooks_to_csv(final_ebook_list):
    if not final_ebook_list:
        print("No data to save.")
        return

    print(f"\nSaving {len(final_ebook_list)} rows to CSV...")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "title",
                "author",
                "publisher",
                "library",
                "image_url",
                "isbn",
                "content_id",
                "provider",
                "platform",
            ],
        )
        writer.writeheader()
        writer.writerows(final_ebook_list)

    print(f"Saved: '{OUTPUT_FILE}' ({len(final_ebook_list)} rows)")


if __name__ == "__main__":
    print("--- Seoul Library elib API crawl ---")
    final_ebook_list = download_all_ebooks()
    save_ebooks_to_csv(final_ebook_list)
