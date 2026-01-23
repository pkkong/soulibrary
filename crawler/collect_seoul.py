# -*- coding: utf-8 -*-
import csv
import math
import requests

API_KEY = "745942496d6b6f6e383774624c4c56"
SERVICE_NAME = "SeoulLibraryBookSearchInfo"
BASE_URL = f"http://openapi.seoul.go.kr:8088/{API_KEY}/json/{SERVICE_NAME}"
BOOKS_PER_PAGE = 1000

OUTPUT_FILE = "../data/seoul_db.csv"

EBOOK_FILTER_CODE = "ze"
FILTER_PATH = f" / / / /{EBOOK_FILTER_CODE}/"


def get_total_ebook_count():
    try:
        test_url = f"{BASE_URL}/1/1/{FILTER_PATH}"
        print(f"API test request... ({test_url})")
        response = requests.get(test_url, timeout=10)
        response.raise_for_status()

        data = response.json()
        if SERVICE_NAME in data:
            total_count = data[SERVICE_NAME].get("list_total_count")
            if total_count:
                return total_count
        print("Error: missing 'list_total_count'.")
        return None
    except Exception as e:
        print(f"API request error: {e}")
        return None


def download_all_ebooks(total_ebook_count):
    total_pages = math.ceil(total_ebook_count / BOOKS_PER_PAGE)
    print(f"Total {total_ebook_count} items, about {total_pages} pages...")

    final_ebook_list = []

    for i in range(total_pages):
        start_index = (i * BOOKS_PER_PAGE) + 1
        end_index = (i + 1) * BOOKS_PER_PAGE
        end_index = min(end_index, total_ebook_count)

        request_url = f"{BASE_URL}/{start_index}/{end_index}/{FILTER_PATH}"
        print(f"({i + 1}/{total_pages}) Range: {start_index}~{end_index}")

        try:
            response = requests.get(request_url, timeout=30)
            response.raise_for_status()
            data = response.json()
            books_in_page = data.get(SERVICE_NAME, {}).get("row", [])

            if not books_in_page:
                print(f"  -> Page {i + 1} empty. (Total {total_pages} pages)")
                continue

            print(f"  -> Received {len(books_in_page)} items")
            for book in books_in_page:
                final_ebook_list.append(
                    {
                        "title": book.get("TITLE") or "",
                        "author": book.get("AUTHOR") or "",
                        "publisher": book.get("PUBLER") or "",
                        "library": "서울도서관",
                        "image_url": "",
                        "isbn": "",
                        "provider": "",
                        "platform": "Mixed",
                    }
                )
        except Exception as e:
            print(f"  -> Page {i + 1} failed: {e}")

    return final_ebook_list


def save_ebooks_to_csv(final_ebook_list):
    if not final_ebook_list:
        print("No data to save.")
        return

    print(f"\nSaving {len(final_ebook_list)} rows to CSV...")

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
                "provider",
                "platform",
            ],
        )
        writer.writeheader()
        writer.writerows(final_ebook_list)

    print(f"Saved: '{OUTPUT_FILE}' ({len(final_ebook_list)} rows)")


if __name__ == "__main__":
    print("--- Seoul Library API crawl ---")
    total_ebook_count = get_total_ebook_count()

    if total_ebook_count:
        final_ebook_list = download_all_ebooks(total_ebook_count)
        save_ebooks_to_csv(final_ebook_list)
    else:
        print("Failed to read total count.")
