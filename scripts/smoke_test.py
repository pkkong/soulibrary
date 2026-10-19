import copy
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
sys.path.insert(0, str(WEB_DIR))

# Keep smoke tests DB-free and fast unless the caller explicitly sets values.
os.environ.setdefault("LIVE_SEARCH_TOTAL_TIMEOUT", "1.0")
os.environ.setdefault("LIVE_SEARCH_LIBRARY_TIMEOUT", "0.8")
os.environ.setdefault("SHARED_SHELVES_STORAGE", "json")
os.environ.setdefault("SHARED_SHELVES_FILE", str(ROOT_DIR / "data" / "_tmp_smoke_shared_shelves.json"))

import app_search  # noqa: E402
import db as db_module  # noqa: E402
from app_search import app  # noqa: E402
import blog_comments  # noqa: E402
import report_routes  # noqa: E402
import seo_books  # noqa: E402
import seo_opportunity_planner as seo_planner  # noqa: E402
import status_api_routes  # noqa: E402
import live_search_routes  # noqa: E402
import live_search.service as live_service  # noqa: E402
import live_search.cache as live_cache  # noqa: E402
from live_search.cache import TTLMemoryCache  # noqa: E402
from live_search.connectors.legacy import DobongKyoboConnector  # noqa: E402
from live_search.connectors.bookers import BookersConnector  # noqa: E402
from live_search.models import LiveSearchResult  # noqa: E402
from live_search.normalizer import merge_live_results, normalize_author, normalize_title_for_group  # noqa: E402
from live_search.service import _result_matches_query  # noqa: E402
from blog_posts import get_blog_posts  # noqa: E402


def assert_response(client, path, expected_status=200):
    response = client.get(path)
    if response.status_code != expected_status:
        body = response.get_data(as_text=True)[:500]
        raise AssertionError(f"{path} returned {response.status_code}, expected {expected_status}: {body}")
    return response


class ImgSrcParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.srcs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "img":
            attr_map = dict(attrs)
            self.srcs.append(attr_map.get("src", ""))


class BlogPrimaryListParser(HTMLParser):
    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__()
        self.cards = []
        self._in_primary = False
        self._primary_depth = 0
        self._in_card = False
        self._card_depth = 0
        self._current = None

    @staticmethod
    def _classes(attrs):
        attr_map = dict(attrs)
        return set((attr_map.get("class") or "").split()), attr_map

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        classes, attr_map = self._classes(attrs)
        starts_primary = tag == "section" and "blog-primary-list" in classes
        if starts_primary:
            self._in_primary = True
            self._primary_depth = 1
        elif self._in_primary and tag not in self.VOID_TAGS:
            self._primary_depth += 1

        if not self._in_primary:
            return

        starts_card = tag == "a" and "blog-card" in classes
        if starts_card:
            self._in_card = True
            self._card_depth = 1
            self._current = {
                "href": attr_map.get("href", ""),
                "date": "",
                "text_parts": [],
            }
        elif self._in_card and tag not in self.VOID_TAGS:
            self._card_depth += 1

        if self._in_card and tag == "time" and self._current is not None:
            self._current["date"] = attr_map.get("datetime", "")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._in_card and tag not in self.VOID_TAGS:
            self._card_depth -= 1
            if self._card_depth == 0:
                text = " ".join(" ".join(self._current.get("text_parts", [])).split())
                self.cards.append(
                    {
                        "href": self._current.get("href", ""),
                        "date": self._current.get("date", ""),
                        "text": text,
                    }
                )
                self._in_card = False
                self._current = None

        if self._in_primary and tag not in self.VOID_TAGS:
            self._primary_depth -= 1
            if self._primary_depth <= 0:
                self._in_primary = False

    def handle_data(self, data):
        if self._current is not None:
            text = data.strip()
            if text:
                self._current["text_parts"].append(text)


def image_sources(html):
    parser = ImgSrcParser()
    parser.feed(html)
    return parser.srcs


def blog_primary_cards(html):
    parser = BlogPrimaryListParser()
    parser.feed(html)
    return parser.cards


def assert_blog_images_load(client):
    posts = get_blog_posts()
    paths = ["/blog", "/blog?category=guide", "/blog?category=recommendations"]
    paths.extend(f"/blog/{post['slug']}" for post in posts)
    failures = []
    seen = set()
    for path in paths:
        body = assert_response(client, path).get_data(as_text=True)
        for src in image_sources(body):
            key = (path, src)
            if key in seen:
                continue
            seen.add(key)
            if not src.startswith("/static/"):
                failures.append(f"{path}: rendered blog image must use /static/, got `{src}`")
                continue
            response = client.get(src)
            content_type = response.headers.get("Content-Type", "")
            if response.status_code != 200 or not response.data:
                failures.append(f"{path}: image `{src}` returned {response.status_code} ({len(response.data)} bytes)")
            elif not (content_type.startswith("image/") or src.endswith(".svg")):
                failures.append(f"{path}: image `{src}` returned unexpected content type `{content_type}`")
    if failures:
        raise AssertionError("Broken blog images:\n" + "\n".join(failures))


def assert_live_search_failure_contract():
    """Keep timeout/cache/singleflight regressions DB-free and off the network."""
    def result(code="mapo", platform="Kyobo_New"):
        return LiveSearchResult(title="회귀검증책", author="작가", publisher="출판사",
                                library_code=code, library_name=code, library_short=code,
                                platform=platform)

    success = [{"errors": [], "error_count": 0, "searched_libraries": 1, "successful_libraries": 1}]
    failure = [{"errors": [{"library_code": "mapo", "error": "search_timeout"}],
                "error_count": 1, "failed_libraries": ["mapo"],
                "searched_libraries": 1, "successful_libraries": 0}]
    with patch.object(live_service, "_CACHE", TTLMemoryCache(600)), \
            patch.object(live_service, "_DETAIL_CACHE", TTLMemoryCache(600)):
        with patch.object(live_service, "_search_libraries", return_value=([], failure)) as upstream:
            for _ in range(2):
                payload = live_service.live_search("실패한검색", "title")
                assert payload["meta"]["partial"] and not payload["meta"]["cache_hit"]
            assert upstream.call_count == 2, "failed empty results must not poison the cache"

        with patch.object(live_service, "_search_libraries", return_value=([result()], failure)):
            payload = live_service.live_search("회귀검증책", "title")
            cached = live_service.live_search("회귀검증책", "title")
            assert payload["items"][0]["counts_partial"] and cached["meta"]["partial"]
            assert cached["meta"]["cache_hit"]
            expiry, _ = next(iter(live_service._CACHE._items.values()))
            assert 0 < expiry - time.time() <= live_service.LIVE_SEARCH_PARTIAL_TTL_SEC

        with patch.object(live_service, "_search_libraries", return_value=([result()], success)):
            limited = live_service.live_search("회귀검증책", "title", libraries_raw="mapo")
            assert limited["meta"]["scope_limited"] and not limited["meta"]["partial"]
            assert live_search_routes._attach_summary_urls(limited, "회귀검증책")["items"][0]["counts_partial"]

        barrier = threading.Barrier(6)
        def fetch(*args, **kwargs):
            time.sleep(0.08)
            return [result()], success

        def search(index):
            barrier.wait(timeout=5)
            return live_service.live_search("동시요청", "title", limit=1, offset=index % 2)

        with patch.object(live_service, "_search_libraries", side_effect=fetch) as upstream:
            with ThreadPoolExecutor(max_workers=6) as executor:
                responses = list(executor.map(search, range(6)))
            assert upstream.call_count == 1, "concurrent identical searches must share one fanout"
        assert all(len(value["items"]) == 1 for value in responses[::2])
        assert all(not value["items"] for value in responses[1::2])
        responses[0]["items"][0]["title"] = "mutated"
        assert responses[2]["items"][0]["title"] == "회귀검증책"
        assert not live_service._INFLIGHT

        barrier = threading.Barrier(6)
        def fail(*args, **kwargs):
            time.sleep(0.08)
            raise RuntimeError("smoke leader failure")

        def failed_search(index):
            barrier.wait(timeout=5)
            try:
                live_service.live_search("실패동시요청", "title")
            except RuntimeError as error:
                return str(error)

        with patch.object(live_service, "_search_libraries", side_effect=fail) as upstream:
            with ThreadPoolExecutor(max_workers=6) as executor:
                failures = list(executor.map(failed_search, range(6)))
            assert upstream.call_count == 1 and failures == ["smoke leader failure"] * 6
        assert not live_service._INFLIGHT, "failed leader must release waiting requests"
        with patch.object(live_service, "_search_libraries", return_value=([], success)):
            assert live_service.live_search("실패동시요청", "title")["total"] == 0

    calls = []
    class Connector:
        def search_library(self, code, cfg, query, field, limit, timeout):
            calls.append(code)
            return []

    with patch.object(live_service, "_connector_for_library", return_value=Connector()):
        live_service._search_libraries("회귀검증책", "title", list(live_service.LIBRARIES), ["YES24"])
    assert len(calls) < len(live_service.LIBRARIES), "fixed incompatible providers should be pruned"
    assert set(live_service.SPECIAL_CONNECTOR_FACTORIES) <= set(calls)
    assert all(code in calls for code, cfg in live_service.LIBRARIES.items()
               if cfg.get("platform") in {"Mixed", "Unknown"})

    release = threading.Event()
    class SlowConnector:
        def search_library(self, *args):
            release.wait(1)
            return []

    try:
        with patch.object(live_service, "LIVE_SEARCH_TOTAL_TIMEOUT", 0.01), \
                patch.object(live_service, "_connector_for_library", return_value=SlowConnector()):
            _, diagnostics = live_service._search_libraries("회귀검증책", "title", ["mapo", "yongsan"], [])
            assert diagnostics[0]["error_count"] == 2 and diagnostics[0]["successful_libraries"] == 0
    finally:
        release.set()

    book = {"title": "회귀검증책", "author": "작가", "counts": {"total": 1}, "libraries": [{"code": "mapo"}]}
    with patch.object(live_search_routes, "live_search", return_value={"items": [book], "meta": {"partial": True}}), \
            patch.object(live_search_routes, "get_cached_live_detail", return_value=None):
        assert live_search_routes._find_complete_live_book(book)["_live_detail_complete"] is False
        payload = app.test_client().get("/api/live_book_detail?title=회귀검증책&author=작가").get_json()
        assert payload["counts_partial"] and payload["book"]["counts_partial"]

    cache = TTLMemoryCache(600, max_items=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("a", 3)
    assert cache.get("b") == 2 and cache.get("a") == 3


def assert_search_deadline_contract():
    """A short detail budget must neither cancel nor consume ordinary flights."""
    def result():
        return LiveSearchResult(title="시간예산검증책", author="작가", library_code="mapo",
                                library_name="마포", library_short="마포", platform="Kyobo_New")

    success = [{"errors": [], "error_count": 0, "searched_libraries": 1, "successful_libraries": 1}]
    failure = [{"errors": [{"error": "search_timeout"}], "error_count": 1,
                "searched_libraries": 1, "successful_libraries": 0}]
    with patch.object(live_service, "_CACHE", TTLMemoryCache(600)), \
            patch.object(live_service, "_DETAIL_CACHE", TTLMemoryCache(600)):
        with patch.object(live_service, "_search_libraries", return_value=([result()], success)) as upstream:
            complete = live_service.live_search("시간예산검증책", "title", deadline=time.monotonic() + 1)
            assert not complete["meta"]["partial"]
            assert live_service.live_search("시간예산검증책", "title")["meta"]["cache_hit"]
            assert upstream.call_count == 1, "complete budgeted results may populate the normal cache"
        live_service._CACHE.clear()
        with patch.object(live_service, "_search_libraries") as upstream:
            try:
                live_service.live_search("만료된예산", "title", deadline=time.monotonic() - 1)
            except live_service.LiveSearchDeadlineExceeded:
                pass
            else:
                raise AssertionError("expired budget must stop before starting a fanout")
            assert upstream.call_count == 0 and not live_service._INFLIGHT
        with patch.object(live_service, "_search_libraries", return_value=([result()], failure)) as upstream:
            partial = live_service.live_search("시간예산검증책", "title", deadline=time.monotonic() + 1)
            assert partial["meta"]["partial"] and partial["items"][0]["counts_partial"]
            assert live_service._CACHE.get(live_service._cache_key("시간예산검증책", "title", [], [])) is None
            assert not live_service.live_search("시간예산검증책", "title")["meta"]["cache_hit"]
            assert upstream.call_count == 2, "budget partial must not contaminate later normal searches"
        live_service._CACHE.clear()

        entered, release = threading.Event(), threading.Event()
        def normal_fanout(*args, **kwargs):
            entered.set()
            assert release.wait(2), "test did not release the ordinary search"
            return [result()], success

        with patch.object(live_service, "_search_libraries", side_effect=normal_fanout) as upstream:
            with ThreadPoolExecutor(max_workers=1) as executor:
                leader = executor.submit(live_service.live_search, "일반진행", "title")
                try:
                    assert entered.wait(2)
                    key = live_service._cache_key("일반진행", "title", [], [])
                    ordinary_future = live_service._INFLIGHT[key]
                    try:
                        live_service.live_search("일반진행", "title", deadline=time.monotonic() + 0.02)
                    except live_service.LiveSearchDeadlineExceeded:
                        pass
                    else:
                        raise AssertionError("short follower must stop at its own deadline")
                    assert not leader.done() and not ordinary_future.cancelled()
                    assert live_service._INFLIGHT.get(key) is ordinary_future
                    assert upstream.call_count == 1
                finally:
                    release.set()
                assert not leader.result(timeout=2)["meta"]["partial"]
        assert not live_service._INFLIGHT
        live_service._CACHE.clear()

        entered, release = threading.Event(), threading.Event()
        def independent_fanout(*args, deadline=None, **kwargs):
            if deadline is not None:
                entered.set()
                assert release.wait(2)
                return [result()], failure
            return [result()], success

        with patch.object(live_service, "_search_libraries", side_effect=independent_fanout) as upstream:
            with ThreadPoolExecutor(max_workers=2) as executor:
                budgeted = executor.submit(live_service.live_search, "독립진행", "title", deadline=time.monotonic() + 1)
                try:
                    assert entered.wait(2)
                    ordinary = executor.submit(live_service.live_search, "독립진행", "title")
                    assert not ordinary.result(timeout=1)["meta"]["partial"]
                    assert not budgeted.done() and upstream.call_count == 2
                finally:
                    release.set()
                assert budgeted.result(timeout=2)["meta"]["partial"]
        assert not live_service._INFLIGHT
        assert not live_service.live_search("독립진행", "title")["meta"]["partial"]

    fast_done, release, slow_done = threading.Event(), threading.Event(), threading.Event()
    class Connector:
        def search_library(self, code, cfg, query, field, limit, timeout):
            if code == "mapo":
                fast_done.set()
                return [result()]
            try:
                release.wait(2)
                return []
            finally:
                slow_done.set()

    try:
        with patch.object(live_service, "_CACHE", TTLMemoryCache(600)), \
                patch.object(live_service, "_DETAIL_CACHE", TTLMemoryCache(600)), \
                patch.object(live_service, "_connector_for_library", return_value=Connector()):
            payload = live_service.live_search("시간예산검증책", "title", libraries_raw="mapo,yongsan", deadline=time.monotonic() + 0.1)
            assert fast_done.is_set() and payload["total"] == 1 and payload["meta"]["partial"]
            assert payload["meta"]["successful_libraries"] == 1
            assert live_service._CACHE.get(live_service._cache_key("시간예산검증책", "title", [], ["mapo", "yongsan"])) is None
    finally:
        release.set()
        assert slow_done.wait(2)


def assert_detail_deadline_contract():
    target = {"title": "시간예산검증책 : 부제", "author": "올바른 작가", "publisher": "출판사"}
    book = {**target, "counts": {"total": 1}, "libraries": [{"code": "mapo"}]}
    family = {**book, "title": "시간예산검증책", "counts": {"total": 4}, "counts_partial": True}
    empty = {**book, "counts": {"total": 0}, "libraries": []}
    wrong = {**book, "author": "다른 작가", "counts": {"total": 99}}
    clock, calls = [100.0], []
    queries = [target["title"], "시간예산검증책", "시간예산검증책 추가"]

    def fake_search(*, query, deadline, **kwargs):
        calls.append((query, deadline, deadline - clock[0]))
        clock[0] += 3
        return {"items": [book, wrong], "meta": {}}

    with patch.object(live_search_routes, "LIVE_DETAIL_TOTAL_TIMEOUT", 5), \
            patch.object(live_search_routes.time, "monotonic", side_effect=lambda: clock[0]), \
            patch.object(live_search_routes, "_title_search_candidates", return_value=queries), \
            patch.object(live_search_routes, "live_search", side_effect=fake_search):
        selected = live_search_routes._find_complete_live_book(target)
    assert [call[0] for call in calls] == queries[:2], "expired detail budget must stop the next title candidate"
    assert [call[1] for call in calls] == [105.0, 105.0]
    assert [call[2] for call in calls] == [5.0, 2.0]
    assert selected["author"] == target["author"] and not selected["_live_detail_complete"]
    with patch.object(live_search_routes, "live_search", side_effect=live_service.LiveSearchDeadlineExceeded("test deadline")):
        unknown_author = live_search_routes._find_complete_live_book({**target, "author": ""}, book)
    assert unknown_author["author"] == book["author"] and not unknown_author["_live_detail_complete"]

    client = app.test_client()
    for endpoint in ("live_book_detail", "live_book_summary"):
        route = f"/api/{endpoint}?title={quote(target['title'])}&author={quote(target['author'])}"
        for fallback, expected_status in [(book, 200), (family, 200), (empty, 502), (wrong, 502), (None, 502)]:
            clock[0] = 100
            with patch.object(live_search_routes, "LIVE_DETAIL_TOTAL_TIMEOUT", 1), \
                    patch.object(live_search_routes.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(live_search_routes, "get_cached_live_detail", return_value=copy.deepcopy(fallback)), \
                    patch.object(live_search_routes, "live_search", side_effect=live_service.LiveSearchDeadlineExceeded("test deadline")), \
                    patch("builtins.print"):
                response = client.get(route)
            assert response.status_code == expected_status, f"{endpoint}: invalid fallback accepted: {response.status_code}"
            if expected_status == 200:
                payload = response.get_json()
                assert payload["counts_partial"]
                assert payload.get("book", payload)["author"] == target["author"]
                assert payload.get("book", payload)["counts"]["total"] == fallback["counts"]["total"]
        with patch.object(live_search_routes, "get_cached_live_detail", return_value=None), \
                patch.object(live_search_routes, "live_search", return_value={"items": [], "meta": {}}):
            assert client.get(route).status_code == 404, "complete empty detail is distinct from timed-out lookup"
        for meta in ({"partial": True}, {"diagnostics": [{"error_count": 1}]}):
            with patch.object(live_search_routes, "get_cached_live_detail", return_value=None), \
                    patch.object(live_search_routes, "live_search", return_value={"items": [], "meta": meta}), \
                    patch("builtins.print"):
                assert client.get(route).status_code == 502, "failed empty lookup must not become a completed 404"


def assert_status_budget_cache_contract():
    assert isinstance(status_api_routes.STATUS_CACHE, TTLMemoryCache)
    assert status_api_routes.STATUS_CACHE.max_items == status_api_routes.STATUS_CACHE_SIZE
    clock = {"mono": 100.0, "wall": 100.0}
    cache = TTLMemoryCache(2, max_items=2)
    calls = []
    class Response:
        text = "mock status"
        def raise_for_status(self):
            pass

    class Session:
        duration = 0.0
        def get(self, url, params=None, timeout=None, **kwargs):
            calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
            clock["mono"] += min(self.duration, timeout)
            return Response()

    session = Session()
    client = app.test_client()
    route = "/api/dobong_status?brcd=smoke-budget&category_id=test-category&debug=1"
    key = "dobong:smoke-budget:001,002:test-category"
    with patch.object(status_api_routes, "STATUS_CACHE", cache), \
            patch.object(status_api_routes, "DOBONG_STATUS_TOTAL_TIMEOUT", 12), \
            patch.object(status_api_routes, "DOBONG_STATUS_ATTEMPT_TIMEOUT", 4.5), \
            patch.object(status_api_routes.time, "monotonic", side_effect=lambda: clock["mono"]), \
            patch.object(live_cache.time, "time", side_effect=lambda: clock["wall"]), \
            patch.object(status_api_routes, "get_status_session", return_value=session):
        session.duration = 4.5
        with patch.object(status_api_routes, "parse_dobong_status", return_value=None):
            response = client.get(route)
            assert response.status_code == 502 and response.get_json()["status"] is None
            assert [call["timeout"] for call in calls] == [4.5, 4.5, 3.0]
            assert len(response.get_json()["attempted"]) == 3
            assert cache.get(key) is None, "failed status must not be cached"
            clock["mono"] = 100
            assert client.get(route).status_code == 502
            assert len(calls) == 6, "a failed status must be retried rather than reused"

        calls.clear()
        clock["mono"] = 100
        session.duration = 0.1
        status = {"owned": 2, "loaned": 1, "available": 1, "reserved": 0}
        with patch.object(status_api_routes, "parse_dobong_status", side_effect=[None] * 5 + [status]) as parser:
            response = client.get(route)
            assert response.status_code == 200 and response.get_json()["product_cd"] == "002"
            paths = [call["url"].rsplit("/", 1)[-1] for call in calls]
            assert paths == ["Ebook_Detail.asp", "ebook_View.asp", "audio_View.asp", "Ebook_Detail.asp", "audio_View.asp", "ebook_View.asp"]
            assert [call["params"]["product_cd"] for call in calls] == ["001"] * 3 + ["002"] * 3
            assert all(call["params"].get("category_id") == "test-category" for call in calls if "View.asp" in call["url"])
            parser.side_effect = None
            parser.return_value = status
            assert client.get(route).get_json() == response.get_json() and len(calls) == 6
            cached = cache.get(key)
            assert cached["status"]["owned"] == 2 and "payload" not in cached
            cached["status"]["owned"] = 99
            assert cache.get(key)["status"]["owned"] == 2
            clock["wall"] += 3
            assert client.get(route).status_code == 200 and len(calls) == 7
            cache.clear()
            assert cache.get(key) is None
            assert client.get(route).status_code == 200 and len(calls) == 8

        cache.clear()
        value = {"status": {"owned": 2}}
        cache.set("a", value)
        value["status"]["owned"] = 99
        cache.set("b", {"status": {"owned": 3}})
        assert cache.get("a")["status"]["owned"] == 2
        cache.set("c", {"status": {"owned": 4}})
        assert len(cache._items) == 2 and cache.get("a") is None
        clock["wall"] += 3
        assert cache.get("b") is None and cache.get("c") is None
        assert not cache._items


def assert_seo_public_projection_contract():
    """Synthetic Search Console input must remain private in every public output."""
    kinds = ("indexing", "index_monitor", "technical", "ctr", "ranking", "query_theme",
             "target_page", "target_keyword", "query_mapping", "search_ux")
    query = 'QA_PRIVATE_QUERY_7F3A 검증비공개검색어 "quoted" 전자도서관'
    private_page = f"https://example.invalid/QA_PRIVATE_PAGE_7F3A?q={quote(query)}"
    extra = "QA_EXTRA_SECRET_7F3A"
    metrics = {"impressions": 9876543, "clicks": 7654321, "ctr": 0.00123456789,
               "position": 8.7654321, "delta_impressions": 3456789}
    evidence = {**metrics, "query": query, "page": private_page, "sample_queries": [query],
                "private_extra": extra, "traffic_bucket": extra, "coverage_state": extra,
                "verdict": extra, "error": extra, "status_code": 503,
                "broken_images": [private_page], "broken_internal_links": [private_page]}
    opportunities = []
    for kind in kinds:
        item = seo_planner.make_opportunity(kind, f'{query} {private_page}', extra, copy.deepcopy(evidence), extra)
        item.update({"private_extra": extra, "unknown_nested": {"account_id": extra}, "automation_level": extra})
        item["required_roles"].append(extra)
        item["required_checks"].append(extra)
        item["guardrails"].append(extra)
        opportunities.append(item)
    plan = {"schema_version": "seo_opportunity_plan.v1", "generated_date": "2026-10-14",
            "source_audit_generated_at": extra, "site_url": f"sc-domain:{extra}", "base_url": private_page,
            "period_days": 28, "dry_run_source": True, "guardrails": [extra], "opportunities": opportunities,
            "unknown_header": extra, "visitor_count": 9876543, "raw_property_id": extra}
    original = copy.deepcopy(plan)
    public = seo_planner.sanitize_plan(plan)
    public_markdown = seo_planner.render_markdown(plan, public=True)
    header_keys = {"schema_version", "generated_date", "source_audit_generated_at", "site_url", "base_url",
                   "period_days", "dry_run_source", "guardrails", "opportunities"}
    item_keys = {"id", "type", "priority", "title", "rationale", "suggested_action", "automation_level",
                 "required_roles", "required_checks", "guardrails", "evidence_summary"}
    assert set(public) == header_keys
    assert public["schema_version"] == "seo_opportunity_plan.v1" and public["dry_run_source"] is True
    assert public["period_days"] == 28 and public["generated_date"] == "2026-10-14"
    assert public["site_url"] == public["base_url"] == "https://www.soulib.kr"
    assert len(public["opportunities"]) == len(kinds)
    for index, item in enumerate(public["opportunities"], 1):
        assert set(item) == item_keys
        assert item["type"] == kinds[index - 1] and item["id"] == f"{item['type']}-{index}"
        assert item["required_roles"] == list(seo_planner.ROLE_MAP[item["type"]])
        assert item["required_checks"] == list(seo_planner.CHECK_MAP[item["type"]])
        assert item["automation_level"] == seo_planner.AUTOMATION_LEVEL[item["type"]]
        assert item["title"] in public_markdown and all(role in public_markdown for role in item["required_roles"])
        assert all(check in public_markdown for check in item["required_checks"])
    assert plan == original, "public projection must not mutate private evidence"
    private_json = json.dumps(plan, ensure_ascii=False)
    private_markdown = seo_planner.render_markdown(plan, public=False)
    assert json.loads(private_json)["opportunities"][0]["evidence"]["query"] == query
    assert query in private_markdown and private_page in private_markdown
    assert str(metrics["impressions"]) in private_json and str(metrics["impressions"]) in private_markdown

    def assert_redacted(public_json, markdown):
        encoded = json.dumps(public_json, ensure_ascii=False)
        forbidden = ["qa_private_query_7f3a", "검증비공개검색어", "qa_private_page_7f3a",
                     extra.lower(), quote("검증비공개검색어").lower(), quote(query).lower(),
                     "9876543", "7654321", "8.7654321", "3456789",
                     "노출: 500회 이상", "클릭 있음", "클릭 없음", "순위: 1페이지권", "순위: 개선 여지 있음"]
        for value in forbidden:
            assert value not in encoded.lower() and value not in markdown.lower(), "private SEO data leaked"
        for item in public_json["opportunities"]:
            assert "evidence" not in item and "private_extra" not in item and "unknown_nested" not in item
            assert "impressions" not in item and "clicks" not in item and "position" not in item
    assert_redacted(public, public_markdown)
    malformed = copy.deepcopy(plan)
    malformed.update({"schema_version": extra, "generated_date": extra, "period_days": extra})
    malformed["opportunities"][0].update({"type": extra, "priority": extra})
    closed = seo_planner.sanitize_plan(malformed)
    assert closed["opportunities"][0]["type"] == "review" and closed["opportunities"][0]["priority"] == "P3"
    assert_redacted(closed, seo_planner.render_markdown(malformed, public=True))

    # Real argparse/build/write wiring with a synthetic audit and local temp files.
    row = {**metrics, "query": query, "page": private_page, "private_extra": extra}
    search_row = {**row, "page": f"https://example.invalid/search?q={quote(query)}"}
    audit = {"generated_at": "2026-10-14T00:00:00Z", "site_url": f"sc-domain:{extra}",
             "base_url": private_page, "dry_run": True,
             "url_inspection": {"inspected": [{"url": private_page, "verdict": "FAIL", "unindexed_days": 15},
                                               {"url": private_page, "error": extra}]},
             "technical_checks": {"pages": [{"url": private_page, "ok": False, "status_code": 503}]},
             "search_console": {"periods": [{"days": 28, "top_queries": [row], "top_pages": [row],
                                               "top_page_queries": [search_row]}],
                                "targets": {"pages": [{"page": private_page, "periods": {"28": metrics}}],
                                            "keywords": [{"query": query, "periods": {"28": metrics}}]}}}
    with TemporaryDirectory(prefix="soulib-seo-smoke-") as directory:
        directory = Path(directory)
        audit_path, private_path, public_path, issue_path = [directory / name for name in ("audit.json", "private.json", "public.json", "issue.md")]
        audit_path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([sys.executable, str(ROOT_DIR / "scripts/seo_opportunity_planner.py"), str(audit_path),
                                 "--max-opportunities", "50", "--json-output", str(private_path),
                                 "--public-json-output", str(public_path), "--github-issue-md", str(issue_path),
                                 "--public-summary", "--markdown"], capture_output=True, text=True, check=True)
        public_cli = json.loads(public_path.read_text(encoding="utf-8"))
        private_cli = json.loads(private_path.read_text(encoding="utf-8"))
        issue = issue_path.read_text(encoding="utf-8")
        assert {item["type"] for item in public_cli["opportunities"]} == set(kinds)
        assert public_cli["dry_run_source"] is True and public_cli["schema_version"] == "seo_opportunity_plan.v1"
        assert result.stdout == issue == seo_planner.render_markdown(private_cli, public=True)
        assert_redacted(public_cli, issue)
        private_text = json.dumps(private_cli, ensure_ascii=False)
        assert any(item["evidence"].get("query") == query for item in private_cli["opportunities"])
        assert private_page in private_text and "9876543" in private_text and extra in private_text
        assert "9876543" in seo_planner.render_markdown(private_cli, public=False)
        common = [sys.executable, str(ROOT_DIR / "scripts/seo_opportunity_planner.py"), str(audit_path), "--max-opportunities", "50"]
        public_stdout = subprocess.run(common + ["--public-summary"], capture_output=True, text=True, check=True)
        stdout_plan = json.loads(public_stdout.stdout)
        assert stdout_plan == public_cli, "public-summary stdout JSON must use the same safe projection"
        assert_redacted(stdout_plan, issue)
        private_stdout = subprocess.run(common, capture_output=True, text=True, check=True)
        assert json.loads(private_stdout.stdout) == private_cli, "default stdout must preserve the private plan"


def assert_partial_provenance_contract():
    title = "검증책"
    result = LiveSearchResult(title=title, author="작가", library_code="mapo", library_name="마포", library_short="마포", platform="Kyobo_New")
    success = [{"errors": [], "error_count": 0, "failed_libraries": [], "searched_libraries": 1, "successful_libraries": 1}]
    cases = [(title, "", "", []), ("검증", "", "", ["query_scope"]),
             (title, "교보", "", ["scope_limited"]), ("검증", "교보", "", ["scope_limited", "query_scope"])]
    for query, providers, libraries, expected in cases:
        with patch.object(live_service, "_CACHE", TTLMemoryCache(600)), \
                patch.object(live_service, "_DETAIL_CACHE", TTLMemoryCache(600)), \
                patch.object(live_service, "_search_libraries", return_value=([result], success)):
            payload = live_service.live_search(query, "title", providers_raw=providers, libraries_raw=libraries)
            item = live_search_routes._attach_summary_urls(payload, query)["items"][0]
            assert item["counts_partial_reasons"] == expected and item["failed_libraries"] == []
            assert not payload["meta"]["partial"] and "upstream_failure" not in item["counts_partial_reasons"]
    placeholder = live_search_routes._placeholder_live_book({"title": title})
    assert placeholder["counts_partial"] and placeholder["counts_partial_reasons"] == [] and placeholder["failed_libraries"] == []
    unknown = live_service.counts_partial_provenance(title, {"title": title, "counts_partial": True})
    assert unknown == {"counts_partial": True, "counts_partial_reasons": [], "failed_libraries": []}
    legacy_errors = {"partial": True, "failed_libraries": [], "diagnostics": [{"error_count": 2, "errors": [{"library_code": "mapo"}, {"library_code": "seongbuk"}]}]}
    provenance = live_service.counts_partial_provenance(title, {"title": title}, legacy_errors)
    assert provenance["counts_partial_reasons"] == ["upstream_failure"] and provenance["failed_libraries"] == ["mapo", "seongbuk"]

    class Connector:
        def search_library(self, code, cfg, query, field, limit, timeout):
            if code == "seongbuk":
                raise RuntimeError("synthetic upstream failure")
            return [result]
    for codes, total in [("mapo,seongbuk", 1), ("seongbuk", 0)]:
        with patch.object(live_service, "_CACHE", TTLMemoryCache(600)), \
                patch.object(live_service, "_DETAIL_CACHE", TTLMemoryCache(600)), \
                patch.object(live_service, "_connector_for_library", return_value=Connector()):
            payload = live_service.live_search(title, "title", libraries_raw=codes)
        assert payload["total"] == total and payload["meta"]["partial"]
        assert payload["meta"]["failed_libraries"] == ["seongbuk"]
        if total:
            assert payload["items"][0]["counts_partial_reasons"] == ["upstream_failure", "scope_limited"]

    target = {"title": "검증책 : 부제", "author": "올바른 작가"}
    item = {**target, "counts": {"total": 1}, "libraries": [{"code": "mapo"}]}
    richer = {**item, "title": title, "counts": {"total": 4}}
    def search(*, query, **kwargs):
        return {"items": [item], "meta": legacy_errors} if query == target["title"] else {"items": [richer], "meta": {}}
    with patch.object(live_search_routes, "live_search", side_effect=search):
        selected = live_search_routes._find_complete_live_book(target)
    assert selected["counts"]["total"] == 4 and selected["_live_detail_complete"]
    assert selected["counts_partial_reasons"] == [] and selected["failed_libraries"] == []
    fallback = {**item, "counts": {"total": 9}, "counts_partial": True,
                "counts_partial_reasons": ["upstream_failure"], "failed_libraries": ["yongsan"]}
    with patch.object(live_search_routes, "live_search", return_value={"items": [item], "meta": legacy_errors}):
        selected = live_search_routes._find_complete_live_book(target, fallback)
    assert selected["counts_partial_reasons"] == ["upstream_failure"] and selected["failed_libraries"] == ["yongsan"]
    for endpoint in ("live_book_summary", "live_book_detail"):
        with patch.object(live_search_routes, "get_cached_live_detail", return_value=copy.deepcopy(fallback)), \
                patch.object(live_search_routes, "live_search", side_effect=live_service.LiveSearchDeadlineExceeded("deadline")):
            response = app.test_client().get(f"/api/{endpoint}?title={quote(target['title'])}&author={quote(target['author'])}")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["counts_partial_reasons"] == ["upstream_failure", "deadline"]
        assert payload["failed_libraries"] == ["yongsan"]
        if endpoint == "live_book_detail":
            assert payload["book"]["counts_partial_reasons"] == payload["counts_partial_reasons"]
            assert payload["book"]["failed_libraries"] == payload["failed_libraries"]
    config = live_service.LIBRARIES["dobong"]
    assert config["platform"] == "Kyobo_New" and "/elibrary-front/" in config["homepage_url"]
    assert "dobong" not in live_service.SPECIAL_CONNECTOR_FACTORIES
    modern = {"code": "dobong", "platform_code": "Kyobo_New", "brcd": "QA", "ctts_dvsn_code": "001", "ctgr_id": "001"}
    assert live_search_routes._status_kind(modern) == "kyobo" and live_search_routes._status_supported(modern)
    legacy = {"code": "dobong", "platform_code": "Kyobo", "brcd": "QA"}
    assert live_search_routes._status_kind(legacy) == "dobong" and live_search_routes._status_supported(legacy)


def main():
    shared_shelves_tmp = Path(os.environ["SHARED_SHELVES_FILE"])
    shared_shelves_tmp.unlink(missing_ok=True)
    client = app.test_client()
    assert_live_search_failure_contract()
    assert_search_deadline_contract()
    assert_detail_deadline_contract()
    assert_status_budget_cache_contract()
    assert_seo_public_projection_contract()
    assert_partial_provenance_contract()

    cover_choice = merge_live_results(
        [
            LiveSearchResult(
                title="표지 품질 테스트",
                author="테스터",
                platform="Bookcube",
                image_url="https://cdn.example.com/thumb/cover_90.jpg",
            ),
            LiveSearchResult(
                title="표지 품질 테스트",
                author="테스터",
                platform="SeoulLibrary",
                image_url="https://cdn.example.com/cover_m_480.jpg",
                image_candidates=[{"url": "https://cdn.example.com/cover_m_480.jpg", "hint": "medium"}],
                identifiers={"content_id": "cover-smoke"},
            ),
        ]
    )[0]
    if cover_choice.get("image_url") != "https://cdn.example.com/cover_m_480.jpg":
        raise AssertionError(f"cover representative did not prefer higher-quality candidate: {cover_choice}")
    if not cover_choice.get("image_candidates"):
        raise AssertionError("cover candidates were not preserved during live-result merge")

    landing = assert_response(client, "/")
    landing_body = landing.get_data(as_text=True)
    if "landing-shell" not in landing_body:
        raise AssertionError("landing page did not render expected markup")
    if "<title>서울시 전자도서 통합검색</title>" not in landing_body:
        raise AssertionError("landing page title should keep the service name")
    if "서울 전자도서관 통합검색" not in landing_body:
        raise AssertionError("landing page should keep the original visible headline")
    if "Soulib - 전자도서관 검색" in landing_body:
        raise AssertionError("landing page should not replace the service name with SEO keywords")
    if "landing-seo-summary" in landing_body:
        raise AssertionError("landing page should not render verbose SEO summary")
    if '"@type": "WebSite"' not in landing_body or "SearchAction" not in landing_body:
        raise AssertionError("landing page did not render site search structured data")

    search = assert_response(client, "/search")
    search_body = search.get_data(as_text=True)
    if "search-page" not in search_body:
        raise AssertionError("search page did not render expected markup")
    if "<title>검색 - 서울시 전자도서 통합검색</title>" not in search_body:
        raise AssertionError("search page title should keep the service name")
    if "책 제목이나 저자를 검색하세요." not in search_body:
        raise AssertionError("search page should keep the concise empty state")
    if "search.js?v=live20261019a" not in search_body:
        raise AssertionError("search page should use the current search asset")

    blog = assert_response(client, "/blog")
    blog_body = blog.get_data(as_text=True)
    posts = get_blog_posts()
    if not posts:
        raise AssertionError("blog smoke test requires at least one published post")
    if "blog-home" not in blog_body or "주제별 보기" not in blog_body or "책 추천" not in blog_body:
        raise AssertionError("blog page did not render expected markup")
    if "blog-local-nav" not in blog_body or "blog-local-search" not in blog_body or "blog-menu-dropdown" not in blog_body:
        raise AssertionError("blog page did not render local navigation and search")
    if "최근 글" not in blog_body or "blog-primary-list" not in blog_body or "blog-card-thumb" not in blog_body:
        raise AssertionError("blog page did not render the latest-post-first article list")
    if "blog-home-hero" in blog_body or "blog-visual-strip" in blog_body or "이 순서로 시작하세요" in blog_body:
        raise AssertionError("blog page should not render the old hero, visual strip, or starter-first copy")
    primary_list_index = blog_body.find("blog-primary-list")
    starter_index = blog_body.find("blog-starter")
    category_index = blog_body.find("blog-category-section")
    if primary_list_index < 0 or (starter_index >= 0 and primary_list_index > starter_index):
        raise AssertionError("blog article list should render before starter links")
    if primary_list_index < 0 or (category_index >= 0 and primary_list_index > category_index):
        raise AssertionError("blog article list should render before topic cards")
    rendered_blog_cards = blog_primary_cards(blog_body)
    if not rendered_blog_cards:
        raise AssertionError("blog page did not render blog post cards")
    expected_blog_hrefs = [f"/blog/{post['slug']}" for post in posts]
    rendered_blog_hrefs = [card["href"] for card in rendered_blog_cards]
    compare_count = min(5, len(expected_blog_hrefs), len(rendered_blog_hrefs))
    if rendered_blog_hrefs[:compare_count] != expected_blog_hrefs[:compare_count]:
        raise AssertionError(
            "blog page did not render latest posts first: "
            f"expected {expected_blog_hrefs[:compare_count]}, got {rendered_blog_hrefs[:compare_count]}"
        )
    newest_date = max(post.get("date") or "" for post in posts)
    if rendered_blog_cards[0].get("date") != newest_date:
        raise AssertionError(
            "blog page first card should use the newest post date: "
            f"expected {newest_date}, got {rendered_blog_cards[0].get('date')}"
        )
    assert_blog_images_load(client)
    guide_blog = assert_response(client, "/blog?category=guide")
    guide_blog_body = guide_blog.get_data(as_text=True)
    if (
        "blog-filter-head" not in guide_blog_body
        or "blog-primary-list" not in guide_blog_body
        or "서울 전자도서관을 처음 이용할 때 준비할 것" not in guide_blog_body
        or "이용 안내" not in guide_blog_body
    ):
        raise AssertionError("blog category filter did not render guide posts")
    legacy_library_blog = assert_response(client, "/blog?category=library")
    if "서울 전자도서관을 처음 이용할 때 준비할 것" not in legacy_library_blog.get_data(as_text=True):
        raise AssertionError("legacy blog library category did not map to guide posts")
    searched_blog = assert_response(client, f"/blog?blog_q={quote('서울온')}")
    searched_blog_body = searched_blog.get_data(as_text=True)
    if (
        "blog-filter-head" not in searched_blog_body
        or "blog-primary-list" not in searched_blog_body
        or "검색 결과" not in searched_blog_body
        or "서울 전자도서관을 처음 이용할 때 준비할 것" not in searched_blog_body
    ):
        raise AssertionError("blog search did not render matching posts")
    if "/static/img/blog/seoul-on/seoul-on-google-play.png" not in searched_blog_body:
        raise AssertionError("SeoulOn search result did not render SeoulOn-specific visual")
    ebook_search_blog = assert_response(client, "/blog/ebook-search-guide")
    ebook_search_body = ebook_search_blog.get_data(as_text=True)
    if "전자도서관 검색과 전자책 통합검색을 빠르게 하는 방법" not in ebook_search_body:
        raise AssertionError("ebook search guide post did not render")
    if "blog-highlight" not in ebook_search_body or "<strong>" not in ebook_search_body:
        raise AssertionError("ebook search guide did not render emphasis markup")
    if "/static/img/blog/guide-screens/soulib-search-results.png" not in ebook_search_body:
        raise AssertionError("ebook search guide did not render search screenshot")
    sf_rec_blog = assert_response(client, "/blog/sf-ebook-starter-recommendations")
    sf_rec_body = sf_rec_blog.get_data(as_text=True)
    if "blog-search-card" not in sf_rec_body:
        raise AssertionError("SF recommendation post did not render Soulib search cards")
    if "blog-search-card-kicker" in sf_rec_body or ">Soulib 검색<" in sf_rec_body:
        raise AssertionError("SF recommendation search cards should not render redundant kicker text")
    if "/search?q=%EB%A7%88%EC%85%98&amp;field=title&amp;refine=%EC%95%A4%EB%94%94%20%EC%9C%84%EC%96%B4" not in sf_rec_body:
        raise AssertionError("SF recommendation post should link to title search with author refine")
    if 'data-search-query="마션"' not in sf_rec_body or "blog-search-card-cover" not in sf_rec_body:
        raise AssertionError("SF recommendation post did not render cover-ready search cards")
    if 'data-cover-url="/static/img/blog/book-covers/martian.jpg"' not in sf_rec_body:
        raise AssertionError("SF recommendation post did not render local book cover for search cards")
    if "/static/img/blog/recommendations/sf-next-read/hero-cover-set.png" not in sf_rec_body:
        raise AssertionError("SF recommendation post did not render recommendation-specific cover")
    if "project-hail-mary-official-poster" in sf_rec_body or "blog-post-cover is-external" in sf_rec_body:
        raise AssertionError("recommendation posts should not use an external poster as the representative image")
    if "blog_search_cards.js" not in sf_rec_body:
        raise AssertionError("blog post page did not include search card cover hydration script")
    if "blog_search_cards.js?v=20260527e" not in sf_rec_body:
        raise AssertionError("blog post page should use the current search card hydration asset")
    card_js = assert_response(client, "/static/js/blog_search_cards.js?v=20260527e").get_data(as_text=True)
    if 'field: "title_author"' in card_js or 'field: "title"' not in card_js:
        raise AssertionError("blog search card hydration should use title search with refine, not title_author")
    commute_rec_body = assert_response(client, "/blog/commute-mystery-ebook-recommendations").get_data(as_text=True)
    if "/search?q=%EC%9A%A9%EC%9D%98%EC%9E%90%20X%EC%9D%98%20%ED%97%8C%EC%8B%A0&amp;field=title&amp;refine=%ED%9E%88%EA%B0%80%EC%8B%9C%EB%85%B8%20%EA%B2%8C%EC%9D%B4%EA%B3%A0" not in commute_rec_body:
        raise AssertionError("commute mystery cards should not concatenate title and author in the search query")
    if "blog-advice-fit" in commute_rec_body or "blog-advice-skip" in commute_rec_body:
        raise AssertionError("recommendation posts should keep book-fit copy in plain paragraphs")
    bestseller_rec_blog = assert_response(client, "/blog/bestseller-waitlist-alternative-ebooks")
    bestseller_rec_body = bestseller_rec_blog.get_data(as_text=True)
    if "search-project-hail-mary" in bestseller_rec_body or "detail-project-hail-mary" in bestseller_rec_body:
        raise AssertionError("unrelated recommendation posts must not reuse Project Hail Mary screenshots")
    recommendation_covers = {
        "/blog/bestseller-waitlist-alternative-ebooks": "/static/img/blog/recommendations/bestseller-alternatives/hero-cover-set.png",
        "/blog/commute-mystery-ebook-recommendations": "/static/img/blog/recommendations/commute-mystery/hero-cover-set.png",
        "/blog/ebook-business-starter-recommendations": "/static/img/blog/recommendations/business-starter/hero-cover-set.png",
        "/blog/family-ebook-candidates-for-parent-child-reading": "/static/img/blog/recommendations/family-reading/hero-cover-set.png",
        "/blog/korean-fiction-ebook-starter-recommendations": "/static/img/blog/recommendations/korean-fiction-starter/hero-cover-set.png",
    }
    for path, cover in recommendation_covers.items():
        body = assert_response(client, path).get_data(as_text=True)
        if cover not in body:
            raise AssertionError(f"{path} did not render recommendation-specific cover {cover}")
        if path == "/blog/korean-fiction-ebook-starter-recommendations" and (
            'data-cover-url="/static/img/blog/book-covers/bright-night.jpg"' not in body
        ):
            raise AssertionError("Korean fiction recommendation did not render the local Bright Night cover")
    family_rec_body = assert_response(client, "/blog/family-ebook-candidates-for-parent-child-reading").get_data(as_text=True)
    if "아름다운 아이" not in family_rec_body or "/search?q=%EC%95%84%EB%A6%84%EB%8B%A4%EC%9A%B4%20%EC%95%84%EC%9D%B4&amp;field=title" not in family_rec_body:
        raise AssertionError("family recommendation should use the searchable Korean title for Wonder")
    if "클라라와 태양" in sf_rec_body or "천 개의 파랑" not in sf_rec_body:
        raise AssertionError("SF recommendation should not keep unavailable book-card targets")

    blog_post = assert_response(client, "/blog/soulib-guide")
    blog_post_body = blog_post.get_data(as_text=True)
    if "blog-body" not in blog_post_body or "blog-comment-form" not in blog_post_body:
        raise AssertionError("blog post page did not render expected markup")
    if "blog-post-cover" not in blog_post_body:
        raise AssertionError("blog post page did not render cover image")
    if "함께 읽기" not in blog_post_body or blog_post_body.find("blog-related") > blog_post_body.find("blog-comments"):
        raise AssertionError("blog post page should render related posts before comments")
    if "blog-figure-tall" not in blog_post_body or "/static/img/blog/soulib-guide/home-search.png" not in blog_post_body:
        raise AssertionError("blog post did not render guide screenshots")

    original_blog_get = blog_comments.requests.get
    original_blog_post = blog_comments.requests.post
    original_app_blog_get = app_search.get_blog_comments
    original_app_blog_create = app_search.create_blog_comment

    class FakeBlogCommentsResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "number": 301,
                    "title": "[블로그댓글] soulib-guide - 좋은 글입니다.",
                    "body": "## 이름\n테스터\n\n## 댓글 내용\n좋은 글입니다.",
                    "html_url": "https://github.com/pkkong/soulibrary/issues/301",
                    "created_at": "2026-05-14T08:17:00Z",
                }
            ]

    class FakeBlogCreateResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "number": 302,
                "title": "[블로그댓글] soulib-guide - 댓글 테스트입니다.",
                "body": "## 이름\n독자\n\n## 댓글 내용\n댓글 테스트입니다.",
                "html_url": "https://github.com/pkkong/soulibrary/issues/302",
                "created_at": "2026-05-14T08:18:00Z",
            }

    def fake_blog_get(url, headers=None, params=None, timeout=None):
        if not url.endswith("/issues"):
            raise AssertionError(f"unexpected blog comment list url: {url}")
        return FakeBlogCommentsResponse()

    def fake_blog_post(url, headers=None, json=None, timeout=None):
        if not url.endswith("/issues"):
            raise AssertionError(f"unexpected blog comment create url: {url}")
        if not json or "[블로그댓글] soulib-guide" not in json.get("title", ""):
            raise AssertionError(f"unexpected blog comment payload: {json}")
        return FakeBlogCreateResponse()

    original_comment_env = {
        "GITHUB_ISSUE_TOKEN": os.environ.get("GITHUB_ISSUE_TOKEN"),
        "GITHUB_ISSUE_REPO": os.environ.get("GITHUB_ISSUE_REPO"),
    }
    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/soulibrary"
    blog_comments.requests.get = fake_blog_get
    blog_comments.requests.post = fake_blog_post
    app_search.get_blog_comments = blog_comments.get_blog_comments
    app_search.create_blog_comment = blog_comments.create_blog_comment
    try:
        blog_with_comments = assert_response(client, "/blog/soulib-guide")
        if "좋은 글입니다." not in blog_with_comments.get_data(as_text=True):
            raise AssertionError("blog comments did not render from GitHub issues")
        comment_submit = client.post(
            "/blog/soulib-guide",
            data={"author": "독자", "message": "댓글 테스트입니다.", "website": ""},
        )
        if comment_submit.status_code != 201 or "댓글이 등록되었습니다" not in comment_submit.get_data(as_text=True):
            raise AssertionError(f"blog comment submission failed: {comment_submit.status_code}")
    finally:
        blog_comments.requests.get = original_blog_get
        blog_comments.requests.post = original_blog_post
        app_search.get_blog_comments = original_app_blog_get
        app_search.create_blog_comment = original_app_blog_create
        for name, value in original_comment_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    my_shelf = assert_response(client, "/my-shelf")
    if "shelf-shell" not in my_shelf.get_data(as_text=True):
        raise AssertionError("my shelf page did not render expected markup")

    share_response = client.post(
        "/api/shelves/share",
        json={
            "list": {"name": "스모크 서재"},
            "books": [
                {
                    "title": "프로젝트 헤일메리",
                    "author": "앤디 위어",
                    "publisher": "알에이치코리아",
                    "counts": {"kyobo": 1, "yes24": 0, "other": 1, "total": 2},
                }
            ],
        },
    )
    if share_response.status_code != 201:
        raise AssertionError(f"shared shelf creation failed: {share_response.status_code} {share_response.get_data(as_text=True)[:500]}")
    shared_payload = share_response.get_json()
    shared_page = assert_response(client, f"/shelf/{shared_payload['slug']}")
    if "shared-shelf-shell" not in shared_page.get_data(as_text=True):
        raise AssertionError("shared shelf page did not render expected markup")

    original_shared_storage = app_search.SHARED_SHELVES_STORAGE
    original_shared_env = {name: os.environ.get(name) for name in ("VERCEL", "DATABASE_URL", "DB_HOST")}
    try:
        app_search.SHARED_SHELVES_STORAGE = "auto"
        os.environ["VERCEL"] = "1"
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("DB_HOST", None)
        try:
            app_search._shared_shelves_use_postgres()
        except RuntimeError as exc:
            if "Vercel shared shelves require" not in str(exc):
                raise
        else:
            raise AssertionError("Vercel shared shelves used JSON fallback without PostgreSQL env")

        os.environ["DATABASE_URL"] = "postgres://user:pass@example.supabase.co:5432/postgres"
        if not app_search._shared_shelves_use_postgres():
            raise AssertionError("shared shelves did not select PostgreSQL when DATABASE_URL was set")
    finally:
        app_search.SHARED_SHELVES_STORAGE = original_shared_storage
        for name, value in original_shared_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    if db_module.psycopg2 is not None:
        original_db_env = {name: os.environ.get(name) for name in ("DATABASE_URL", "DB_HOST")}
        original_connect = db_module.psycopg2.connect
        connect_calls = []

        class DummyPgConnection:
            def cursor(self, *args, **kwargs):
                raise AssertionError("smoke test should not execute SQL through dummy connection")

            def close(self):
                return None

        def fake_connect(*args, **kwargs):
            connect_calls.append((args, kwargs))
            return DummyPgConnection()

        try:
            os.environ["DATABASE_URL"] = "postgres://user:pass@example.supabase.co:6543/postgres?sslmode=require"
            os.environ.pop("DB_HOST", None)
            db_module.psycopg2.connect = fake_connect
            db_module.get_db().close()
        finally:
            db_module.psycopg2.connect = original_connect
            for name, value in original_db_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        if not connect_calls or connect_calls[0][0][0] != "postgres://user:pass@example.supabase.co:6543/postgres?sslmode=require":
            raise AssertionError("DATABASE_URL was not passed directly to psycopg2.connect")

    original_find_complete_live_book = live_search_routes._find_complete_live_book
    seo_live_calls = []

    def blocked_seo_live_lookup(*args, **kwargs):
        seo_live_calls.append((args, kwargs))
        raise AssertionError("SEO book pages must not block on live detail lookup")

    live_search_routes._find_complete_live_book = blocked_seo_live_lookup
    try:
        seo_page = assert_response(client, "/books/project-hail-mary")
    finally:
        live_search_routes._find_complete_live_book = original_find_complete_live_book
    if seo_live_calls:
        raise AssertionError("SEO book page called live detail lookup during server render")
    if "/api/live_book_detail?" not in seo_page.get_data(as_text=True):
        raise AssertionError("SEO book page did not include async detail hydration")

    original_seo_env = {
        "SEO_AUTO_CAPTURE": os.environ.get("SEO_AUTO_CAPTURE"),
        "SEO_DYNAMIC_BOOKS": os.environ.get("SEO_DYNAMIC_BOOKS"),
        "SEO_AUTO_PUBLISH": os.environ.get("SEO_AUTO_PUBLISH"),
        "SEO_BOOKS_PATH": os.environ.get("SEO_BOOKS_PATH"),
    }
    seo_tmp = ROOT_DIR / "data" / "_tmp_smoke_seo_books.json"
    seo_tmp.unlink(missing_ok=True)
    for env_name in ("SEO_AUTO_CAPTURE", "SEO_DYNAMIC_BOOKS", "SEO_AUTO_PUBLISH"):
        os.environ.pop(env_name, None)
    os.environ["SEO_BOOKS_PATH"] = str(seo_tmp)
    try:
        recorded = seo_books.record_search_results(
            "자동 SEO 테스트",
            {
                "items": [
                    {
                        "title": "자동 SEO 테스트",
                        "author": "테스터",
                        "publisher": "테스트출판",
                        "counts": {"total": 99},
                    }
                ]
            },
        )
        if recorded != 0 or seo_tmp.exists():
            raise AssertionError("SEO auto capture should be disabled by default")

        os.environ["SEO_AUTO_CAPTURE"] = "1"
        os.environ.pop("SEO_AUTO_PUBLISH", None)
        recorded = seo_books.record_search_results(
            "자동 SEO 테스트",
            {
                "items": [
                    {
                        "title": "자동 SEO 테스트",
                        "author": "테스터",
                        "publisher": "테스트출판",
                        "counts": {"total": 99},
                    }
                ]
            },
        )
        if recorded != 1:
            raise AssertionError("SEO explicit capture did not store candidate")
        os.environ["SEO_AUTO_PUBLISH"] = "1"
        recorded_again = seo_books.record_search_results(
            "자동 SEO 테스트",
            {
                "items": [
                    {
                        "title": "자동 SEO 테스트",
                        "author": "테스터",
                        "publisher": "테스트출판",
                        "counts": {"total": 99},
                    }
                ]
            },
        )
        if recorded_again != 1:
            raise AssertionError("SEO repeated capture did not update existing candidate")
        with seo_tmp.open(encoding="utf-8") as f:
            seo_store = json.load(f)
        captured_book = next(book for book in seo_store["books"] if book["title"] == "자동 SEO 테스트")
        if captured_book.get("status") != "candidate":
            raise AssertionError("SEO search capture should never publish candidates directly")
        if any(book.get("slug") == "자동-seo-테스트" for book in seo_books.get_seo_books()):
            raise AssertionError("SEO captured candidates should not publish by default")

        def matching_seo_search(query, field, providers_raw, libraries_raw, limit, offset):
            if query != "자동 SEO 테스트" or field != "title":
                raise AssertionError(f"unexpected SEO validation query: {query}/{field}")
            return {
                "items": [
                    {
                        "title": "자동 SEO 테스트",
                        "author": "테스터",
                        "publisher": "테스트출판",
                        "counts": {"total": 12},
                        "image_url": "https://example.com/cover.jpg",
                        "live_detail_key": "smoke-seo-key",
                    }
                ]
            }

        review_summary = seo_books.review_seo_candidates(matching_seo_search, auto_publish=False)
        if review_summary.get("approved") != 1:
            raise AssertionError(f"SEO validation did not approve matching candidate: {review_summary}")
        with seo_tmp.open(encoding="utf-8") as f:
            seo_store = json.load(f)
        approved_book = next(book for book in seo_store["books"] if book["title"] == "자동 SEO 테스트")
        if approved_book.get("status") != "approved" or approved_book.get("validation", {}).get("score", 0) < 70:
            raise AssertionError("SEO validation did not store approved review metadata")
        os.environ["SEO_DYNAMIC_BOOKS"] = "1"
        if any(book.get("slug") == "자동-seo-테스트" for book in seo_books.get_seo_books()):
            raise AssertionError("SEO approved candidates should not render as published pages")

        publish_summary = seo_books.review_seo_candidates(matching_seo_search, auto_publish=True)
        if publish_summary.get("published") != 1:
            raise AssertionError(f"SEO validation did not publish matching candidate: {publish_summary}")
        if not any(book.get("slug") == "자동-seo-테스트" for book in seo_books.get_seo_books()):
            raise AssertionError("SEO published dynamic book did not render when enabled")

        os.environ.pop("SEO_AUTO_PUBLISH", None)
        recorded_bad = seo_books.record_search_results(
            "검증 실패 테스트",
            {
                "items": [
                    {
                        "title": "검증 실패 테스트",
                        "author": "다른저자",
                        "publisher": "다른출판",
                        "counts": {"total": 99},
                    }
                ]
            },
        )
        if recorded_bad != 1:
            raise AssertionError("SEO bad candidate fixture was not captured")

        def mismatched_seo_search(query, field, providers_raw, libraries_raw, limit, offset):
            return {
                "items": [
                    {
                        "title": "완전히 다른 책",
                        "author": "불일치",
                        "publisher": "불일치",
                        "counts": {"total": 1},
                    }
                ]
            }

        reject_summary = seo_books.review_seo_candidates(mismatched_seo_search, auto_publish=True)
        if reject_summary.get("rejected") != 1:
            raise AssertionError(f"SEO validation did not reject mismatched candidate: {reject_summary}")
        with seo_tmp.open(encoding="utf-8") as f:
            seo_store = json.load(f)
        rejected_book = next(book for book in seo_store["books"] if book["title"] == "검증 실패 테스트")
        if rejected_book.get("status") != "rejected":
            raise AssertionError("SEO mismatched candidate was not marked rejected")
    finally:
        seo_tmp.unlink(missing_ok=True)
        for name, value in original_seo_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    empty_search = assert_response(client, "/api/search")
    if empty_search.headers.get("X-Robots-Tag") != "noindex, nofollow":
        raise AssertionError("API responses must send X-Robots-Tag noindex,nofollow")
    payload = empty_search.get_json()
    if payload != {"total": 0, "items": []}:
        raise AssertionError(f"unexpected empty search payload: {payload}")

    sitemap = assert_response(client, "/sitemap.xml")
    sitemap_body = sitemap.get_data(as_text=True)
    if "/sitemap-static.xml" not in sitemap_body:
        raise AssertionError("sitemap index did not include static sitemap")

    seo_landing_paths = (
        "/ebook-search",
        "/digital-library-search",
        "/seoul-ebook-library-search",
    )
    for path in seo_landing_paths:
        page = assert_response(client, path)
        body = page.get_data(as_text=True)
        if f'href="http://localhost{path}"' not in body and f'href="https://www.soulib.kr{path}"' not in body:
            raise AssertionError(f"{path} did not render canonical link")
        if '<meta name="description"' not in body:
            raise AssertionError(f"{path} did not render meta description")
        if 'class="landing-search seo-landing-search"' not in body or 'action="/search"' not in body or 'name="q"' not in body:
            raise AssertionError(f"{path} did not render search form")

    static_sitemap = assert_response(client, "/sitemap-static.xml")
    static_sitemap_body = static_sitemap.get_data(as_text=True)
    for path in seo_landing_paths:
        if path not in static_sitemap_body:
            raise AssertionError(f"static sitemap did not include {path}")
    if "/reports" in static_sitemap_body:
        raise AssertionError("static sitemap should not include /reports")

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
            "html_url": "https://github.com/pkkong/soulibrary/issues/2",
            "state": "closed",
            "created_at": "2026-05-14T08:17:00Z",
            "closed_at": "2026-05-14T09:00:00Z",
        }
    )
    if (
        parsed_report["category"] != "대출 상태"
        or parsed_report["status_label"] != "종료됨"
        or parsed_report["resolution_message"] != ""
        or parsed_report["resolution_at"] is not None
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

    merged_unscripted = merge_live_results(
        [
            LiveSearchResult(
                title="언스크립티드(Unscripted)(부의 추월차선 완결판)",
                author="엠제이 드마코",
                publisher="토트",
                library_code="gangnam",
                library_name="강남구 전자도서관",
                platform="Kyobo_New",
            ),
            LiveSearchResult(
                title="언스크립티드",
                author="엠제이 드마코",
                publisher="토트",
                library_code="gangbuk",
                library_name="강북구 전자도서관",
                platform="Kyobo_New",
            ),
            LiveSearchResult(
                title="언스크립티드 : 부의 추월차선 완결판",
                author="엠제이 드마코",
                publisher="토트출판사",
                library_code="yes24_jongno",
                library_name="종로구립도서관",
                platform="YES24",
            ),
        ]
    )
    if len(merged_unscripted) != 1 or merged_unscripted[0]["counts"]["total"] != 3:
        raise AssertionError(f"unscripted title variants did not merge: {merged_unscripted}")

    merged_housemaid = merge_live_results(
        [
            LiveSearchResult(
                title="하우스메이드 2",
                author="프라다 맥파든",
                publisher="북플라자",
                library_code="gangnam",
                library_name="강남구 전자도서관",
                platform="Kyobo_New",
            ),
            LiveSearchResult(
                title="하우스메이드 2 - 하우스메이드의 비밀",
                author="프리다 맥파든 지음, 황성연 옮김",
                publisher="북플라자",
                library_code="yes24_jongno",
                library_name="종로구립도서관",
                platform="YES24",
            ),
            LiveSearchResult(
                title="하우스메이드 3 - 하우스메이드의 집",
                author="프리다 맥파든 지음, 정미정 옮김",
                publisher="북플라자",
                library_code="gangbuk",
                library_name="강북구 전자도서관",
                platform="Kyobo_New",
            ),
            LiveSearchResult(
                title="하우스메이드 3",
                author="프리다 맥파든",
                publisher="북플라자",
                library_code="sen",
                library_name="서울시교육청",
                platform="SeoulEducation",
            ),
        ]
    )
    if len(merged_housemaid) != 2:
        raise AssertionError(f"housemaid series variants did not merge by volume: {merged_housemaid}")

    volume_split = merge_live_results(
        [
            LiveSearchResult(title="테스트 소설(1)", author="테스터", library_code="a", library_name="A"),
            LiveSearchResult(title="테스트 소설(2)", author="테스터", library_code="b", library_name="B"),
        ]
    )
    if len(volume_split) != 2:
        raise AssertionError(f"volume markers should stay separate: {volume_split}")
    if normalize_title_for_group("테스트 제목-부제") != normalize_title_for_group("테스트 제목"):
        raise AssertionError("compact hyphen subtitle should normalize to the base title")
    if normalize_title_for_group("COVID-19 시대") == normalize_title_for_group("COVID"):
        raise AssertionError("technical hyphenated titles should not be cut as compact subtitles")
    if normalize_author("홍길동·김철수") != normalize_author("홍길동"):
        raise AssertionError("middle-dot author separator should keep the first author")

    if not _result_matches_query(
        "언스크립티드",
        "title_author",
        LiveSearchResult(title="언스크립티드", author="엠제이 드마코"),
    ):
        raise AssertionError("query filter rejected a matching title")
    if _result_matches_query(
        "언스크립티드",
        "title_author",
        LiveSearchResult(title="A Select Collection of Old English Plays", author="NULL", publisher="iGB"),
    ):
        raise AssertionError("query filter accepted an unrelated result")

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
    original_set_cached_detail = live_search_routes.set_cached_live_detail
    cache_writes = {}
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
    long_title = "최소한의 삼국지 : 최태성의 삼국지 고전 특강"
    base_title = "최소한의 삼국지"
    long_title_book = {
        "title": long_title,
        "author": "최태성",
        "publisher": "프런트페이지",
        "counts": {"kyobo": 1, "yes24": 0, "other": 0, "total": 1},
        "libraries": [
            {"code": "eunpyeong", "name": "은평구립전자도서관", "short": "은평", "platform_code": "Eunpyeong"},
        ],
    }
    base_title_book = {
        "title": base_title,
        "author": "최태성",
        "publisher": "프런트페이지",
        "counts": {"kyobo": 1, "yes24": 1, "other": 2, "total": 4},
        "libraries": [
            {"code": "eunpyeong", "name": "은평구립전자도서관", "short": "은평", "platform_code": "Eunpyeong"},
            {"code": "dobong", "name": "도봉구 전자도서관", "short": "도봉", "platform_code": "Kyobo"},
            {"code": "jongno", "name": "종로구립도서관", "short": "종로", "platform_code": "YES24"},
            {"code": "gangnam", "name": "강남구 전자도서관", "short": "강남", "platform_code": "Gangnam"},
        ],
    }
    wrong_author_base_title_book = {
        "title": base_title,
        "author": "다른 저자",
        "publisher": "다른출판",
        "counts": {"kyobo": 9, "yes24": 0, "other": 0, "total": 9},
        "libraries": [
            {"code": "wrong_author", "name": "오탐 도서관", "short": "오탐", "platform_code": "Kyobo_New"},
        ],
    }
    failed_partial_title = "부분 결과 실패 : 부제"
    failed_partial_base_title = "부분 결과 실패"
    failed_partial_book = {
        "title": failed_partial_title,
        "author": "올바른 저자",
        "publisher": "올바른출판",
        "counts": {"kyobo": 1, "yes24": 0, "other": 0, "total": 1},
        "counts_partial": True,
        "libraries": [
            {"code": "partial_only", "name": "부분 도서관", "short": "부분", "platform_code": "Kyobo_New"},
        ],
    }
    wrong_failed_partial_book = {
        "title": failed_partial_base_title,
        "author": "다른 저자",
        "publisher": "다른출판",
        "counts": {"kyobo": 7, "yes24": 0, "other": 0, "total": 7},
        "libraries": [
            {"code": "wrong_failed", "name": "잘못된 도서관", "short": "오류", "platform_code": "Kyobo_New"},
        ],
    }

    def fake_cached_detail(key):
        if not key:
            return None
        if key == "complete-project":
            return complete_cached_book
        if key == "failed-partial":
            return failed_partial_book
        if key != "partial-project":
            raise AssertionError(f"unexpected detail key: {key}")
        return partial_book

    def fake_set_cached_detail(key, item):
        cache_writes[key] = dict(item)

    def fake_live_search(query, field, providers_raw="", libraries_raw="", limit=20, offset=0, refine="", *, deadline=None):
        if query == "프로젝트" and field == "title_author":
            return {"total": 1, "items": [partial_book], "filters": {"providers": [], "libraries": []}, "meta": {}}
        if query == "프로젝트 헤일메리" and field == "title":
            return {"total": 1, "items": [complete_book], "filters": {"providers": [], "libraries": []}, "meta": {}}
        if query == "구독형 테스트" and field == "title":
            return {"total": 1, "items": [subscription_book], "filters": {"providers": [], "libraries": []}, "meta": {}}
        if query == long_title and field == "title":
            return {"total": 1, "items": [long_title_book], "filters": {"providers": [], "libraries": []}, "meta": {}}
        if query == base_title and field == "title":
            return {
                "total": 2,
                "items": [wrong_author_base_title_book, base_title_book],
                "filters": {"providers": [], "libraries": []},
                "meta": {},
            }
        if query in {failed_partial_title, failed_partial_base_title} and field == "title":
            return {
                "total": 1,
                "items": [wrong_failed_partial_book],
                "filters": {"providers": [], "libraries": []},
                "meta": {},
            }
        raise AssertionError(f"unexpected live search: {query} {field}")

    live_search_routes.get_cached_live_detail = fake_cached_detail
    live_search_routes.live_search = fake_live_search
    live_search_routes.set_cached_live_detail = fake_set_cached_detail
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
        long_title_payload = assert_response(
            client,
            f"/api/live_book_detail?title={quote(long_title)}&author={quote('최태성')}&publisher={quote('프런트페이지')}",
        ).get_json()
        failed_partial_payload = assert_response(
            client,
            f"/api/live_book_detail?key=failed-partial&title={quote(failed_partial_title)}&author={quote('올바른 저자')}&publisher={quote('올바른출판')}",
        ).get_json()
    finally:
        live_search_routes.live_search = original_live_search
        live_search_routes.get_cached_live_detail = original_cached_detail
        live_search_routes.set_cached_live_detail = original_set_cached_detail
    hydrated_body = hydrated_detail.get_data(as_text=True)
    if "은평" not in hydrated_body or "강남" in hydrated_body or "/api/live_book_detail" not in hydrated_body:
        raise AssertionError("live detail should render cached partial result before background hydration")
    if 'data-live-status="1"' in hydrated_body or "도서관에서 확인" not in hydrated_body:
        raise AssertionError("live detail should not request status when required identifiers are missing")
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
    selected_long_title_book = long_title_payload.get("book") or {}
    long_title_groups_html = long_title_payload.get("groups_html") or ""
    if selected_long_title_book.get("title") != base_title or selected_long_title_book.get("counts", {}).get("total") != 4:
        raise AssertionError(f"long subtitle detail did not select richer base-title result: {long_title_payload}")
    if "오탐 도서관" in long_title_groups_html or "강남" not in long_title_groups_html:
        raise AssertionError(f"long subtitle detail did not filter by compatible author: {long_title_payload}")
    failed_partial_book_payload = failed_partial_payload.get("book") or {}
    if failed_partial_book_payload.get("title") != failed_partial_title:
        raise AssertionError(f"failed detail hydration should fall back to the partial book: {failed_partial_payload}")
    if cache_writes.get("failed-partial", {}).get("counts_partial") is not True:
        raise AssertionError(f"failed detail hydration must not mark partial fallback complete: {cache_writes}")
    if "잘못된 도서관" in (failed_partial_payload.get("groups_html") or ""):
        raise AssertionError(f"failed detail hydration accepted a mismatched high-count result: {failed_partial_payload}")
    subscription_groups_html = subscription_payload.get("groups_html") or ""
    if 'data-live-status="1"' in subscription_groups_html or "구독형" not in subscription_groups_html:
        raise AssertionError("subscription libraries should render without live status polling")
    if "status-available" not in subscription_groups_html or "is-muted" in subscription_groups_html:
        raise AssertionError("subscription libraries should render with available styling")
    if "도서관에서 확인" not in subscription_detail.get_data(as_text=True):
        raise AssertionError("live detail status failures should fall back to a library-check label")

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
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "number": 124,
                    "title": "[오류신고] 대출 상태 - 해결된 신고입니다.",
                    "body": "## 신고 내용\n해결된 신고입니다.",
                    "html_url": "https://github.com/pkkong/soulibrary/issues/124",
                    "comments_url": "https://api.github.com/repos/pkkong/soulibrary/issues/124/comments",
                    "comments": 1,
                    "state": "closed",
                    "state_reason": "completed",
                    "created_at": "2026-05-14T08:18:00Z",
                    "closed_at": "2026-05-14T09:00:00Z",
                    "updated_at": "2026-05-14T09:00:00Z",
                },
                {
                    "number": 122,
                    "title": "[오류신고] 오류 - 기존 신고 내용입니다.",
                    "body": "## 신고 내용\n기존 신고 내용입니다.\n\n## 문제가 있던 주소\nhttps://example.com/search",
                    "html_url": "https://github.com/pkkong/soulibrary/issues/122",
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
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "body": "## 처리 결과\n조치 완료\n수정 후 배포 완료했습니다.",
                    "author_association": "OWNER",
                    "created_at": "2026-05-14T09:00:00Z",
                }
            ]

    class FakeIssueResponse:
        status_code = 201

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "number": 123,
                "title": self.payload.get("title") or "[오류신고] 오류 - 자동 테스트 신고 내용입니다.",
                "body": self.payload.get("body") or "## 신고 내용\n자동 테스트 신고 내용입니다.",
                "html_url": "https://github.com/pkkong/soulibrary/issues/123",
                "state": "open",
                "created_at": "2026-05-14T08:17:00Z",
            }

    class FakeIssueFailureResponse:
        status_code = 500

        def raise_for_status(self):
            raise RuntimeError("fake issue creation failure")

    def fake_issue_get(url, headers=None, params=None, timeout=None, allow_redirects=True):
        if allow_redirects:
            raise AssertionError("GitHub list and comment reads must not follow redirects")
        if url == "https://api.github.com/repos/pkkong/soulibrary/issues/124/comments":
            return FakeIssueCommentsResponse()
        if url != "https://api.github.com/repos/pkkong/soulibrary/issues":
            raise AssertionError(f"unexpected issue list url: {url}")
        if not params or params.get("state") != "all":
            raise AssertionError(f"unexpected issue list params: {params}")
        return FakeIssueListResponse()

    issue_post_calls = {"count": 0}

    def fake_issue_post(url, headers=None, json=None, timeout=None):
        issue_post_calls["count"] += 1
        if url != "https://api.github.com/repos/pkkong/soulibrary/issues":
            raise AssertionError(f"unexpected issue url: {url}")
        body = (json or {}).get("body", "")
        if "## 연락처" in body or "tester@example.com" in body:
            raise AssertionError("report submission must not publish a contact field")
        if "저장 실패 테스트입니다." in body:
            return FakeIssueFailureResponse()
        if not json or (
            "자동 테스트 신고 내용입니다." not in body
            and "JSON 테스트 신고 내용입니다." not in body
        ):
            raise AssertionError(f"unexpected issue payload: {json}")
        return FakeIssueResponse(json)

    for env_name in github_env_names:
        os.environ.pop(env_name, None)
    report_source_url = "https://www.soulib.kr/search?q=언스크립티드&field=title_author"
    prefilled_report = assert_response(client, f"/reports?url={quote(report_source_url, safe='')}")
    prefilled_body = prefilled_report.get_data(as_text=True)
    if "https://www.soulib.kr/search?q=언스크립티드" not in prefilled_body or "field=title_author" not in prefilled_body:
        raise AssertionError("reports page did not preserve full source URL query string")

    missing_store = assert_response(client, "/reports")
    missing_store_body = missing_store.get_data(as_text=True)
    if "report-form" not in missing_store_body:
        raise AssertionError("reports page did not render expected markup")
    if "GitHub Issues 저장소 연결에 실패했습니다" in missing_store_body:
        raise AssertionError("reports page blocked initial render on GitHub store status")
    missing_recent = client.get("/api/reports/recent")
    if missing_recent.status_code != 503:
        raise AssertionError(f"missing report store API returned {missing_recent.status_code}, expected 503")
    if missing_recent.headers.get("X-Robots-Tag") != "noindex, nofollow":
        raise AssertionError("reports API must send X-Robots-Tag noindex,nofollow")
    missing_recent_payload = missing_recent.get_json()
    missing_recent_html = missing_recent_payload.get("html") or ""
    if "최근 접수 목록을 잠시 불러오지 못했습니다" not in missing_recent_html:
        raise AssertionError("reports API did not show the customer-facing unavailable message")
    if "GitHub" in missing_recent_html or "GITHUB_ISSUE_TOKEN" in missing_recent_html:
        raise AssertionError("reports API leaked internal report-store details")

    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/soulibrary"
    report_routes.requests.get = fake_issue_get
    reports_shell = assert_response(client, "/reports")
    reports_body = reports_shell.get_data(as_text=True)
    if "기존 신고 내용입니다" not in reports_body or "이슈 #122" not in reports_body:
        recent_reports = assert_response(client, "/api/reports/recent")
        reports_body = recent_reports.get_json().get("html") or ""
    if "기존 신고 내용입니다" not in reports_body or "이슈 #122" not in reports_body:
        raise AssertionError("reports page did not render GitHub issues as the report store")
    if "처리 안내" not in reports_body:
        raise AssertionError("reports page did not render customer-facing resolution heading")
    if "신고하신 문제를 해결했습니다." not in reports_body or "해결됨" not in reports_body:
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
        invalid_api_submission = client.post(
            "/api/reports",
            json={"category": "오류", "message": "짧음", "page_url": "https://example.com/search"},
        )
        trap_call_count = issue_post_calls["count"]
        trap_api_submission = client.post(
            "/api/reports",
            json={
                "category": "오류",
                "message": "허니팟 테스트 신고 내용입니다.",
                "page_url": "https://example.com/search",
                "website": "https://spam.example.com",
            },
        )
        trap_post_call_count = issue_post_calls["count"]
        json_submission = client.post(
            "/api/reports",
            json={
                "category": "오류",
                "message": "JSON 테스트 신고 내용입니다.",
                "page_url": "https://example.com/toss",
                "contact": "tester@example.com",
            },
        )
        failed_api_submission = client.post(
            "/api/reports",
            json={
                "category": "오류",
                "message": "저장 실패 테스트입니다.",
                "page_url": "https://example.com/failure",
            },
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
    if invalid_api_submission.status_code != 400:
        raise AssertionError(f"invalid JSON report returned {invalid_api_submission.status_code}, expected 400")
    invalid_api_payload = invalid_api_submission.get_json()
    if "어떤 문제가 있었는지" not in (invalid_api_payload.get("error") or ""):
        raise AssertionError("invalid JSON report did not reuse report message validation")
    if trap_api_submission.status_code != 200:
        raise AssertionError(f"honeypot JSON report returned {trap_api_submission.status_code}, expected 200")
    if trap_post_call_count != trap_call_count:
        raise AssertionError("honeypot JSON report attempted to create a GitHub issue")
    trap_payload = trap_api_submission.get_json()
    if not trap_payload.get("ok") or trap_payload.get("report") is not None:
        raise AssertionError("honeypot JSON report did not return a success-like JSON response")
    if json_submission.status_code != 201:
        body = json_submission.get_data(as_text=True)[:500]
        raise AssertionError(f"JSON report submission failed with {json_submission.status_code}: {body}")
    json_payload = json_submission.get_json()
    json_report = json_payload.get("report") or {}
    if not json_payload.get("ok") or json_report.get("issue_number") != 123:
        raise AssertionError(f"JSON report submission did not return created report summary: {json_payload}")
    if json_report.get("message") != "JSON 테스트 신고 내용입니다.":
        raise AssertionError("JSON report summary did not preserve cleaned message")
    if json_report.get("page_url") != "https://example.com/toss":
        raise AssertionError("JSON report summary did not preserve page_url")
    if failed_api_submission.status_code != 500:
        raise AssertionError(f"failed JSON report returned {failed_api_submission.status_code}, expected 500")
    failed_payload = failed_api_submission.get_json()
    if failed_payload.get("error") != report_routes.REPORT_SAVE_ERROR:
        raise AssertionError("failed JSON report did not return customer-facing save error")

    report_routes.requests.get = fake_issue_get
    os.environ["GITHUB_ISSUE_TOKEN"] = "smoke-test-token"
    os.environ["GITHUB_ISSUE_REPO"] = "pkkong/soulibrary"
    try:
        saved = assert_response(client, "/reports?saved=1")
    finally:
        report_routes.requests.get = original_get
        restore_github_env()
    if "신고가 접수되었습니다" not in saved.get_data(as_text=True):
        raise AssertionError("report saved confirmation did not render")

    shared_shelves_tmp.unlink(missing_ok=True)
    print("smoke_test: ok")


if __name__ == "__main__":
    main()
