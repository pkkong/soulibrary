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
import live_search_routes  # noqa: E402
from live_search.connectors.legacy import DobongKyoboConnector  # noqa: E402
from live_search.connectors.bookers import BookersConnector  # noqa: E402
from live_search.models import LiveSearchResult  # noqa: E402
from live_search.normalizer import merge_live_results  # noqa: E402


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

    my_shelf = assert_response(client, "/my-shelf")
    if "shelf-shell" not in my_shelf.get_data(as_text=True):
        raise AssertionError("my shelf page did not render expected markup")

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
            "closed_at": "2026-05-14T09:00:00Z",
        }
    )
    if (
        parsed_report["category"] != "대출 상태"
        or parsed_report["status_label"] != "처리 완료"
        or parsed_report["resolution_message"] != "신고해주신 '기존 신고 내용' 문제를 확인했고, 필요한 조치를 완료했습니다. 알려주셔서 감사합니다."
        or parsed_report["resolution_at"].strftime("%Y-%m-%d %H:%M") != "2026-05-14 18:00"
    ):
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
        def __init__(self, text="", content=None, json_data=None):
            self.text = text
            self.content = content if content is not None else text.encode("utf-8")
            self._json_data = json_data

        def raise_for_status(self):
            return None

        def json(self):
            if self._json_data is None:
                raise ValueError("no json")
            return self._json_data

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

    merged_project_hail_mary = merge_live_results(
        [
            LiveSearchResult(
                title="프로젝트 헤일메리",
                author="앤디 위어",
                publisher="알에이치코리아(RHK)",
                library_code="eunpyeong",
                library_name="은평구립전자도서관",
                platform="Eunpyeong",
                identifiers={"content_id": "101619655"},
            ),
            LiveSearchResult(
                title="프로젝트 헤일메리",
                author="Andy Weir",
                publisher="RHK",
                library_code="gangnam",
                library_name="강남구 전자도서관",
                platform="Gangnam",
                identifiers={"content_id": "B9788925521725"},
            ),
        ]
    )
    if len(merged_project_hail_mary) != 1 or merged_project_hail_mary[0]["counts"]["total"] != 2:
        raise AssertionError(f"project hail mary author alias did not merge: {merged_project_hail_mary}")

    subscription_merge = merge_live_results(
        [
            LiveSearchResult(
                title="구독형 테스트",
                author="테스터",
                publisher="테스트출판",
                library_code="gangdong_subs",
                library_name="강동구립도서관 (구독)",
                platform="Kyobo_New",
                service_type="Subscription",
                identifiers={"brcd": "SUBS001", "ctts_dvsn_code": "001", "ctgr_id": "001"},
            )
        ]
    )
    if subscription_merge[0]["libraries"][0].get("service_type") != "Subscription":
        raise AssertionError(f"subscription service_type was not preserved: {subscription_merge}")

    bookers_result = BookersConnector()._result(
        "gangbuk_subs",
        {
            "library_name": "강북구립도서관 (구독)",
            "short_name": "강북",
            "service_type": "Subscription",
            "bookers_org_name": "강북구립도서관",
            "bookers_org_code": "UIS0000000737",
            "bookers_uis_code": "UIS0000000737",
        },
        {
            "ucm_code": "UCM0000157794",
            "ucm_title": "프로젝트 헤일메리",
            "ucm_writer": "앤디 위어",
            "ucp_brand": "알에이치코리아(RHK)",
            "ucm_ebook_isbn": "9788925521725",
            "ucm_cover_url": "https://files.bookers.life/cover.jpg",
        },
    )
    if (
        bookers_result.platform != "Bookers"
        or bookers_result.service_type != "Subscription"
        or "bookDetail.do" not in bookers_result.detail_url
        or "ucm_code=UCM0000157794" not in bookers_result.detail_url
        or "paramUisCode=UIS0000000737" not in bookers_result.detail_url
    ):
        raise AssertionError(f"bookers connector did not map subscription result: {bookers_result}")

    original_live_search = live_search_routes.live_search
    original_cached_detail = live_search_routes.get_cached_live_detail
    partial_book = {
        "title": "프로젝트 헤일메리",
        "author": "앤디 위어",
        "publisher": "알에이치코리아",
        "counts": {"kyobo": 1, "yes24": 0, "other": 0, "total": 1},
        "counts_partial": True,
        "libraries": [
            {"code": "eunpyeong", "name": "은평구립전자도서관", "short": "은평", "platform_code": "Eunpyeong"},
        ],
    }
    complete_cached_book = {
        "title": "완성 캐시 테스트",
        "author": "테스터",
        "publisher": "테스트출판",
        "counts": {"kyobo": 1, "yes24": 0, "other": 1, "total": 2},
        "libraries": [
            {"code": "eunpyeong", "name": "은평구립전자도서관", "short": "은평", "platform_code": "Eunpyeong"},
            {"code": "gangnam", "name": "강남구 전자도서관", "short": "강남", "platform_code": "Gangnam"},
        ],
    }
    complete_book = {
        "title": "프로젝트 헤일메리",
        "author": "앤디 위어",
        "publisher": "알에이치코리아",
        "counts": {"kyobo": 1, "yes24": 0, "other": 1, "total": 2},
        "libraries": [
            {"code": "eunpyeong", "name": "은평구립전자도서관", "short": "은평", "platform_code": "Eunpyeong"},
            {"code": "gangnam", "name": "강남구 전자도서관", "short": "강남", "platform_code": "Gangnam"},
        ],
    }
    subscription_book = {
        "title": "구독형 테스트",
        "author": "테스터",
        "publisher": "테스트출판",
        "counts": {"kyobo": 1, "yes24": 0, "other": 0, "total": 1},
        "libraries": [
            {
                "code": "gangdong_subs",
                "name": "강동구립도서관 (구독)",
                "short": "강동",
                "platform_code": "Kyobo_New",
                "service_type": "Subscription",
                "brcd": "SUBS001",
                "ctts_dvsn_code": "001",
                "ctgr_id": "001",
            },
        ],
    }

    def fake_cached_detail(key):
        if not key:
            return None
        if key == "complete-project":
            return complete_cached_book
        if key != "partial-project":
            raise AssertionError(f"unexpected detail key: {key}")
        return partial_book

    def fake_live_search(query, field, providers_raw="", libraries_raw="", limit=20, offset=0, refine=""):
        if query == "프로젝트" and field == "title_author":
            return {"total": 1, "items": [partial_book], "filters": {"providers": [], "libraries": []}, "meta": {}}
        if query == "프로젝트 헤일메리" and field == "title":
            return {"total": 1, "items": [complete_book], "filters": {"providers": [], "libraries": []}, "meta": {}}
        if query == "구독형 테스트" and field == "title":
            return {"total": 1, "items": [subscription_book], "filters": {"providers": [], "libraries": []}, "meta": {}}
        raise AssertionError(f"unexpected live search: {query} {field}")

    live_search_routes.get_cached_live_detail = fake_cached_detail
    live_search_routes.live_search = fake_live_search
    try:
        partial_search = assert_response(
            client,
            "/api/live_search?query=%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8&field=title_author&limit=20&offset=0",
        ).get_json()
        partial_item = partial_search["items"][0]
        if not partial_item.get("counts_partial") or partial_item.get("summary_url"):
            raise AssertionError(f"broad search card should defer detail hydration: {partial_item}")

        hydrated_detail = assert_response(
            client,
            "/live_book?key=partial-project&title=%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8+%ED%97%A4%EC%9D%BC%EB%A9%94%EB%A6%AC&author=%EC%95%A4%EB%94%94+%EC%9C%84%EC%96%B4&publisher=%EC%95%8C%EC%97%90%EC%9D%B4%EC%B9%98%EC%BD%94%EB%A6%AC%EC%95%84"
        )
        hydrated_payload = assert_response(
            client,
            "/api/live_book_detail?key=partial-project&title=%ED%94%84%EB%A1%9C%EC%A0%9D%ED%8A%B8+%ED%97%A4%EC%9D%BC%EB%A9%94%EB%A6%AC&author=%EC%95%A4%EB%94%94+%EC%9C%84%EC%96%B4&publisher=%EC%95%8C%EC%97%90%EC%9D%B4%EC%B9%98%EC%BD%94%EB%A6%AC%EC%95%84",
        ).get_json()
        complete_cached_detail = assert_response(
            client,
            "/live_book?key=complete-project&title=%EC%99%84%EC%84%B1+%EC%BA%90%EC%8B%9C+%ED%85%8C%EC%8A%A4%ED%8A%B8",
        )
        subscription_detail = assert_response(
            client,
            "/live_book?title=%EA%B5%AC%EB%8F%85%ED%98%95+%ED%85%8C%EC%8A%A4%ED%8A%B8&author=%ED%85%8C%EC%8A%A4%ED%84%B0&publisher=%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%B6%9C%ED%8C%90",
        )
        subscription_payload = assert_response(
            client,
            "/api/live_book_detail?title=%EA%B5%AC%EB%8F%85%ED%98%95+%ED%85%8C%EC%8A%A4%ED%8A%B8&author=%ED%85%8C%EC%8A%A4%ED%84%B0&publisher=%ED%85%8C%EC%8A%A4%ED%8A%B8%EC%B6%9C%ED%8C%90",
        ).get_json()
    finally:
        live_search_routes.live_search = original_live_search
        live_search_routes.get_cached_live_detail = original_cached_detail
    hydrated_body = hydrated_detail.get_data(as_text=True)
    if "은평" not in hydrated_body or "강남" in hydrated_body or "/api/live_book_detail" not in hydrated_body:
        raise AssertionError("live detail should render cached partial result before background hydration")
    if "강남" not in (hydrated_payload.get("groups_html") or "") or "은평" not in (hydrated_payload.get("groups_html") or ""):
        raise AssertionError(f"background live detail hydration did not return complete libraries: {hydrated_payload}")
    complete_cached_body = complete_cached_detail.get_data(as_text=True)
    if "완성 캐시 테스트" not in complete_cached_body or "강남" not in complete_cached_body:
        raise AssertionError("live detail did not render complete cached detail directly")

    subscription_body = subscription_detail.get_data(as_text=True)
    if "/api/live_book_detail" not in subscription_body or 'data-service-type="Subscription"' in subscription_body:
        raise AssertionError("uncached live detail should defer subscription library hydration")
    if 'data-service-type="Subscription"' not in (subscription_payload.get("groups_html") or ""):
        raise AssertionError("background live detail did not render subscription service_type")

    eunpyeong_session = FakeStatusSession(FakeStatusResponse(json_data={
        "data": {
            "contentKey": "101619655",
            "copys": 2,
            "loanCnt": 2,
            "reserveCnt": 97,
        }
    }))
    status_api_routes.get_status_session = lambda: eunpyeong_session
    try:
        eunpyeong_status = assert_response(
            client,
            "/api/eunpyeong_status?content_id=101619655",
        )
    finally:
        status_api_routes.get_status_session = original_status_session
        status_api_routes.STATUS_CACHE.clear()
    eunpyeong_payload = eunpyeong_status.get_json()
    if eunpyeong_payload.get("status", {}).get("total") != 2 or eunpyeong_payload.get("status", {}).get("reserved") != 97:
        raise AssertionError(f"eunpyeong current API status did not parse: {eunpyeong_payload}")
    eunpyeong_call = eunpyeong_session.calls[0]
    if "api/service/content/detail" not in eunpyeong_call["url"] or eunpyeong_call["params"].get("id") != "101619655":
        raise AssertionError(f"eunpyeong status did not request current detail API: {eunpyeong_session.calls}")

    original_get = report_routes.requests.get
    original_post = report_routes.requests.post
    github_env_names = ("GITHUB_ISSUE_TOKEN", "GITHUB_TOKEN", "GITHUB_ISSUE_REPO")
    original_github_env = {name: os.environ.get(name) for name in github_env_names}

    def restore_github_env():
        for name, value in original_github_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    class FakeIssueListResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "number": 124,
                    "title": "[오류신고] 대출 상태 - 해결된 신고입니다.",
                    "body": "## 신고 내용\n해결된 신고입니다.",
                    "html_url": "https://github.com/pkkong/library_crawler/issues/124",
                    "comments_url": "https://api.github.com/repos/pkkong/library_crawler/issues/124/comments",
                    "comments": 1,
                    "state": "closed",
                    "created_at": "2026-05-14T08:18:00Z",
                    "closed_at": "2026-05-14T09:00:00Z",
                    "updated_at": "2026-05-14T09:00:00Z",
                },
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

    class FakeIssueCommentsResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "body": "수정 후 배포 완료했습니다.",
                    "created_at": "2026-05-14T09:00:00Z",
                }
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
        if url == "https://api.github.com/repos/pkkong/library_crawler/issues/124/comments":
            return FakeIssueCommentsResponse()
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

    for env_name in github_env_names:
        os.environ.pop(env_name, None)
    missing_store = assert_response(client, "/reports")
    missing_store_body = missing_store.get_data(as_text=True)
    if "GitHub Issues 저장소 연결에 실패했습니다" not in missing_store_body:
        raise AssertionError("reports page hid GitHub store connection failure")
    if "운영 서버에 GITHUB_ISSUE_TOKEN 환경변수가 없습니다" not in missing_store_body:
        raise AssertionError("reports page did not show the missing token cause")
    if "확인 필요" not in missing_store_body:
        raise AssertionError("reports page did not mark report store status as unavailable")

    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/library_crawler"
    report_routes.requests.get = fake_issue_get
    reports = assert_response(client, "/reports")
    reports_body = reports.get_data(as_text=True)
    if "report-form" not in reports_body:
        raise AssertionError("reports page did not render expected markup")
    if "기존 신고 내용입니다" not in reports_body or "이슈 #122" not in reports_body:
        raise AssertionError("reports page did not render GitHub issues as the report store")
    if "처리 안내" not in reports_body:
        raise AssertionError("reports page did not render customer-facing resolution heading")
    if "신고해주신 &#39;해결된 신고입니다.&#39; 문제를 확인했고" not in reports_body:
        raise AssertionError("reports page did not render customer-facing resolution message")
    if "수정 후 배포 완료했습니다" in reports_body:
        raise AssertionError("reports page leaked developer-facing issue comments")

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

    if submission.status_code != 201:
        body = submission.get_data(as_text=True)[:500]
        raise AssertionError(f"report submission failed with {submission.status_code}: {body}")
    submission_body = submission.get_data(as_text=True)
    if "신고가 접수되었습니다" not in submission_body:
        raise AssertionError("report saved confirmation did not render after submission")
    if "방금 접수" not in submission_body or "자동 테스트 신고 내용입니다." not in submission_body:
        raise AssertionError("newly submitted report was not shown immediately")
    if "이슈 #123" not in submission_body:
        raise AssertionError("newly submitted GitHub issue link was not shown immediately")

    report_routes.requests.get = fake_issue_get
    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/library_crawler"
    try:
        saved = assert_response(client, "/reports?saved=1")
    finally:
        report_routes.requests.get = original_get
        restore_github_env()
    if "신고가 접수되었습니다" not in saved.get_data(as_text=True):
        raise AssertionError("report saved confirmation did not render")

    print("smoke_test: ok")


if __name__ == "__main__":
    main()
