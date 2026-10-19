"""Offline regressions for report pagination, resolution evidence, and storage."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import requests
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "web"))

import report_routes as reports


def issue(number, state="open", **extra):
    return {
        "number": number,
        "title": f"[오류신고] 오류 - 검증 신고 {number}",
        "body": f"## 신고 내용\n검증 신고 {number}\n\n## 문제가 있던 주소\nhttps://example.com/search",
        "html_url": f"https://github.com/pkkong/soulibrary/issues/{number}",
        "state": state,
        "created_at": "2026-10-19T01:00:00Z",
        "closed_at": "2026-10-19T03:00:00Z" if state == "closed" else None,
        "comments": 0,
        **extra,
    }


def ordinary_issue(number, pull_request=False):
    value = issue(number, title="운영 작업")
    if pull_request:
        value["pull_request"] = {"url": "https://api.github.com/example"}
    return value


def comment(body="## 처리 결과\n조치 완료\n검증한 운영자 설명", association="OWNER", **extra):
    return {
        "body": body,
        "author_association": association,
        "created_at": "2026-10-19T02:00:00Z",
        **extra,
    }


class Response:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError("offline HTTP error", response=response)

    def json(self):
        return self.data


class ReportIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "GITHUB_ISSUE_TOKEN": "offline-report-token",
            "GITHUB_ISSUE_REPO": "pkkong/soulibrary",
            "GITHUB_ISSUE_TIMEOUT": "8",
            "GITHUB_ISSUE_LABELS": "",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.network_guard = patch.object(
            requests.sessions.Session, "request",
            side_effect=AssertionError("Real network access is forbidden in this test."),
        )
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)
        self.app = Flask(__name__, template_folder=str(ROOT / "web" / "templates"))
        self.app.register_blueprint(reports.report_bp)
        self.client = self.app.test_client()

    def test_closed_states_without_evidence_never_claim_resolved(self):
        for reason in (None, "completed", "not_planned", "duplicate", "unknown"):
            with self.subTest(reason=reason):
                result = reports._issue_to_report(issue(1, "closed", state_reason=reason))
                self.assertEqual(result["status_label"], "종료됨")
                self.assertEqual(result["resolution_message"], "")
                self.assertIsNone(result["resolution_at"])

    def test_open_and_unknown_states_remain_distinct(self):
        for state, expected in (("open", "접수됨"), (None, "확인 중"), ("unexpected", "확인 중")):
            with self.subTest(state=state):
                result = reports._issue_to_report(issue(1, state))
                self.assertEqual(result["status_label"], expected)

    def test_valid_evidence_preserves_kst_and_only_fixed_message(self):
        with patch.object(reports.requests, "get", return_value=Response([
            comment(), comment("별도 후속 질문", created_at="2026-10-19T03:00:00Z"),
        ])):
            closed = issue(1, "closed", state_reason="completed", comments=2)
            resolution_at = reports._latest_resolution_time(closed)
        result = reports._issue_to_report(closed, resolution_at)
        self.assertEqual(result["status_label"], "해결됨")
        self.assertEqual(result["resolution_at"].strftime("%Y-%m-%d %H:%M"), "2026-10-19 11:00")
        self.assertEqual(result["resolution_message"], "신고하신 문제를 해결했습니다.")
        self.assertNotIn("운영자 설명", result["resolution_message"])

    def test_result_requires_exact_marker_trusted_author_and_valid_timestamp(self):
        rejected = [
            comment(association="NONE"), comment(association="CONTRIBUTOR"),
            comment("## 처리 결과\n확인 중"), comment("조치 완료"),
            comment("## 처리 결과\n아직 검토 중\n조치 완료"),
            comment("## 처리 결과\n조치 완료 예정"),
            comment(created_at="invalid"), comment(created_at=123),
        ]
        for value in rejected:
            with self.subTest(comment=value):
                with patch.object(reports.requests, "get", return_value=Response([value])):
                    self.assertIsNone(reports._latest_resolution_time(
                        issue(1, "closed", state_reason="completed", comments=1)))
        for association in ("OWNER", "MEMBER", "COLLABORATOR"):
            with self.subTest(association=association):
                with patch.object(reports.requests, "get", return_value=Response([comment(association=association)])):
                    self.assertIsNotNone(reports._latest_resolution_time(
                        issue(1, "closed", state_reason="completed", comments=1)))

    def test_not_planned_and_open_never_read_comments(self):
        with patch.object(reports.requests, "get") as get:
            for state, reason in (("open", "completed"), ("closed", "not_planned"), ("closed", None)):
                self.assertIsNone(reports._latest_resolution_time(issue(1, state, state_reason=reason, comments=1)))
            get.assert_not_called()

    def test_comment_destination_is_fixed_and_latest_page_is_bounded(self):
        with patch.object(reports.requests, "get", return_value=Response([comment()])) as get:
            result = reports._latest_resolution_time(issue(
                12, "closed", state_reason="completed", comments=201,
                comments_url="https://attacker.example/steal-token"))
        self.assertIsNotNone(result)
        self.assertEqual(get.call_args.args[0], "https://api.github.com/repos/pkkong/soulibrary/issues/12/comments")
        self.assertEqual(get.call_args.kwargs["params"]["page"], 3)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])

    def test_older_resolution_evidence_outside_latest_page_does_not_invent_success(self):
        with patch.object(reports.requests, "get", return_value=Response([comment("추가 질문")])) as get:
            self.assertIsNone(reports._latest_resolution_time(issue(12, "closed", state_reason="completed", comments=101)))
        self.assertEqual(get.call_count, 1)

    def test_invalid_resolution_at_cannot_create_resolved_result(self):
        result = reports._issue_to_report(issue(1, "closed", state_reason="completed"), "invalid")
        self.assertEqual(result["status_label"], "종료됨")
        self.assertEqual(result["resolution_message"], "")

    def test_reports_after_100_prs_and_100_regular_issues_are_found_in_order(self):
        pages = [
            [ordinary_issue(number, pull_request=True) for number in range(500, 400, -1)],
            [ordinary_issue(number) for number in range(400, 300, -1)],
            [issue(299), issue(298), issue(297)],
        ]
        with patch.object(reports.requests, "get", side_effect=[Response(page) for page in pages]) as get:
            result = reports._recent_github_reports(limit=2)
        self.assertEqual([entry["issue_number"] for entry in result], [299, 298])
        self.assertEqual([call.kwargs["params"]["page"] for call in get.call_args_list], [1, 2, 3])
        for call in get.call_args_list:
            self.assertEqual(call.args[0], "https://api.github.com/repos/pkkong/soulibrary/issues")
            self.assertEqual(call.kwargs["params"]["sort"], "created")
            self.assertEqual(call.kwargs["params"]["direction"], "desc")
            self.assertFalse(call.kwargs["allow_redirects"])
            self.assertGreater(call.kwargs["timeout"], 0)
            self.assertLessEqual(call.kwargs["timeout"], 8)

    def test_pr_with_report_title_is_excluded_and_duplicate_page_items_are_deduped(self):
        first = [issue(500, pull_request={})] + [ordinary_issue(number) for number in range(499, 400, -1)]
        first[-1] = issue(401)
        with patch.object(reports.requests, "get", side_effect=[Response(first), Response([issue(401), issue(399)])]):
            result = reports._recent_github_reports()
        self.assertEqual([entry["issue_number"] for entry in result], [401, 399])

    def test_page_limit_cannot_return_normal_empty(self):
        page = [ordinary_issue(number) for number in range(1, 101)]
        with patch.object(reports.requests, "get", return_value=Response(page)) as get:
            with self.assertRaises(reports.ReportListUnavailable) as raised:
                reports._recent_github_reports()
        self.assertEqual(get.call_count, reports.REPORT_LIST_MAX_PAGES)
        self.assertEqual(raised.exception.reports, [])

    def test_page_limit_keeps_partial_reports_in_failure(self):
        page = [issue(1)] + [ordinary_issue(number) for number in range(2, 101)]
        with patch.object(reports.requests, "get", return_value=Response(page)):
            with self.assertRaises(reports.ReportListUnavailable) as raised:
                reports._recent_github_reports()
        self.assertEqual([entry["issue_number"] for entry in raised.exception.reports], [1])

    def test_http_failure_keeps_prior_page_reports(self):
        page = [issue(300)] + [ordinary_issue(number) for number in range(299, 200, -1)]
        with patch.object(reports.requests, "get", side_effect=[Response(page), Response({}, 503)]):
            with self.assertRaises(reports.ReportListUnavailable) as raised:
                reports._recent_github_reports()
        self.assertEqual([entry["issue_number"] for entry in raised.exception.reports], [300])

    def test_timeout_and_invalid_response_are_not_normal_empty(self):
        for response in (requests.Timeout("offline timeout"), Response({"invalid": "shape"}), Response([], 302)):
            with self.subTest(response=response):
                with patch.object(reports.requests, "get", side_effect=[response]):
                    with self.assertRaises(reports.ReportListUnavailable):
                        reports._recent_github_reports()

    def test_budget_exhaustion_prevents_another_request(self):
        page = [ordinary_issue(number) for number in range(1, 101)]
        with patch.object(reports.time, "monotonic", side_effect=[0.0, 0.0, 8.1]):
            with patch.object(reports.requests, "get", return_value=Response(page)) as get:
                with self.assertRaises(reports.ReportListUnavailable):
                    reports._recent_github_reports()
        self.assertEqual(get.call_count, 1)

    def test_empty_completed_read_is_a_real_empty_list(self):
        with patch.object(reports.requests, "get", return_value=Response([])) as get:
            self.assertEqual(reports._recent_github_reports(), [])
        self.assertEqual(get.call_count, 1)

    def test_completed_comment_lookups_are_capped_and_fail_closed(self):
        closed = [issue(number, "closed", state_reason="completed", comments=1) for number in range(10, 0, -1)]
        with patch.object(reports.requests, "get", side_effect=[Response(closed), *[Response([comment()])] * 3]) as get:
            result = reports._recent_github_reports()
        self.assertEqual(get.call_count, 4)
        self.assertEqual([value["status_label"] for value in result], ["해결됨"] * 3 + ["종료됨"] * 7)

    def test_comment_failure_does_not_hide_valid_report_or_claim_resolved(self):
        with patch.object(reports.requests, "get", side_effect=[
            Response([issue(1, "closed", state_reason="completed", comments=1)]),
            Response({}, 503),
        ]):
            result = reports._recent_github_reports()
        self.assertEqual(result[0]["status_label"], "종료됨")
        self.assertEqual(result[0]["resolution_message"], "")

    def test_api_partial_list_renders_reports_and_notice_with_503(self):
        partial = [reports._issue_to_report(issue(1))]
        with patch.object(reports, "_recent_github_reports", side_effect=reports.ReportListUnavailable(partial)):
            response = self.client.get("/api/reports/recent")
        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertTrue(payload["unavailable"])
        self.assertIn("검증 신고 1", payload["html"])
        self.assertIn(reports.REPORT_LIST_PARTIAL_NOTICE, payload["html"])
        self.assertNotIn("아직 접수된 신고가 없습니다", payload["html"])

    def test_api_failed_empty_and_actual_empty_are_distinct(self):
        with patch.object(reports, "_recent_github_reports", side_effect=reports.ReportListUnavailable([])):
            failed = self.client.get("/api/reports/recent")
        with patch.object(reports, "_recent_github_reports", return_value=[]):
            empty = self.client.get("/api/reports/recent")
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(empty.status_code, 200)
        self.assertNotIn("아직 접수된 신고가 없습니다", failed.get_json()["html"])
        self.assertIn("아직 접수된 신고가 없습니다", empty.get_json()["html"])

    def test_result_comments_never_appear_in_public_html(self):
        closed = issue(1, "closed", state_reason="completed", comments=1)
        secret_text = "검증용 내부 설명 admin@example.com"
        with patch.object(reports.requests, "get", side_effect=[Response([closed]), Response([comment(
            "## 처리 결과\n조치 완료\n" + secret_text)])]):
            response = self.client.get("/api/reports/recent")
        self.assertEqual(response.status_code, 200)
        html = response.get_json()["html"]
        self.assertIn("해결됨", html)
        self.assertIn("신고하신 문제를 해결했습니다.", html)
        self.assertNotIn(secret_text, html)
        self.assertNotIn("admin@example.com", html)

    def test_contact_fields_are_not_published_and_only_confirmed_creation_is_success(self):
        with patch.object(reports.requests, "post", return_value=Response(issue(42), 201)) as post:
            response = self.client.post("/api/reports", json={
                "message": "검증을 위한 충분한 신고 내용", "contact": "private@example.com",
                "email": "private@example.com", "page_url": "https://example.com/search",
            })
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(response.get_json()["report"]["issue_number"], 42)
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("private@example.com", str(payload))
        self.assertNotIn("## 연락처", payload["body"])

    def test_creation_http_failure_or_missing_issue_is_not_success(self):
        for result in (Response({}, 503), Response({}, 201), Response(issue(1), 200), Response(issue(True), 201)):
            with self.subTest(result=result):
                with patch.object(reports.requests, "post", return_value=result):
                    response = self.client.post("/api/reports", json={"message": "충분한 길이의 검증 신고 내용"})
                self.assertEqual(response.status_code, 500)
                self.assertNotIn("ok", response.get_json())

    def test_honeypot_and_invalid_inputs_never_write_reports(self):
        with patch.object(reports.requests, "post") as post:
            invalid = self.client.post("/api/reports", json={"message": "짧음"})
            trap = self.client.post("/api/reports", json={"message": "검증 신고 내용입니다", "website": "https://spam.example"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(trap.status_code, 200)
        self.assertIsNone(trap.get_json()["report"])
        post.assert_not_called()

    def test_limit_zero_avoids_requests(self):
        with patch.object(reports.requests, "get") as get:
            self.assertEqual(reports._recent_github_reports(limit=0), [])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
