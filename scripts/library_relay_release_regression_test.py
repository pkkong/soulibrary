#!/usr/bin/env python3
"""Offline release guards: no credentials, fixtures, network or deployments."""

import copy
import json
import unittest
from unittest import mock
import urllib.error
import urllib.parse

import library_relay_release as release


TOKEN, TEAM, PROJECT = "managementCanary", "team_test", "prj_test"
SECRET, URL = "f" * 64, "https://relay-test.vercel.app"
ENV = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
       "GITHUB_REPOSITORY": "pkkong/soulibrary", "GITHUB_REF": release.BRANCH_REF,
       "VERCEL_TOKEN": TOKEN, "VERCEL_ORG_ID": TEAM, "VERCEL_PROJECT_ID": PROJECT}
PROJECT_DATA = {"id": PROJECT, "accountId": TEAM, "framework": "flask",
                "resourceConfig": {"functionDefaultRegions": ["iad1"]},
                "targets": {"production": {"id": "dpl_current", "url": "production.vercel.app", "alias": ["www.soulib.kr"]}}}


def row(key):
    return {"key": key, "type": "encrypted", "target": ["production"], "value": SECRET}


class Response:
    headers = {}

    def __init__(self, payload, status):
        self.data, self.status = json.dumps(payload).encode(), status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, maximum):
        return self.data[:maximum]


class EnvironmentAPI:
    def __init__(self, rows=(), fail_write=0):
        self.rows, self.writes, self.calls = copy.deepcopy(list(rows)), [], []
        self.fail_write = fail_write

    def open(self, request, timeout):
        self.calls.append(request)
        parsed = urllib.parse.urlparse(request.full_url)
        assert parsed.scheme == "https" and parsed.netloc == "api.vercel.com"
        assert parsed.path == "/v10/projects/" + PROJECT + "/env"
        assert request.get_header("Authorization") == "Bearer " + TOKEN
        assert timeout == release.inspect.TIMEOUT_SECONDS
        query = urllib.parse.parse_qs(parsed.query)
        if request.get_method() == "GET":
            assert query == {"teamId": [TEAM], "decrypt": ["false"]}
            return Response({"envs": self.rows}, 200)
        assert request.get_method() == "POST" and query == {"teamId": [TEAM], "upsert": ["true"]}
        body = json.loads(request.data)
        assert set(body) == {"key", "value", "type", "target"}
        assert body["key"] in release.PRODUCTION_KEYS
        assert body["type"] == "encrypted" and body["target"] == ["production"]
        self.writes.append(body)
        if len(self.writes) == self.fail_write:
            raise urllib.error.URLError(SECRET + TOKEN)
        self.rows = [entry for entry in self.rows if entry["key"] != body["key"]]
        created = {**body, "value": SECRET, "id": "envIdCanary"}
        self.rows.append(created)
        return Response({"created": created, "failed": []}, 201)


class ReleaseGuards(unittest.TestCase):
    def prepare(self, api, proof=True, extra_records=()):
        def metadata(resource, *args, **kwargs):
            return copy.deepcopy(PROJECT_DATA if resource == "project" else {
                "projectId": PROJECT, "target": None, "readyState": "READY", "regions": ["icn1"]})
        records = [{"libraryCode": code, "status": "ok", "region": "icn1",
                    "hasIdentifier": True, "hasStatus": proof} for code in release.REQUIRED_CODES]
        records.extend(extra_records)
        with mock.patch.object(release.inspect, "request_metadata", side_effect=metadata), \
                mock.patch.object(release, "deploy_preview", return_value=URL), \
                mock.patch.object(release, "read_json_response", return_value=(200, {"ok": True, "mode": "library-relay", "region": "icn1"}, 0)), \
                mock.patch.object(release, "check_libraries", return_value=records), \
                mock.patch.object(release.secrets, "token_hex", return_value=SECRET):
            return release.preview(ENV, mode="prepare", opener=api)

    def assert_private(self, report):
        for private in (SECRET, TOKEN, TEAM, PROJECT, "envIdCanary"):
            self.assertNotIn(private, json.dumps(report))

    def test_prepare_off_first_and_only_four_keys(self):
        api = EnvironmentAPI([row("EXISTING_UNRELATED")])
        report = self.prepare(api)
        self.assertTrue(report["ok"] and report["productionConfigPrepared"] and report["productionPreserved"])
        self.assertEqual([entry["key"] for entry in api.writes], ["LIBRARY_RELAY_ENABLED", "LIBRARY_RELAY_URL", "LIBRARY_RELAY_SECRET", "LIBRARY_RELAY_CODES"])
        self.assertEqual([entry["value"] for entry in api.writes], ["0", URL, SECRET, "seongbuk,yeongdeungpo"])
        self.assertTrue(any(entry["key"] == "EXISTING_UNRELATED" for entry in api.rows))
        self.assertFalse(report["productionDeploymentRequested"] or report["effectiveProductionRecoveryVerified"])
        self.assert_private(report)

    def test_no_writes_until_both_statuses_proved(self):
        api = EnvironmentAPI()
        report = self.prepare(api, proof=False)
        self.assertEqual(report["errorKind"], "relay_verification_failed")
        self.assertEqual(api.calls, [])

    def test_partial_write_failures_stop_after_off(self):
        for failure in range(1, 5):
            api = EnvironmentAPI(fail_write=failure)
            report = self.prepare(api)
            self.assertFalse(report["ok"] or report["productionConfigPrepared"])
            self.assertTrue(report["productionPreserved"])
            self.assertEqual(len(api.writes), failure)
            self.assertEqual(api.writes[0]["value"], "0")
            self.assert_private(report)

    def test_gangseo_staged_only_with_search_and_status_pair(self):
        search = {"libraryCode": "gangseo", "status": "ok", "region": "icn1", "hasIdentifier": True}
        detail = {"libraryCode": "gangseo", "status": "ok", "region": "icn1", "hasStatus": True}
        cases = [([search, detail], True), ([search], False),
                 ([search, {**detail, "status": "failed", "hasStatus": False}], False),
                 ([detail], False), ([search, {**detail, "region": "iad1"}], False)]
        for records, include in cases:
            api = EnvironmentAPI()
            report = self.prepare(api, extra_records=records)
            self.assertTrue(report["ok"])
            expected = release.STAGED_CODE_VALUES[1 if include else 0]
            self.assertEqual(api.writes[-1]["value"], expected)
            self.assertEqual(report["preparedRelayCodes"], expected.split(","))
            self.assert_private(report)
        api = EnvironmentAPI()
        report = self.prepare(api, extra_records=[{**search, "libraryCode": "songpa_owned"}, {**detail, "libraryCode": "songpa_owned"}])
        self.assertTrue(report["ok"])
        self.assertEqual(api.writes[-1]["value"], release.STAGED_CODE_VALUES[0])
        for value in ("gangseo", "seongbuk,yeongdeungpo,songpa_owned", "seongbuk,yeongdeungpo,gangseo,songpa_owned"):
            with self.assertRaises(release.inspect.ProbeFailure):
                release.production_env("upsert", TOKEN, TEAM, PROJECT, EnvironmentAPI(), "LIBRARY_RELAY_CODES", value)

    def test_optional_gangseo_status_uses_returned_id_and_three_detail_cap(self):
        calls = []
        def page(opener, url, secret, code, operation, params):
            calls.append((code, operation, params))
            return {"libraryCode": code, "operation": operation, "status": "ok", "region": "icn1"}, object()
        def search(response, code):
            return {"brcd": "test-brcd"} if code == "seongbuk" else {"goods_id": code + "-returned-id"}
        with mock.patch.object(release, "page_check", side_effect=page), \
                mock.patch.object(release, "parse_search", side_effect=search), \
                mock.patch.object(release, "parse_status", return_value=True):
            records = release.check_libraries(None, URL, SECRET)
        details = [call for call in calls if call[1].endswith("_detail")]
        self.assertEqual(len(calls), 7)
        self.assertEqual([call[0] for call in details], ["seongbuk", "yeongdeungpo", "gangseo"])
        self.assertEqual(details[-1], ("gangseo", "yes24_detail", {"goods_id": "gangseo-returned-id"}))
        self.assertTrue(next(record for record in records if record["libraryCode"] == "gangseo" and "hasStatus" in record)["hasStatus"])

    def test_main_switch_requires_prepared_metadata_and_only_writes_enabled(self):
        env = {**ENV, "GITHUB_REF": release.MAIN_REF}
        with mock.patch.object(release.inspect, "request_metadata", return_value=PROJECT_DATA):
            for mode in ("activate", "disable"):
                api = EnvironmentAPI(row(key) for key in release.PRODUCTION_KEYS)
                report = release.toggle(env, mode, opener=api)
                self.assertTrue(report["ok"])
                self.assertEqual([(entry["key"], entry["value"]) for entry in api.writes], [("LIBRARY_RELAY_ENABLED", "1" if mode == "activate" else "0")])
                self.assertFalse(report["productionDeploymentRequested"])
                self.assert_private(report)
            api = EnvironmentAPI()
            self.assertFalse(release.toggle(env, "activate", opener=api)["ok"])
            self.assertEqual(api.writes, [])

    def test_strict_context_before_any_api_call(self):
        for mode in ("preview", "prepare", "activate", "disable"):
            valid = {**ENV, "GITHUB_REF": release.BRANCH_REF if mode in ("preview", "prepare") else release.MAIN_REF}
            wrong_ref = release.MAIN_REF if valid["GITHUB_REF"] == release.BRANCH_REF else release.BRANCH_REF
            for change in ({"GITHUB_REF": wrong_ref}, {"GITHUB_EVENT_NAME": "push"}, {"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_EVENT_NAME": "schedule"}, {"GITHUB_REPOSITORY": "foreign/repo"}):
                api = EnvironmentAPI()
                with self.assertRaisesRegex(release.inspect.ProbeFailure, "ci_context_required"):
                    if mode in ("preview", "prepare"):
                        release.preview({**valid, **change}, mode=mode, opener=api)
                    else:
                        release.toggle({**valid, **change}, mode, opener=api)
                self.assertEqual(api.calls, [])

    def test_metadata_hides_values_and_rejects_scope_or_mode_conflicts(self):
        metadata = release.production_env("list", TOKEN, TEAM, PROJECT, EnvironmentAPI([row("LIBRARY_RELAY_SECRET")]))
        self.assertNotIn(SECRET, json.dumps(metadata))
        for conflict in ({**row("LIBRARY_RELAY_SECRET"), "target": ["production", "preview"]}, {**row("LIBRARY_RELAY_SECRET"), "type": "plain"}, row("LIBRARY_RELAY_MODE")):
            api = EnvironmentAPI([conflict])
            report = self.prepare(api)
            self.assertFalse(report["ok"])
            self.assertEqual(api.writes, [])
        with self.assertRaises(release.inspect.ProbeFailure):
            release.production_env("upsert", TOKEN, TEAM, PROJECT, EnvironmentAPI(), "LIBRARY_RELAY_MODE", "1")

    def test_http_failure_reports_only_safe_status(self):
        env = {**ENV, "GITHUB_REF": release.MAIN_REF}
        for failure in (urllib.error.HTTPError(URL, 403, SECRET + TOKEN, {}, None), Response({}, 202)):
            api = mock.Mock()
            if isinstance(failure, Exception):
                api.open.side_effect = failure
            else:
                api.open.return_value = failure
            with mock.patch.object(release.inspect, "request_metadata", return_value=PROJECT_DATA):
                report = release.toggle(env, "disable", opener=api)
            self.assertFalse(report["ok"])
            self.assertEqual(report["errorHttpStatus"], 403 if isinstance(failure, Exception) else 202)
            self.assert_private(report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
