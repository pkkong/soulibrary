import os
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
sys.path.insert(0, str(WEB_DIR))

# Keep smoke tests DB-free and fast unless the caller explicitly sets values.
os.environ.setdefault("LIVE_SEARCH_TOTAL_TIMEOUT", "1.0")
os.environ.setdefault("LIVE_SEARCH_LIBRARY_TIMEOUT", "0.8")

from app_search import app  # noqa: E402
import report_routes  # noqa: E402
import status_api_routes  # noqa: E402
from live_search.connectors.legacy import DobongKyoboConnector  # noqa: E402


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

    legacy_book = assert_response(client, "/book/1", expected_status=301)
    if not legacy_book.headers.get("Location", "").endswith("/search"):
        raise AssertionError(f"legacy book detail did not redirect to search: {legacy_book.headers.get('Location')}")

    legacy_libraries = assert_response(client, "/api/book_libraries?book_id=1", expected_status=404)
    legacy_payload = legacy_libraries.get_json()
    if legacy_payload.get("error") != "legacy_detail_unavailable":
        raise AssertionError(f"unexpected legacy libraries payload: {legacy_payload}")

    utc_created_at = datetime(2026, 5, 14, 8, 17, tzinfo=timezone.utc)
    decorated_report = report_routes._issue_to_report(
        {
            "number": 1,
            "title": "[오류신고] 오류 - 테스트",
            "body": "## 신고 내용\n테스트",
            "state": "open",
            "created_at": utc_created_at,
        }
    )
    if decorated_report["created_at"].strftime("%Y-%m-%d %H:%M") != "2026-05-14 17:17":
        raise AssertionError(f"report time did not render as KST: {decorated_report['created_at']}")
    parsed_report = report_routes._issue_to_report(
        {
            "number": 2,
            "title": "[오류신고] 대출 상태 - 기존 신고",
            "body": "## 신고 내용\n기존 신고 내용\n\n## 문제가 있던 주소\nhttps://example.com",
            "html_url": "https://github.com/pkkong/library_crawler/issues/2",
            "state": "closed",
            "created_at": "2026-05-14T08:17:00Z",
        }
    )
    if parsed_report["category"] != "대출 상태" or parsed_report["status_label"] != "처리 완료":
        raise AssertionError(f"github issue report did not parse correctly: {parsed_report}")

    dobong_html = """
    <li id="content_450D000228066">
      <p class="pic"><a href="/Kyobo_T3/Content/audio/audio_View.asp?barcode=450D000228066&product_cd=002&category_id=0733">
        <img src="/cover.jpg">
      </a></p>
      <dt><a>최소한의 삼국지</a></dt>
      <dd><em>최태성 / [ 프런트페이지 / 2024 ]</em></dd>
    </li>
    """
    dobong_results = DobongKyoboConnector()._parse_results(
        dobong_html,
        "https://elib.dobong.kr",
        "dobong",
        {"library_name": "도봉", "short_name": "도봉"},
    )
    if not dobong_results or (dobong_results[0].identifiers or {}).get("product_cd") != "002":
        raise AssertionError("dobong live connector did not keep product_cd from result link")

    class FakeStatusResponse:
        def __init__(self, text="", content=None):
            self.text = text
            self.content = content if content is not None else text.encode("utf-8")

        def raise_for_status(self):
            return None

    class FakeStatusSession:
        def __init__(self, response):
            self.response = response
            self.calls = []

        def get(self, url, params=None, timeout=None, headers=None, verify=None):
            self.calls.append({"url": url, "params": params or {}})
            return self.response

    original_status_session = status_api_routes.get_status_session
    status_api_routes.STATUS_CACHE.clear()
    dobong_session = FakeStatusSession(FakeStatusResponse(text="<span>대출 5 / 5 예약 0</span>"))
    status_api_routes.get_status_session = lambda: dobong_session
    try:
        dobong_status = assert_response(
            client,
            "/api/dobong_status?brcd=450D000228066&product_cd=002",
        )
    finally:
        status_api_routes.get_status_session = original_status_session
        status_api_routes.STATUS_CACHE.clear()
    if dobong_status.get_json().get("product_cd") != "002":
        raise AssertionError(f"dobong status did not preserve product_cd: {dobong_status.get_json()}")
    if (dobong_session.calls[0]["params"] or {}).get("product_cd") != "002":
        raise AssertionError(f"dobong status did not request product_cd=002: {dobong_session.calls}")

    gangnam_html = "보유 3 대출 2 예약 0".encode("euc-kr")
    gangnam_session = FakeStatusSession(FakeStatusResponse(content=gangnam_html))
    status_api_routes.get_status_session = lambda: gangnam_session
    try:
        gangnam_status = assert_response(
            client,
            "/api/gangnam_status?library_code=gangnam&content_id=Y167892129",
        )
    finally:
        status_api_routes.get_status_session = original_status_session
        status_api_routes.STATUS_CACHE.clear()
    if gangnam_status.get_json().get("status", {}).get("owned") != 3:
        raise AssertionError(f"gangnam EUC-KR status did not parse: {gangnam_status.get_json()}")

    original_get = report_routes.requests.get
    original_post = report_routes.requests.post

    class FakeIssueListResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "number": 122,
                    "title": "[오류신고] 오류 - 기존 신고 내용입니다.",
                    "body": "## 신고 내용\n기존 신고 내용입니다.\n\n## 문제가 있던 주소\nhttps://example.com/search",
                    "html_url": "https://github.com/pkkong/library_crawler/issues/122",
                    "state": "open",
                    "created_at": "2026-05-14T08:17:00Z",
                },
                {
                    "number": 14,
                    "title": "Not a report",
                    "pull_request": {},
                    "state": "closed",
                    "created_at": "2026-05-14T08:18:00Z",
                },
            ]

    class FakeIssueResponse:
        status_code = 201

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "number": 123,
                "title": "[오류신고] 오류 - 자동 테스트 신고 내용입니다.",
                "body": "## 신고 내용\n자동 테스트 신고 내용입니다.",
                "html_url": "https://github.com/pkkong/library_crawler/issues/123",
                "state": "open",
                "created_at": "2026-05-14T08:17:00Z",
            }

    def fake_issue_get(url, headers=None, params=None, timeout=None):
        if url != "https://api.github.com/repos/pkkong/library_crawler/issues":
            raise AssertionError(f"unexpected issue list url: {url}")
        if not params or params.get("state") != "all":
            raise AssertionError(f"unexpected issue list params: {params}")
        return FakeIssueListResponse()

    def fake_issue_post(url, headers=None, json=None, timeout=None):
        if url != "https://api.github.com/repos/pkkong/library_crawler/issues":
            raise AssertionError(f"unexpected issue url: {url}")
        if not json or "자동 테스트 신고 내용입니다." not in json.get("body", ""):
            raise AssertionError(f"unexpected issue payload: {json}")
        return FakeIssueResponse()

    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/library_crawler"
    report_routes.requests.get = fake_issue_get
    reports = assert_response(client, "/reports")
    reports_body = reports.get_data(as_text=True)
    if "report-form" not in reports_body:
        raise AssertionError("reports page did not render expected markup")
    if "기존 신고 내용입니다" not in reports_body or "이슈 #122" not in reports_body:
        raise AssertionError("reports page did not render GitHub issues as the report store")

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
        report_routes.requests.get = original_get
        report_routes.requests.post = original_post
        os.environ.pop("GITHUB_ISSUE_TOKEN", None)
        os.environ.pop("GITHUB_ISSUE_REPO", None)

    if submission.status_code not in (302, 303):
        body = submission.get_data(as_text=True)[:500]
        raise AssertionError(f"report submission failed with {submission.status_code}: {body}")
    if not submission.headers.get("Location", "").endswith("/reports?saved=1"):
        raise AssertionError(f"unexpected report redirect: {submission.headers.get('Location')}")

    report_routes.requests.get = fake_issue_get
    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/library_crawler"
    try:
        saved = assert_response(client, "/reports?saved=1")
    finally:
        report_routes.requests.get = original_get
        os.environ.pop("GITHUB_ISSUE_TOKEN", None)
        os.environ.pop("GITHUB_ISSUE_REPO", None)
    if "신고가 접수되었습니다" not in saved.get_data(as_text=True):
        raise AssertionError("report saved confirmation did not render")

    print("smoke_test: ok")


if __name__ == "__main__":
    main()
