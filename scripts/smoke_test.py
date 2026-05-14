import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
sys.path.insert(0, str(WEB_DIR))

# Keep smoke tests DB-free and fast unless the caller explicitly sets values.
os.environ.setdefault("LIVE_SEARCH_TOTAL_TIMEOUT", "1.0")
os.environ.setdefault("LIVE_SEARCH_LIBRARY_TIMEOUT", "0.8")

from app_search import app  # noqa: E402


def assert_response(client, path, expected_status=200):
    response = client.get(path)
    if response.status_code != expected_status:
        body = response.get_data(as_text=True)[:500]
        raise AssertionError(f"{path} returned {response.status_code}, expected {expected_status}: {body}")
    return response


def main():
    client = app.test_client()

    landing = assert_response(client, "/")
    if "landing-shell" not in landing.get_data(as_text=True):
        raise AssertionError("landing page did not render expected markup")

    search = assert_response(client, "/search")
    if "search-page" not in search.get_data(as_text=True):
        raise AssertionError("search page did not render expected markup")

    empty_search = assert_response(client, "/api/search")
    payload = empty_search.get_json()
    if payload != {"total": 0, "items": []}:
        raise AssertionError(f"unexpected empty search payload: {payload}")

    print("smoke_test: ok")


if __name__ == "__main__":
    main()
