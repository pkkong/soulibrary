"""Offline regressions for book-specific loan counts and author identity."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))

import requests
from flask import Flask, template_rendered

from adapters.status_parsers import (
    parse_bookcube_detail_status, parse_bookcube_status, parse_gangnam_detail_status,
    parse_gangnam_status, parse_seoul_status, parse_sen_status, parse_sen_xml_status,
    parse_yes24_status,
)
from live_search.connectors.yes24 import Yes24Connector
from live_search.models import LiveSearchResult
from live_search.normalizer import clean_author_display, merge_live_results, normalize_author, result_group_key
from live_search.relay import RelayError, yes24_status_html
import status_api_routes


def stat(owned=3, loaned=1, reserved=2):
    return (f'<div class="stat clearfix"><ul><li>보유 <strong>{owned}</strong></li>'
            f'<li>대출 <strong>{loaned}</strong></li><li>예약 <strong>{reserved}</strong></li></ul></div>')


def book(goods_id="222", counts=None):
    return (f'<div class="bx clearfix"><a href="/ebook/detail/?goods_id={goods_id}">검증 도서</a>'
            + (stat() if counts is None else counts) + '</div>')


def listing(*books):
    return '<html><body><div class="ebook-list">' + ''.join(books) + '</div></body></html>'


def detail(goods_id="222", counts=None):
    return ('<html><body><div class="ebook-wrap ebook-view"><div class="top">'
            + (stat() if counts is None else counts) + '</div></div>'
            + f'<input name="return_url" value="/ebook/detail/?goods_id={goods_id}"></body></html>')


def response(document, status=200):
    value = requests.Response()
    value.status_code = status
    value._content = document.encode("utf-8")
    value.encoding = "utf-8"
    value.headers["Content-Type"] = "text/html; charset=utf-8"
    return value


class Yes24IdentityTests(unittest.TestCase):
    def test_selects_requested_book_instead_of_first_status(self):
        document = listing(book("111", stat(9, 8, 7)), book())
        self.assertEqual(parse_yes24_status(document, "222"), {"owned": 3, "loaned": 1, "reserved": 2})
        self.assertEqual(parse_yes24_status(document, "111"), {"owned": 9, "loaned": 8, "reserved": 7})

    def test_missing_and_prefix_ids_are_not_matches(self):
        document = listing(book("2220", stat(9, 8, 7)))
        for goods_id in ("222", "22", "111", "", None, 222):
            with self.subTest(goods_id=goods_id):
                self.assertIsNone(parse_yes24_status(document, goods_id))
        self.assertIsNone(parse_yes24_status(listing(book("222&goods_id=111")), "222"))

    def test_unidentified_status_fragment_cannot_claim_any_book(self):
        self.assertIsNone(parse_yes24_status(stat(), "222"))
        self.assertIsNone(parse_yes24_status('<html><body>로그인' + stat() + '</body></html>', "222"))

    def test_duplicate_books_and_conflicting_detail_identity_fail(self):
        self.assertIsNone(parse_yes24_status(listing(book(), book()), "222"))
        self.assertIsNone(parse_yes24_status(detail("111"), "222"))
        conflicting = detail().replace('</body>', '<input name="return_url" value="/ebook/detail/?goods_id=111"></body>')
        self.assertIsNone(parse_yes24_status(conflicting, "222"))

    def test_nested_books_do_not_lend_their_identity_or_status_to_parent(self):
        document = listing(book("111", stat(9, 8, 7) + book()))
        self.assertEqual(parse_yes24_status(document, "222"), {"owned": 3, "loaned": 1, "reserved": 2})
        self.assertEqual(parse_yes24_status(document, "111"), {"owned": 9, "loaned": 8, "reserved": 7})
        self.assertIsNone(parse_yes24_status(listing(book("111", book())), "111"))

    def test_all_counts_are_required_and_ambiguous_stats_fail(self):
        invalid = (
            '<div class="stat"></div>',
            stat().replace('예약 <strong>2</strong>', '예약 대기 2'),
            stat().replace('보유 <strong>3</strong>', '누적대출 <strong>3</strong>'),
            stat().replace('<strong>3</strong>', '<strong> 3 </strong>'),
            stat().replace('<strong>3</strong>', '<strong>-3</strong>'),
            stat().replace('</ul>', '<li>보유 <strong>9</strong></li></ul>'),
            stat() + stat(9, 8, 7),
        )
        for counts in invalid:
            with self.subTest(counts=counts):
                self.assertIsNone(parse_yes24_status(detail(counts=counts), "222"))
                self.assertIsNone(parse_yes24_status(listing(book(counts=counts)), "222"))

    def test_explicit_zero_is_a_valid_status(self):
        for document in (detail(counts=stat(0, 0, 0)), listing(book(counts=stat(0, 0, 0)))):
            self.assertEqual(parse_yes24_status(document, "222"), {"owned": 0, "loaned": 0, "reserved": 0})

    def test_nested_label_markup_and_comments_preserve_counts(self):
        counts = stat().replace('보유 <strong>3</strong>', '<span>보유</span> <strong><em>3</em></strong>')
        counts = counts.replace('</ul>', '<!-- <li>보유 <strong>9</strong></li> --></ul>')
        self.assertEqual(parse_yes24_status(detail(counts=counts), "222"), {"owned": 3, "loaned": 1, "reserved": 2})

    def test_detail_recommendations_cannot_supply_missing_counts(self):
        document = detail(counts=book("111", stat(9, 8, 7)))
        self.assertIsNone(parse_yes24_status(document, "222"))
        document = detail(counts=stat() + book("111", stat(9, 8, 7)))
        self.assertEqual(parse_yes24_status(document, "222"), {"owned": 3, "loaned": 1, "reserved": 2})

    def test_operation_contract_and_shared_helper_retain_identity(self):
        for document, operation in ((detail(), "yes24_detail"), (listing(book()), "yes24_list")):
            checked = yes24_status_html(response(document), operation, "222")
            self.assertIn('goods_id=222', checked)
            self.assertEqual(parse_yes24_status(checked, "222"), {"owned": 3, "loaned": 1, "reserved": 2})
        for document, operation in ((listing(book()), "yes24_detail"), (detail(), "yes24_list")):
            with self.assertRaises(RelayError):
                yes24_status_html(response(document), operation, "222")


class Yes24RouteTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"LIBRARY_RELAY_ENABLED": "0"})
        self.env.start()
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("Offline test attempted network"))
        self.network.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.network.stop)
        self.addCleanup(status_api_routes.STATUS_CACHE.clear)
        status_api_routes.STATUS_CACHE.clear()
        app = Flask("search-integrity-tests")
        app.register_blueprint(status_api_routes.status_api_bp)
        self.client = app.test_client()
        self.session = MagicMock()
        self.transport = patch.object(status_api_routes, "get_status_session", return_value=self.session)
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def get(self, code="gwanak"):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.client.get(f"/api/yes24_status?library_code={code}&goods_id=222")

    def test_direct_wrong_fallback_returns_failure_and_is_never_cached(self):
        self.session.get.side_effect = [response('', 404), response(listing(book("111", stat(9, 8, 7))))] * 2
        for _ in range(2):
            value = self.get()
            self.assertEqual(value.status_code, 502)
            self.assertIsNone(value.json["status"])
            self.assertIsNone(status_api_routes.STATUS_CACHE.get("yes24:gwanak:222"))
        self.assertEqual(self.session.get.call_count, 4)

    def test_direct_correct_fallback_succeeds_and_caches_only_requested_book(self):
        self.session.get.side_effect = [response(detail("111", stat(9, 8, 7))),
                                        response(listing(book("111", stat(9, 8, 7)), book()))]
        value = self.get()
        self.assertEqual(value.status_code, 200)
        self.assertEqual(value.json["status"], {"owned": 3, "loaned": 1, "reserved": 2})
        self.assertEqual(self.get().json, value.json)
        self.assertEqual(self.session.get.call_count, 2)

    def test_direct_detail_success_and_zero_are_cached_across_yes24_libraries(self):
        for code in ("gwanak", "gangdong_owned", "jongno"):
            for counts, expected in ((stat(), {"owned": 3, "loaned": 1, "reserved": 2}),
                                     (stat(0, 0, 0), {"owned": 0, "loaned": 0, "reserved": 0})):
                with self.subTest(code=code, counts=counts):
                    status_api_routes.STATUS_CACHE.clear()
                    self.session.get.reset_mock()
                    self.session.get.return_value = response(detail(counts=counts))
                    value = self.get(code)
                    self.assertEqual(value.status_code, 200)
                    self.assertEqual(value.json["status"], expected)
                    self.assertEqual(self.get(code).json, value.json)
                    self.assertEqual(self.session.get.call_count, 1)

    def test_direct_missing_numeric_counts_fail_without_cache(self):
        bad_counts = '<div class="stat"><ul><li>보유</li><li>대출</li><li>예약</li></ul></div>'
        self.session.get.side_effect = [response(detail(counts=bad_counts)), response(listing(book(counts=bad_counts)))]
        value = self.get()
        self.assertEqual(value.status_code, 502)
        self.assertIsNone(value.json["status"])
        self.assertIsNone(status_api_routes.STATUS_CACHE.get("yes24:gwanak:222"))


# Minimal structures verified against the public sites on 2026-10-20. Keep only
# book identity and current counts; no descriptions, account fields, or loan IDs.
def cube_counts(loaned=1, total=3, reserved=2, kind="i2"):
    return f'<ul class="{kind}"><li><p>대출</p>{loaned}/{total}</li><li><p>예약</p>{reserved}</li><li>누적대출 99</li></ul>'


def cube_card(content_id="222", counts=None):
    return (f'<li class="item"><div class="subject"><a href="javascript:goView(\'{content_id}\',\'\',\'book\',\'N\');">검증 도서</a></div>'
            + (cube_counts() if counts is None else counts) + '</li>')


def cube_list(*cards):
    return '<html><body><ul id="detail_list" class="list typelist">' + ''.join(cards) + '</ul></body></html>'


def cube_detail(content_id="222", counts=None):
    return ('<html><body><div class="book_view"><div class="detail_info">'
            + (cube_counts(kind="state") if counts is None else counts) + '</div></div>'
            + f'<input type="hidden" name="book_num" value="{content_id}"></body></html>')


def gangnam_counts(owned=3, loaned=1, reserved=2):
    return (f'<div class="current"><span>보유 <strong>{owned}</strong></span>'
            f'<span>대출 <strong>{loaned}</strong></span><span>예약 <strong>{reserved}</strong></span></div>')


def gangnam_card(content_id="222", counts=None):
    return (f'<div class="book"><div class="list_info"><div class="book_title"><a href="book_detail.asp?book_num={content_id}">검증 도서</a></div>'
            + (gangnam_counts() if counts is None else counts) + '</div></div>')


def gangnam_list(*cards):
    return '<html><body><div class="contents book"><div class="book_list_body catalog">' + ''.join(cards) + '</div></div></body></html>'


def gangnam_detail(content_id="222", counts=None):
    return ('<html><body><div class="book_warp"><div class="book_info">'
            + (gangnam_counts() if counts is None else counts) + '</div></div>'
            + f'<input type="hidden" name="book_num" value="{content_id}"></body></html>')


def content_record(content_id="222", loaned=1, total=3, reserved=2):
    return {"contentsKey": content_id, "currentLoanCount": loaned, "contentsCopys": total, "currentResvCount": reserved}


def xml_record(content_id="222", loaned=1, total=3, reserved=2):
    return (f'<Contents><contentsKey>{content_id}</contentsKey><currentLoanCount>{loaned}</currentLoanCount>'
            f'<contentsCopys>{total}</contentsCopys><currentResvCount>{reserved}</currentResvCount></Contents>')


def xml_document(*records):
    return '<Map>' + ''.join(records) + '</Map>'


def api_response(value, content_type="application/json"):
    result = response(json.dumps(value) if not isinstance(value, str) else value)
    result.headers["Content-Type"] = content_type
    return result


def gangnam_response(document):
    result = response(document)
    result._content = document.encode("euc-kr")
    result.encoding = "euc-kr"
    return result


class BookcubeIdentityTests(unittest.TestCase):
    def test_list_uses_exact_card_identity_and_ignores_grid_copy(self):
        document = cube_list(cube_card("2220", cube_counts(8, 9, 7)), cube_card())
        document = document.replace('</body>', '<ul id="grid_list">' + cube_card(counts="") + '</ul></body>')
        self.assertEqual(parse_bookcube_status(document, "222"), {"loaned": 1, "total": 3, "reserved": 2})
        self.assertIsNone(parse_bookcube_status(cube_list(cube_card("2220")), "222"))

    def test_id_in_text_or_nearby_book_cannot_supply_counts(self):
        self.assertIsNone(parse_bookcube_status(cube_list(cube_card("111", cube_counts() + '222')), "222"))
        self.assertIsNone(parse_bookcube_status(cube_list(cube_card("111"), cube_card(counts="")), "222"))
        self.assertIsNone(parse_bookcube_status('<html><body>222' + cube_counts() + '</body></html>', "222"))

    def test_duplicate_cards_and_conflicting_links_are_ambiguous(self):
        self.assertIsNone(parse_bookcube_status(cube_list(cube_card(), cube_card()), "222"))
        conflicting = cube_card().replace('</li>', '<a href="/FxLibrary/product/view/?num=111">다른 책</a></li>', 1)
        self.assertIsNone(parse_bookcube_status(cube_list(conflicting), "222"))
        ambiguous = cube_card().replace("javascript:goView('222','','book','N');", "/FxLibrary/product/view/?num=222&amp;num=111")
        self.assertIsNone(parse_bookcube_status(cube_list(ambiguous), "222"))

    def test_detail_requires_matching_hidden_identity_and_own_state(self):
        self.assertEqual(parse_bookcube_detail_status(cube_detail(), "222"), {"loaned": 1, "total": 3, "reserved": 2})
        for document in (cube_detail("2220"), cube_detail().replace('name="book_num"', 'name="other"'), cube_counts(kind="state")):
            self.assertIsNone(parse_bookcube_detail_status(document, "222"))
        self.assertIsNone(parse_bookcube_detail_status(cube_detail().replace('</body>', '<input name="book_num" value="111"></body>'), "222"))
        self.assertIsNone(parse_bookcube_detail_status(cube_detail(counts=cube_card("111", cube_counts(kind="state"))), "222"))
        repeated = cube_detail().replace('</body>', '<input name="book_num" value="222"></body>')
        self.assertEqual(parse_bookcube_detail_status(repeated, "222"), {"loaned": 1, "total": 3, "reserved": 2})

    def test_missing_invalid_and_duplicate_counts_fail_but_explicit_zero_succeeds(self):
        invalid = (cube_counts(reserved=""), cube_counts(reserved=-1), cube_counts(total="1,2"),
                   cube_counts(loaned="oops"), cube_counts().replace('</ul>', '<li>예약 9</li></ul>'),
                   cube_counts() + cube_counts())
        for counts in invalid:
            with self.subTest(counts=counts):
                self.assertIsNone(parse_bookcube_status(cube_list(cube_card(counts=counts)), "222"))
                self.assertIsNone(parse_bookcube_detail_status(cube_detail(counts=counts.replace('class="i2"', 'class="state"')), "222"))
        self.assertEqual(parse_bookcube_detail_status(cube_detail(counts=cube_counts(0, 0, 0, "state")), "222"), {"loaned": 0, "total": 0, "reserved": 0})
        self.assertEqual(parse_bookcube_status(cube_list(cube_card(counts=cube_counts(0, 0, 0))), "222"), {"loaned": 0, "total": 0, "reserved": 0})


class GangnamIdentityTests(unittest.TestCase):
    def test_list_selects_requested_book_instead_of_prefix_or_parent(self):
        document = gangnam_list(gangnam_card("2220", gangnam_counts(9, 8, 7)), gangnam_card())
        self.assertEqual(parse_gangnam_status(document, "222"), {"owned": 3, "loaned": 1, "reserved": 2})
        self.assertIsNone(parse_gangnam_status(gangnam_list(gangnam_card("2220")), "222"))
        self.assertIsNone(parse_gangnam_status(gangnam_list(gangnam_card("111"), gangnam_card(counts="")), "222"))

    def test_detail_requires_matching_identity_and_ignores_due_date_numbers(self):
        counts = gangnam_counts().replace('<div class="current">', '<div class="current"><span>대출예정일 <span><strong>2026-11-13</strong></span>')
        self.assertEqual(parse_gangnam_detail_status(gangnam_detail(counts=counts), "222"), {"owned": 3, "loaned": 1, "reserved": 2})
        for document in (gangnam_detail("2220"), gangnam_detail().replace('name="book_num"', 'name="other"'), '보유 3 대출 1 예약 2'):
            self.assertIsNone(parse_gangnam_detail_status(document, "222"))
        self.assertIsNone(parse_gangnam_detail_status(gangnam_detail(counts=gangnam_card("111")), "222"))
        repeated = gangnam_detail().replace('</body>', '<input name="book_num" value="222"></body>')
        self.assertEqual(parse_gangnam_detail_status(repeated, "222"), {"owned": 3, "loaned": 1, "reserved": 2})
        self.assertIsNone(parse_gangnam_detail_status(repeated.replace('value="222"', 'value="111"', 1), "222"))

    def test_duplicates_conflicting_identity_and_partial_numbers_fail(self):
        self.assertIsNone(parse_gangnam_status(gangnam_list(gangnam_card(), gangnam_card()), "222"))
        conflicting = gangnam_card().replace('</a>', '</a><a href="book_detail.asp?book_num=111">다른 책</a>', 1)
        self.assertIsNone(parse_gangnam_status(gangnam_list(conflicting), "222"))
        for counts in (gangnam_counts(reserved=""), gangnam_counts(owned=-1), gangnam_counts(loaned="1.0"),
                       gangnam_counts().replace('</div>', '<span>보유 <strong>9</strong></span></div>'), gangnam_counts() + gangnam_counts()):
            with self.subTest(counts=counts):
                self.assertIsNone(parse_gangnam_status(gangnam_list(gangnam_card(counts=counts)), "222"))
                self.assertIsNone(parse_gangnam_detail_status(gangnam_detail(counts=counts), "222"))

    def test_explicit_zero_is_valid(self):
        expected = {"owned": 0, "loaned": 0, "reserved": 0}
        self.assertEqual(parse_gangnam_status(gangnam_list(gangnam_card(counts=gangnam_counts(0, 0, 0))), "222"), expected)
        self.assertEqual(parse_gangnam_detail_status(gangnam_detail(counts=gangnam_counts(0, 0, 0)), "222"), expected)


class PublicApiIdentityTests(unittest.TestCase):
    def test_json_selects_requested_record_instead_of_first_and_supports_dict(self):
        expected = {"loaned": 1, "total": 3, "reserved": 2}
        for parse in (parse_seoul_status, parse_sen_status):
            self.assertEqual(parse({"Contents": [content_record("111", 8, 9, 7), content_record()]}, "222"), expected)
            self.assertEqual(parse({"Contents": content_record()}, "222"), expected)

    def test_json_missing_wrong_duplicate_ids_and_empty_contents_are_failures(self):
        without_id = content_record(); without_id.pop("contentsKey")
        for parse in (parse_seoul_status, parse_sen_status):
            for data in ({"Contents": {}}, {"Contents": []}, {"Contents": content_record("2220")},
                         {"Contents": without_id}, {"Contents": [content_record(), content_record()]}, content_record()):
                with self.subTest(parse=parse.__name__, data=data):
                    self.assertIsNone(parse(data, "222"))

    def test_json_all_counts_must_be_explicit_integers(self):
        for parse in (parse_seoul_status, parse_sen_status):
            for key in ("currentLoanCount", "contentsCopys", "currentResvCount"):
                for value in (None, "", -1, True, False, 1.5, "1.0", "-1", "1,2", [], {}):
                    record = content_record(); record[key] = value
                    with self.subTest(parse=parse.__name__, key=key, value=value):
                        self.assertIsNone(parse({"Contents": record}, "222"))
                record = content_record(); record.pop(key)
                self.assertIsNone(parse({"Contents": record}, "222"))
            self.assertEqual(parse({"Contents": content_record(loaned=0, total="0", reserved=0)}, "222"), {"loaned": 0, "total": 0, "reserved": 0})

    def test_xml_uses_same_record_for_id_and_all_counts(self):
        self.assertEqual(parse_sen_xml_status(xml_document(xml_record("111", 8, 9, 7), xml_record()), "222"), {"loaned": 1, "total": 3, "reserved": 2})
        self.assertEqual(parse_sen_xml_status(xml_document(xml_record(loaned=0, total=0, reserved=0)), "222"), {"loaned": 0, "total": 0, "reserved": 0})
        for document in (xml_document(xml_record("2220")), xml_document(xml_record(), xml_record()),
                         xml_document(xml_record().replace('<contentsKey>222</contentsKey>', '')),
                         xml_document(xml_record().replace('<currentResvCount>2</currentResvCount>', '')),
                         xml_document(xml_record().replace('</Contents>', '<contentsCopys>9</contentsCopys></Contents>')),
                         xml_document(xml_record().replace('</Contents>', '<contentsKey>222</contentsKey></Contents>')),
                         xml_document(xml_record(loaned=-1)), xml_document(xml_record(total="1.0")),
                         '<Map><Contents><contentsKey>222</contentsKey></Contents><currentLoanCount>1</currentLoanCount><contentsCopys>3</contentsCopys><currentResvCount>2</currentResvCount></Map>',
                         '<!DOCTYPE Map [<!ENTITY id "222">]><Map><Contents><contentsKey>&id;</contentsKey></Contents></Map>'):
            with self.subTest(document=document):
                self.assertIsNone(parse_sen_xml_status(document, "222"))


class OtherStatusRouteTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("requests.sessions.Session.request", side_effect=AssertionError("Offline test attempted network"))
        self.network.start(); self.addCleanup(self.network.stop)
        self.addCleanup(status_api_routes.STATUS_CACHE.clear)
        status_api_routes.STATUS_CACHE.clear()
        app = Flask("other-status-integrity-tests"); app.register_blueprint(status_api_routes.status_api_bp)
        self.client = app.test_client(); self.session = MagicMock()
        self.transport = patch.object(status_api_routes, "get_status_session", return_value=self.session)
        self.transport.start(); self.addCleanup(self.transport.stop)

    def get(self, route):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.client.get(route)

    def test_wrong_detail_and_fallback_never_cache_another_book(self):
        cases = (
            ("/api/bookcube_status?library_code=geumcheon&content_id=222", "bookcube:geumcheon:222", cube_detail("111"), cube_list(cube_card("2220", cube_counts(8, 9, 7)))),
            ("/api/gangnam_status?library_code=gangnam&content_id=222", "gangnam:gangnam:222", gangnam_detail("111"), gangnam_list(gangnam_card("2220", gangnam_counts(9, 8, 7)))),
        )
        for route, key, wrong_detail, wrong_list in cases:
            with self.subTest(route=route):
                self.session.get.reset_mock()
                encode = gangnam_response if route.startswith('/api/gangnam_status') else response
                self.session.get.side_effect = [encode(wrong_detail), encode(wrong_list)] * 2
                for _ in range(2):
                    self.assertEqual(self.get(route).status_code, 502)
                    self.assertIsNone(status_api_routes.STATUS_CACHE.get(key))
                self.assertEqual(self.session.get.call_count, 4)

    def test_correct_requested_fallback_is_cached(self):
        for route, key, bad, good, expected in (
            ("/api/bookcube_status?library_code=geumcheon&content_id=222", "bookcube:geumcheon:222", cube_detail("111"), cube_list(cube_card("111"), cube_card()), {"loaned": 1, "total": 3, "reserved": 2}),
            ("/api/gangnam_status?library_code=gangnam&content_id=222", "gangnam:gangnam:222", gangnam_detail("111"), gangnam_list(gangnam_card("111"), gangnam_card()), {"owned": 3, "loaned": 1, "reserved": 2}),
        ):
            with self.subTest(route=route):
                encode = gangnam_response if route.startswith('/api/gangnam_status') else response
                self.session.get.reset_mock(); self.session.get.side_effect = [encode(bad), encode(good)]
                value = self.get(route)
                self.assertEqual(value.status_code, 200); self.assertEqual(value.json["status"], expected)
                self.assertEqual(self.get(route).json, value.json); self.assertEqual(self.session.get.call_count, 2)

    def test_public_api_wrong_missing_or_duplicate_record_is_failure_not_cached_zero(self):
        for route, key in (("/api/seoul_status?content_id=222", "seoul:222"), ("/api/sen_status?library_code=sen_owned&content_id=222", "sen:sen_owned:222")):
            for data in ({"Contents": {}}, {"Contents": content_record("2220")}, {"Contents": [content_record(), content_record()]}, {"Contents": {"contentsKey": "222"}}):
                with self.subTest(route=route, data=data):
                    self.session.get.reset_mock(); self.session.get.side_effect = None; self.session.get.return_value = api_response(data)
                    for _ in range(2):
                        value = self.get(route); self.assertEqual(value.status_code, 502); self.assertIsNone(value.json["status"])
                        self.assertIsNone(status_api_routes.STATUS_CACHE.get(key))
                    self.assertEqual(self.session.get.call_count, 2)

    def test_duplicate_json_fields_and_invalid_xml_counts_do_not_cache(self):
        duplicate = '{"Contents":{"contentsKey":"222","contentsCopys":3,"contentsCopys":9,"currentLoanCount":1,"currentResvCount":2}}'
        for route, key in (("/api/seoul_status?content_id=222", "seoul:222"), ("/api/sen_status?library_code=sen_owned&content_id=222", "sen:sen_owned:222")):
            self.session.get.return_value = api_response(duplicate)
            self.assertEqual(self.get(route).status_code, 502); self.assertIsNone(status_api_routes.STATUS_CACHE.get(key))
        self.session.get.return_value = api_response(xml_document(xml_record(reserved="")), "application/xhtml+xml")
        self.assertEqual(self.get('/api/sen_status?library_code=sen_owned&content_id=222').status_code, 502)
        self.assertIsNone(status_api_routes.STATUS_CACHE.get('sen:sen_owned:222'))

    def test_explicit_zero_success_is_cached_and_subscription_contract_is_unchanged(self):
        cases = (
            ("/api/bookcube_status?library_code=geumcheon&content_id=222", response(cube_detail(counts=cube_counts(0, 0, 0, "state")))),
            ("/api/gangnam_status?library_code=gangnam&content_id=222", gangnam_response(gangnam_detail(counts=gangnam_counts(0, 0, 0)))),
            ("/api/seoul_status?content_id=222", api_response({"Contents": content_record(loaned=0, total=0, reserved=0)})),
            ("/api/sen_status?library_code=sen_owned&content_id=222", api_response(xml_document(xml_record(loaned=0, total=0, reserved=0)), "application/xhtml+xml")),
        )
        for route, value in cases:
            with self.subTest(route=route):
                self.session.get.reset_mock(); self.session.get.side_effect = None; self.session.get.return_value = value
                first = self.get(route); self.assertEqual(first.status_code, 200)
                self.assertEqual(set(first.json["status"].values()), {0})
                self.assertEqual(self.get(route).json, first.json); self.assertEqual(self.session.get.call_count, 1)
        self.session.get.reset_mock()
        subs = self.get('/api/sen_status?library_code=sen_subs&content_id=unlimited')
        self.assertEqual(subs.status_code, 200); self.assertEqual(subs.json["status"], {"loaned": 0, "total": 1, "reserved": 0})
        self.session.get.assert_not_called()


class AuthorIdentityTests(unittest.TestCase):
    def test_role_letters_within_names_are_preserved(self):
        for author in ("더글러스 애덤스", "저스틴 크로닌", "한강", "김민역", "저우하오후이"):
            with self.subTest(author=author):
                self.assertEqual(clean_author_display(author), author)
                self.assertEqual(normalize_author(author), author.replace(" ", ""))

    def test_roles_require_metadata_boundaries(self):
        variants = ("더글러스 애덤스 저", "더글러스 애덤스 지음", "더글러스 애덤스 (지은이)",
                    "더글러스 애덤스 [저]", "지은이: 더글러스 애덤스", "저자 더글러스 애덤스",
                    "<더글러스 애덤스>저", "&lt;더글러스 애덤스&gt; 저", "<span>더글러스 애덤스</span> 저")
        for author in variants:
            with self.subTest(author=author):
                self.assertEqual(clean_author_display(author), "더글러스 애덤스")
                self.assertEqual(normalize_author(author), "더글러스애덤스")
        self.assertEqual(clean_author_display("김민역"), "김민역")
        self.assertEqual(clean_author_display("김민역 역"), "김민역")
        self.assertEqual(clean_author_display("한강저"), "한강저")

    def test_primary_author_separators_and_aliases_stay_compatible(self):
        for separator in ("/", ",", ";", "|", "·"):
            self.assertEqual(clean_author_display(f"더글러스 애덤스 저{separator}김철수 역"), "더글러스 애덤스")
        for author in ("프리다 맥파든 지음, 황성연 옮김", "프라다 맥파든", "Freida McFadden"):
            self.assertEqual(normalize_author(author), "프리다맥파든")
            self.assertEqual(clean_author_display(author), "프리다 맥파든")
        self.assertEqual(normalize_author("Andy Weir"), normalize_author("앤디 위어 저"))

    def test_same_title_different_authors_remain_separate(self):
        # The former global deletion collapsed these distinct names to 더러스.
        items = [LiveSearchResult(title="같은 제목", author=author, library_code=str(index))
                 for index, author in enumerate(("더글러스 애덤스", "더러스 애덤스"))]
        merged = merge_live_results(items)
        self.assertEqual(len(merged), 2)
        self.assertEqual({item["author"] for item in merged}, {"더글러스 애덤스", "더러스 애덤스"})

    def test_same_author_role_variants_merge_with_intact_display(self):
        items = [LiveSearchResult(title="검증 도서", author=author, library_code=str(index))
                 for index, author in enumerate(("저스틴 크로닌", "저스틴 크로닌 저", "<저스틴 크로닌> 지음"))]
        merged = merge_live_results(items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["author"], "저스틴 크로닌")
        self.assertEqual(merged[0]["counts"]["total"], 3)
        for item in items:
            display = clean_author_display(item.author)
            self.assertEqual(result_group_key(item.as_dict()), result_group_key({"title": item.title, "author": display}))

    def test_yes24_connector_preserves_names_before_merging(self):
        connector = Yes24Connector()
        for author in ("로버트 저메키스", "더글러스 애덤스", "저스틴 크로닌"):
            with self.subTest(author=author):
                document = listing('<div class="bx"><p class="tit">'
                                   '<a href="/ebook/detail/?goods_id=222">검증 도서</a></p>'
                                   f'<p class="writer">{author} 저/김철수 역</p></div>')
                items = connector._parse_results(document, "https://offline.example", "gwanak", {"library_name": "검증도서관"})
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].author, author)
                self.assertEqual(merge_live_results(items)[0]["author"], author)


class LibraryRegistryContextTests(unittest.TestCase):
    def test_search_and_detail_have_only_public_library_codes_and_names(self):
        import app_search

        captured = []

        def capture(_sender, template, context, **_extra):
            captured.append((template.name, context))

        expected = [{"code": code, "name": app_search.LIBRARY_SHORT.get(
            code, info.get("library_name") or info.get("name") or code)}
            for code, info in app_search.LIBRARIES.items()]
        with template_rendered.connected_to(capture, app_search.app), \
                patch.object(app_search, "get_db", side_effect=AssertionError("Registry needs no DB")), \
                patch("requests.sessions.Session.request", side_effect=AssertionError("Registry needs no network")):
            client = app_search.app.test_client()
            self.assertEqual(client.get('/search').status_code, 200)
            self.assertEqual(client.get('/live_book?title=검증도서&author=검증저자').status_code, 200)
        self.assertEqual([template for template, _context in captured], ["search.html", "live_book.html"])
        for _template, context in captured:
            self.assertEqual(context["library_registry"], expected)
            self.assertTrue(all(set(entry) == {"code", "name"} for entry in context["library_registry"]))
        self.assertEqual(captured[0][1]["lib_url_map"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
