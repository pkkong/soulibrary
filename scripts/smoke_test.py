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
BAD_REPORTS_PATH = Path(tempfile.gettempdir()) / "soulib_smoke_bad_reports_path"
BAD_REPORTS_PATH.mkdir(exist_ok=True)
os.environ.setdefault("ERROR_REPORTS_FILE", str(BAD_REPORTS_PATH))
for path in (
    Path(tempfile.gettempdir()) / "soulib_smoke_error_reports.jsonl",
    Path(tempfile.gettempdir()) / "soulib" / "error_reports.jsonl",
):
    try:
        path.unlink()
    except FileNotFoundError:
        pass

from app_search import app  # noqa: E402
import report_routes  # noqa: E402


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

    sitemap = assert_response(client, "/sitemap.xml")
    sitemap_body = sitemap.get_data(as_text=True)
    if "/sitemap-static.xml" not in sitemap_body:
        raise AssertionError("sitemap index did not include static sitemap")

    legacy_book = assert_response(client, "/book/1", expected_status=404)
    if "이전 상세 페이지는 현재 지원하지 않습니다" not in legacy_book.get_data(as_text=True):
        raise AssertionError("legacy book detail did not render the DB-free fallback")

    legacy_libraries = assert_response(client, "/api/book_libraries?book_id=1", expected_status=404)
    legacy_payload = legacy_libraries.get_json()
    if legacy_payload.get("error") != "legacy_detail_unavailable":
        raise AssertionError(f"unexpected legacy libraries payload: {legacy_payload}")

    reports = assert_response(client, "/reports")
    if "report-form" not in reports.get_data(as_text=True):
        raise AssertionError("reports page did not render expected markup")

    original_post = report_routes.requests.post

    class FakeIssueResponse:
        status_code = 201

        def raise_for_status(self):
            return None

        def json(self):
            return {"number": 123, "html_url": "https://github.com/pkkong/library_crawler/issues/123"}

    def fake_issue_post(url, headers=None, json=None, timeout=None):
        if url != "https://api.github.com/repos/pkkong/library_crawler/issues":
            raise AssertionError(f"unexpected issue url: {url}")
        if not json or "자동 테스트 신고 내용입니다." not in json.get("body", ""):
            raise AssertionError(f"unexpected issue payload: {json}")
        return FakeIssueResponse()

    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/library_crawler"
    report_routes.requests.post = fake_issue_post
    try:
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
    finally:
        report_routes.requests.post = original_post
        os.environ.pop("GITHUB_ISSUE_TOKEN", None)
        os.environ.pop("GITHUB_ISSUE_REPO", None)

    if submission.status_code not in (302, 303):
        body = submission.get_data(as_text=True)[:500]
        raise AssertionError(f"report submission failed with {submission.status_code}: {body}")
    if not submission.headers.get("Location", "").endswith("/reports?saved=1"):
        raise AssertionError(f"unexpected report redirect: {submission.headers.get('Location')}")

    saved = assert_response(client, "/reports?saved=1")
    if "신고가 접수되었습니다" not in saved.get_data(as_text=True):
        raise AssertionError("report saved confirmation did not render")
    if "자동 테스트 신고 내용입니다" not in saved.get_data(as_text=True):
        raise AssertionError("saved report did not render in recent reports")
    if "이슈 #123" not in saved.get_data(as_text=True):
        raise AssertionError("created GitHub issue did not render in recent reports")

    print("smoke_test: ok")


if __name__ == "__main__":
    main()
