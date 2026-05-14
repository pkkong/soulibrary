import os
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
sys.path.insert(0, str(WEB_DIR))

# Keep smoke tests DB-free and fast unless the caller explicitly sets values.
os.environ.setdefault("LIVE_SEARCH_TOTAL_TIMEOUT", "1.0")
os.environ.setdefault("LIVE_SEARCH_LIBRARY_TIMEOUT", "0.8")
os.environ.setdefault("ERROR_REPORTS_STORAGE", "file")
os.environ.setdefault(
    "ERROR_REPORTS_FILE",
    str(Path(tempfile.gettempdir()) / "soulib_smoke_error_reports.jsonl"),
)
try:
    Path(os.environ["ERROR_REPORTS_FILE"]).unlink()
except FileNotFoundError:
    pass

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

    reports = assert_response(client, "/reports")
    if "report-form" not in reports.get_data(as_text=True):
        raise AssertionError("reports page did not render expected markup")

    submission = client.post(
        "/reports",
        data={
            "category": "오류",
            "message": "자동 테스트 신고 내용입니다.",
            "page_url": "https://example.com/search",
            "contact": "",
        },
        follow_redirects=False,
    )
    if submission.status_code not in (302, 303):
        body = submission.get_data(as_text=True)[:500]
        raise AssertionError(f"report submission failed with {submission.status_code}: {body}")
    if not submission.headers.get("Location", "").endswith("/reports?saved=1"):
        raise AssertionError(f"unexpected report redirect: {submission.headers.get('Location')}")

    saved = assert_response(client, "/reports?saved=1")
    if "신고가 접수되었습니다" not in saved.get_data(as_text=True):
        raise AssertionError("report saved confirmation did not render")

    print("smoke_test: ok")


if __name__ == "__main__":
    main()
