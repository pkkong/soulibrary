"""Offline transport/auth/deadline/zero-result regressions for the library relay."""

import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))

import requests
from flask import Flask
import library_relay_app
from config import LIBRARIES
from live_search import relay
from live_search.connectors.kyobo import KyoboNewConnector
from live_search.connectors.yes24 import Yes24Connector
import status_api_routes

# Compact fixtures preserve the actual successful/zero document structures
# observed at the two official sites. No production user data is copied here.
KYOBO_RESULT = '''<html><body><div class="book_resultTxt">검색결과 총 1개</div>
<ul class="book_resultList"><li><ul><li class="tit"><a onclick="fnContentClick(this, '001', '12345', '1101', '')">검증 도서</a></li>
<li class="writer">검증 저자<span>검증 출판사</span></li></ul></li></ul></body></html>'''
KYOBO_ZERO = '''<html><body><div class="book_resultTxt"><p><strong>검증</strong> 에 대한 검색 결과가 없습니다.</p></div></body></html>'''
YES24_RESULT = '''<html><body><div class="total">전체 <em>1</em>건</div><div class="ebook-list"><div class="bx clearfix">
<p class="tit"><a href="/ebook/detail?goods_id=12345">검증 도서</a></p><p class="writer">검증 저자</p>
<p class="detail"><span>검증 출판사</span><span>2026</span><span>예스24</span></p></div></div></body></html>'''
YES24_ZERO = '<html><body><div class="total">전체 <em>0</em>건 (0 / 0)</div><div class="ebook-list"></div></body></html>'
KYOBO_STATUS = '<html><body><p class="use">대출 : 1 / 3 예약 : 2</p></body></html>'
YES24_STAT = '<div class="stat"><li>보유<strong>3</strong></li><li>대출<strong>1</strong></li><li>예약<strong>2</strong></li></div>'
YES24_STATUS = '<html><body><div class="ebook-view">' + YES24_STAT + '</div><input name="return_url" value="/ebook/detail/?goods_id=12345"></body></html>'
YES24_STATUS_LIST = '<html><body><div class="ebook-list"><div class="bx"><a href="/ebook/detail?goods_id=12345">검증</a>' + YES24_STAT + '</div></div></body></html>'
SECRET = "offline-test-secret-which-is-at-least-32-bytes"
ENV = {"LIBRARY_RELAY_ENABLED": "1", "LIBRARY_RELAY_MODE": "0",
       "LIBRARY_RELAY_CODES": "seongbuk,yeongdeungpo", "LIBRARY_RELAY_SECRET": SECRET,
       "LIBRARY_RELAY_URL": "https://offline-relay.vercel.app", "VERCEL_REGION": "icn1"}


def response(html, status=200):
    value = requests.Response()
    value.status_code = status
    value._content = html.encode("utf-8")
    value.encoding = "utf-8"
    value.headers["Content-Type"] = "text/html; charset=utf-8"
    return value


class StreamResponse:
    def __init__(self, body, status=200, headers=None, chunks=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def iter_content(self, chunk_size):
        if self.chunks is not None:
            yield from self.chunks
        else:
            for index in range(0, len(self.body), chunk_size):
                yield self.body[index:index + chunk_size]


def session_with(method, result):
    session = MagicMock()
    session.__enter__.return_value = session
    getattr(session, method).return_value = result
    return session


def payload(code="seongbuk", operation="kyobo_search", params=None):
    return {"version": 1, "library_code": code, "operation": operation,
            "params": params if params is not None else {"query": "검증", "field": "ctts", "limit": 10},
            "budget_ms": 4000}


def envelope(html):
    return {"version": 1, "ok": True, "upstream_status": 200,
            "content_type": "text/html; charset=utf-8",
            "body_base64": base64.b64encode(html.encode("utf-8")).decode("ascii"), "region": "icn1"}


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENV)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = library_relay_app.app.test_client()

    def signed_post(self, value=None, body=None, timestamp=None, signature=None, **kwargs):
        body = body if body is not None else json.dumps(value or payload(), ensure_ascii=False).encode()
        stamp = timestamp or str(int(time.time()))
        headers = {relay.TIMESTAMP_HEADER: stamp,
                   relay.SIGNATURE_HEADER: signature or relay.signature(stamp, body)}
        headers.update(kwargs.pop("headers", {}))
        return self.client.post(relay.RELAY_PATH, data=body, content_type="application/json", headers=headers, **kwargs)

    def test_health_and_isolated_route_map(self):
        self.assertEqual(self.client.get("/health").json, {"ok": True, "mode": "library-relay", "region": "icn1"})
        for url in ("/", "/api/live_search", "/api/shared_shelves", "/api/kyobo_status", "/static/js/search.js"):
            self.assertEqual(self.client.get(url).status_code, 404)
        check = subprocess.run([sys.executable, "-c", "import index,sys; assert 'app_search' not in sys.modules; assert 'db' not in sys.modules; assert len(list(index.app.url_map.iter_rules())) == 2"],
                               cwd=ROOT, env={**os.environ, "LIBRARY_RELAY_MODE": "1"}, capture_output=True)
        self.assertEqual(check.returncode, 0, check.stderr.decode())

    def test_auth_and_invalid_payload_never_fetch(self):
        with patch.object(library_relay_app, "fetch_upstream") as fetch:
            self.assertEqual(self.client.post(relay.RELAY_PATH, json=payload()).status_code, 401)
            self.assertEqual(self.signed_post(signature="0" * 64).status_code, 401)
            for delta in (-61, 61):
                self.assertEqual(self.signed_post(timestamp=str(int(time.time()) + delta)).status_code, 401)
            wrong = []
            for key, val in (("url", "http://127.0.0.1/"), ("headers", {}), ("cookie", "secret")):
                wrong.append({**payload(), key: val})
            for key, val in (("library_code", "gwanak"), ("library_code", {}), ("operation", "yes24_search"),
                             ("budget_ms", True), ("budget_ms", 4501), ("budget_ms", 0), ("version", True)):
                wrong.append({**payload(), key: val})
            wrong.extend([payload(params={"query": "x", "field": "ctts", "limit": True}),
                          payload(params={"query": "x\n", "field": "ctts", "limit": 1}),
                          payload(params={"query": "x" * 501, "field": "ctts", "limit": 1}),
                          payload(params={"query": "x", "field": "ctts", "limit": 1, "url": "x"}),
                          payload("yeongdeungpo", "yes24_detail", {"goods_id": "//localhost"})])
            for value in wrong:
                self.assertEqual(self.signed_post(value).status_code, 400)
            for raw in (b"{", b'{"version":1,"version":1}', b'[]'):
                self.assertEqual(self.signed_post(body=raw).status_code, 400)
            self.assertEqual(self.signed_post(body=b"x" * (relay.MAX_REQUEST_BYTES + 1)).status_code, 413)
            self.assertEqual(self.signed_post(query_string={"url": "x"}).status_code, 400)
            fetch.assert_not_called()

    def test_fixed_recipes(self):
        cases = [payload(), payload("seongbuk", "kyobo_detail", {"brcd": "123", "ctts_dvsn_code": "001", "ctgr_id": "", "sntn_auth_code": ""})]
        for code in ("yeongdeungpo", "songpa_owned", "gangseo"):
            cases.extend([payload(code, "yes24_search", {"query": "https://127.0.0.1/?next=x", "field": "total"}),
                          payload(code, "yes24_detail", {"goods_id": "123"}), payload(code, "yes24_list", {})])
        for case in cases:
            url, headers = relay.page_recipe(case)
            self.assertTrue(url.startswith(relay.ORIGINS[case["library_code"]] + "/"))
            self.assertEqual(headers["Referer"], relay.ORIGINS[case["library_code"]])
            self.assertNotIn("Cookie", headers)
        for op in ("kyobo_search", "kyobo_detail"):
            with self.assertRaises(relay.RelayError):
                relay.page_recipe(payload("yeongdeungpo", op))

    def test_upstream_bounded_and_no_header_forwarding(self):
        upstream = session_with("get", StreamResponse(KYOBO_RESULT.encode()))
        with patch.object(relay, "make_session", return_value=upstream):
            result = self.signed_post(headers={"Authorization": "CANARY", "Cookie": "CANARY"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(base64.b64decode(result.json["body_base64"]).decode(), KYOBO_RESULT)
        options = upstream.get.call_args.kwargs
        self.assertFalse(options["allow_redirects"])
        self.assertFalse(options["verify"])
        self.assertNotIn("Authorization", options["headers"])
        self.assertNotIn("Cookie", options["headers"])
        self.assertLessEqual(options["timeout"].total, 4)

    def test_upstream_errors_size_and_timeout(self):
        cases = [(StreamResponse(b"", 302), "redirect"), (StreamResponse(b"", 429), "upstream_http"),
                 (StreamResponse(b"{}", headers={"Content-Type": "application/json"}), "invalid_document"),
                 (StreamResponse(b"<html>truncated"), "invalid_document"),
                 (StreamResponse(b"", headers={"Content-Type": "text/html", "Content-Length": str(relay.MAX_PAGE_BYTES + 1)}), "body_too_large"),
                 (StreamResponse(b"", chunks=[b"x" * relay.MAX_PAGE_BYTES, b"x"]), "body_too_large")]
        for upstream_response, expected in cases:
            with patch.object(relay, "make_session", return_value=session_with("get", upstream_response)):
                value = self.signed_post()
            self.assertEqual(value.status_code, 502)
            self.assertEqual(value.json["error"], expected)
        failing = session_with("get", None)
        failing.get.side_effect = requests.Timeout("SECRET-CANARY")
        with patch.object(relay, "make_session", return_value=failing):
            value = self.signed_post()
        self.assertEqual(value.status_code, 504)
        self.assertNotIn("SECRET-CANARY", value.get_data(as_text=True))
        with patch.object(relay.time, "monotonic", side_effect=[0, 0, 5]):
            with patch.object(relay, "make_session", return_value=session_with("get", StreamResponse(KYOBO_RESULT.encode()))):
                with self.assertRaises(relay.RelayError):
                    relay.fetch_upstream(payload())

    def test_client_preserves_bytes_and_uses_verified_tls(self):
        remote = session_with("post", StreamResponse(json.dumps(envelope(YES24_RESULT)).encode()))
        with patch.object(relay.requests, "Session", return_value=remote):
            value = relay.fetch_page("yeongdeungpo", "yes24_search", {"query": "검증", "field": "total"}, relay.operation_deadline(4.5))
        self.assertEqual(value.content, YES24_RESULT.encode())
        self.assertEqual(value.text, YES24_RESULT)
        options = remote.post.call_args.kwargs
        self.assertTrue(options["verify"])
        self.assertFalse(options["allow_redirects"])
        self.assertFalse(remote.trust_env)
        self.assertLessEqual(options["timeout"].total, 4.5)
        self.assertTrue(relay.authenticated(options["headers"][relay.TIMESTAMP_HEADER], options["headers"][relay.SIGNATURE_HEADER], options["data"]))
        self.assertLess(json.loads(options["data"])["budget_ms"], 4500)

    def test_client_url_errors_and_deadlines_fail_closed(self):
        for url in ("http://x.vercel.app", "https://localhost", "https://x.vercel.app.evil", "https://u@x.vercel.app", "https://x.vercel.app:443", "https://x.vercel.app/path", "https://x.vercel.app?q=x"):
            with patch.dict(os.environ, {"LIBRARY_RELAY_URL": url}), patch.object(relay.requests, "Session") as session:
                with self.assertRaises(relay.RelayError):
                    relay.fetch_page("seongbuk", "kyobo_search", payload()["params"], relay.operation_deadline(4.5))
                session.assert_not_called()
        with patch.object(relay.requests, "Session") as session:
            with self.assertRaises(relay.RelayError):
                relay.fetch_page("seongbuk", "kyobo_search", payload()["params"], time.monotonic() - 1)
            session.assert_not_called()
        for data in (b"not json CANARY", json.dumps({**envelope(KYOBO_RESULT), "body_base64": "CANARY!!!"}).encode(), json.dumps({**envelope(KYOBO_RESULT), "url": "CANARY"}).encode()):
            with patch.object(relay.requests, "Session", return_value=session_with("post", StreamResponse(data))):
                with self.assertRaises(relay.RelayError) as error:
                    relay.fetch_page("seongbuk", "kyobo_search", payload()["params"], relay.operation_deadline(4.5))
                self.assertNotIn("CANARY", str(error.exception))

    def test_flag_disabled_and_other_libraries_preserve_direct_path(self):
        for code in LIBRARIES:
            if code not in ("seongbuk", "yeongdeungpo"):
                self.assertFalse(relay.relay_enabled(code))
        with patch.dict(os.environ, {"LIBRARY_RELAY_MODE": "1"}):
            self.assertFalse(relay.relay_enabled("seongbuk"))
        for code, connector, fixture, enabled in (("seongbuk", KyoboNewConnector(), KYOBO_RESULT, "0"), ("yeongdeungpo", Yes24Connector(), YES24_RESULT, "0"), ("yongsan", KyoboNewConnector(), KYOBO_RESULT, "1"), ("songpa_owned", Yes24Connector(), YES24_RESULT, "1")):
            target = "live_search.connectors.kyobo" if isinstance(connector, KyoboNewConnector) else "live_search.connectors.yes24"
            direct = MagicMock()
            direct.get.return_value = response(fixture)
            session_target = patch.object(connector, "_session", return_value=direct) if isinstance(connector, KyoboNewConnector) else patch(target + ".make_session", return_value=direct)
            with patch.dict(os.environ, {"LIBRARY_RELAY_ENABLED": enabled}), session_target, patch(target + ".fetch_page") as remote:
                results = connector.search_library(code, LIBRARIES[code], "검증", "title", 10, 2.5)
                self.assertEqual(len(results), 1)
                self.assertEqual(direct.get.call_args.kwargs["timeout"], 2.5)
                self.assertFalse(direct.get.call_args.kwargs["verify"])
                remote.assert_not_called()

    def test_remote_search_success_zero_and_failure_documents(self):
        for code, connector, good, zero in (("seongbuk", KyoboNewConnector(), KYOBO_RESULT, KYOBO_ZERO), ("yeongdeungpo", Yes24Connector(), YES24_RESULT, YES24_ZERO)):
            target = "live_search.connectors.kyobo" if code == "seongbuk" else "live_search.connectors.yes24"
            for fixture, length in ((good, 1), (zero, 0)):
                with patch(target + ".fetch_page", return_value=response(fixture)):
                    self.assertEqual(len(connector.search_library(code, LIBRARIES[code], "검증", "title", 10, 4.5)), length)
            for fixture in ("<html><body>로그인이 필요합니다.</body></html>", "<html><body>Access denied</body></html>", good.replace("</html>", ""), zero.replace("0</em>", "5</em>") if code != "seongbuk" else "<html><body>no results</body></html>"):
                with patch(target + ".fetch_page", return_value=response(fixture)):
                    with self.assertRaises(relay.RelayError):
                        connector.search_library(code, LIBRARIES[code], "검증", "title", 10, 4.5)
        with patch("live_search.connectors.kyobo.fetch_page", return_value=response(KYOBO_ZERO)) as fetch:
            KyoboNewConnector().search_library("seongbuk", LIBRARIES["seongbuk"], "검증", "title_author", 10, 4.5)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args_list[0].args[-1], fetch.call_args_list[1].args[-1])

    def test_yes24_status_matches_requested_book_and_explicit_counts(self):
        from adapters.status_parsers import parse_yes24_status
        wrong = '<div class="bx"><a href="/ebook/detail?goods_id=99999">다른 책</a>' + YES24_STAT.replace('3</strong>', '9</strong>') + '</div>'
        multiple = YES24_STATUS_LIST.replace('<div class="ebook-list">', '<div class="ebook-list">' + wrong)
        html = relay.yes24_status_html(response(multiple), "yes24_list", "12345")
        self.assertEqual(parse_yes24_status(html, "12345"), {"owned": 3, "loaned": 1, "reserved": 2})
        for fixture, operation, goods_id in (
            (multiple, "yes24_list", "1234"),  # substring is not an ID match
            (multiple, "yes24_list", "88888"),  # missing real book
            (YES24_STATUS.replace("12345", "99999"), "yes24_detail", "12345"),
            (YES24_STATUS.replace(YES24_STAT, '<div class="stat"></div>'), "yes24_detail", "12345"),
            (YES24_STATUS.replace('예약<strong>2</strong>', '예약 대기 2'), "yes24_detail", "12345"),
            (YES24_STATUS.replace('보유<strong>3</strong>', '보유<strong> 3 </strong>'), "yes24_detail", "12345"),
            (YES24_STATUS.replace('보유<strong>3</strong>', '누적대출<strong>3</strong>'), "yes24_detail", "12345"),
            ('<html><body>로그인' + YES24_STAT + '</body></html>', "yes24_detail", "12345"),
        ):
            with self.assertRaises(relay.RelayError):
                relay.yes24_status_html(response(fixture), operation, goods_id)
        zero = YES24_STATUS.replace('3</strong>', '0</strong>').replace('1</strong>', '0</strong>').replace('2</strong>', '0</strong>')
        self.assertEqual(parse_yes24_status(relay.yes24_status_html(response(zero), "yes24_detail", "12345"), "12345"),
                         {"owned": 0, "loaned": 0, "reserved": 0})
        status_api_routes.STATUS_CACHE.clear()
        app = Flask("missing-status-regression")
        app.register_blueprint(status_api_routes.status_api_bp)
        with patch.object(status_api_routes, "fetch_page", return_value=response(multiple)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(app.test_client().get("/api/yes24_status?library_code=yeongdeungpo&goods_id=88888").status_code, 502)
        status_api_routes.STATUS_CACHE.clear()


    def test_status_cache_and_shared_fallback_deadline(self):
        app = Flask("relay-status-tests")
        app.register_blueprint(status_api_routes.status_api_bp)
        client = app.test_client()
        status_api_routes.STATUS_CACHE.clear()
        with patch.object(status_api_routes, "fetch_page", return_value=response(KYOBO_STATUS)) as fetch:
            url = "/api/kyobo_status?library_code=seongbuk&brcd=12345&ctts_dvsn_code=001&ctgr_id=1101"
            self.assertEqual(client.get(url).json["status"], {"loaned": 1, "total": 3, "reserved": 2})
            self.assertEqual(client.get(url).status_code, 200)
            self.assertEqual(fetch.call_count, 1)
        status_api_routes.STATUS_CACHE.clear()
        with patch.object(status_api_routes, "fetch_page", side_effect=[response("<html></html>"), response(YES24_STATUS_LIST)]) as fetch, contextlib.redirect_stdout(io.StringIO()):
            value = client.get("/api/yes24_status?library_code=yeongdeungpo&goods_id=12345")
            self.assertEqual(value.status_code, 200)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args_list[0].args[-1], fetch.call_args_list[1].args[-1])
        status_api_routes.STATUS_CACHE.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out), patch.object(status_api_routes, "fetch_page", side_effect=requests.RequestException("CANARY-QUERY-SECRET")):
            for _ in range(2):
                value = client.get("/api/yes24_status?library_code=yeongdeungpo&goods_id=12345")
                self.assertEqual(value.status_code, 502)
        self.assertNotIn("CANARY", out.getvalue())
        status_api_routes.STATUS_CACHE.clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
