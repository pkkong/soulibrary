#!/usr/bin/env python3
"""Offline transport-observer, privacy, authentication and release guards."""

import contextlib
import copy
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error
import urllib.parse

import requests
import urllib3.connection as connection
import urllib3.util.connection as util_connection
import songpa_probe_app as app
import songpa_connectivity_probe as client


SECRET, TOKEN, TEAM, PROJECT = "f" * 64, "managementCanary", "team_test", "prj_test"
PRIVATE = "private-page-cookie-address-canary"
URL = "https://songpa-test.vercel.app"
ENV = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": "pkkong/soulibrary",
       "GITHUB_REF": client.REF, "VERCEL_TOKEN": TOKEN, "VERCEL_ORG_ID": TEAM, "VERCEL_PROJECT_ID": PROJECT}
PROJECT_DATA = {"id": PROJECT, "accountId": TEAM, "framework": "flask", "resourceConfig": {"functionDefaultRegions": ["iad1"]},
                "targets": {"production": {"id": "dpl_current", "url": "production.vercel.app", "alias": ["www.soulib.kr"]}}}
PHASE = {"phase": "tcp", "state": "started", "elapsedSeconds": 0}
DIAGNOSTIC = {"ok": True, "mode": "songpa-probe", "region": "icn1", "diagnosticComplete": True,
              "requestSucceeded": False, "outcome": "budget_exhausted", "elapsedSeconds": 15.01,
              "phases": [PHASE], "versions": {"requests": "2.32.5", "urllib3": "2.5.0"}}


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.raw, self.status, self.headers = json.dumps(payload).encode(), status, headers or {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, maximum): return self.raw[:maximum]


class Opener:
    def __init__(self): self.calls = []
    def open(self, request, timeout):
        self.calls.append(request)
        assert request.get_header("Authorization") is None
        if request.full_url == URL + "/health":
            return Response({"ok": True, "mode": "songpa-probe", "region": "icn1"})
        assert request.full_url == URL + "/diagnose" and request.get_method() == "POST"
        assert request.data == app.BODY and timeout == 24
        stamp = request.get_header("X-songpa-probe-timestamp")
        signature = hmac.new(SECRET.encode(), stamp.encode() + b"\n" + app.BODY, hashlib.sha256).hexdigest()
        assert request.get_header("X-songpa-probe-signature") == signature
        return Response({**DIAGNOSTIC, "raw": PRIVATE, "secret": SECRET})


class SongpaTests(unittest.TestCase):
    def assert_private(self, value):
        text = json.dumps(value)
        for private in (SECRET, TOKEN, TEAM, PROJECT, PRIVATE, app.EXPECTED_ADDRESS, "프로젝트 헤일메리"):
            self.assertNotIn(private, text)

    def test_auth_payload_and_single_use_never_start_unauthorized_probe(self):
        stamp = str(int(time.time()))
        signature = hmac.new(SECRET.encode(), stamp.encode() + b"\n" + app.BODY, hashlib.sha256).hexdigest()
        headers = {"X-Songpa-Probe-Timestamp": stamp, "X-Songpa-Probe-Signature": signature}
        app._used = False
        with mock.patch.dict(os.environ, {"SONGPA_PROBE_SECRET": SECRET, "VERCEL_REGION": "icn1"}), \
                mock.patch.object(app, "diagnose", return_value={key: value for key, value in DIAGNOSTIC.items() if key not in ("ok", "mode", "region")}) as diagnostic:
            browser = app.app.test_client()
            self.assertEqual(browser.get("/health").json, {"ok": True, "mode": "songpa-probe", "region": "icn1"})
            for path, data, auth in (("/diagnose", app.BODY, {}), ("/diagnose?url=bad", app.BODY, headers),
                                     ("/diagnose", b'{"url":"bad"}', headers), ("/diagnose", app.BODY, {**headers, "X-Songpa-Probe-Signature": "한글"})):
                self.assertIn(browser.post(path, data=data, headers=auth).status_code, (400, 401))
            diagnostic.assert_not_called()
            self.assertEqual(browser.post("/diagnose", data=app.BODY, headers=headers).status_code, 200)
            self.assertEqual(browser.post("/diagnose", data=app.BODY, headers=headers).status_code, 409)
            diagnostic.assert_called_once_with()

    def test_subprocess_budget_and_allowlist_survive_timeout_without_secrets(self):
        raw = b"\n".join(json.dumps(event).encode() for event in (
            {"kind": "versions", "python": "3.11.0", "requests": PRIVATE}, {**PHASE, "raw": PRIVATE, "ip": app.EXPECTED_ADDRESS},
            {"phase": PRIVATE, "state": "failed", "elapsedSeconds": 1}, {"kind": "done", "success": False}))
        def run(args, **kwargs):
            self.assertEqual(args[-1], "--worker")
            self.assertEqual(kwargs["timeout"], 15)
            self.assertEqual(set(kwargs["env"]), {"PATH", "PYTHONPATH", "PYTHONUNBUFFERED", "LD_LIBRARY_PATH"})
            self.assertEqual(kwargs["env"]["LD_LIBRARY_PATH"], "/var/lang/lib:/lib64")
            self.assertNotIn(SECRET, json.dumps(kwargs))
            raise subprocess.TimeoutExpired(args, 15, output=raw, stderr=PRIVATE.encode())
        with mock.patch.dict(os.environ, {"SONGPA_PROBE_SECRET": SECRET, "VERCEL_TOKEN": TOKEN, "HTTPS_PROXY": PRIVATE,
                                          "LD_LIBRARY_PATH": "/var/lang/lib:/lib64"}):
            result = app.diagnose(run=run)
        self.assertTrue(result["diagnosticComplete"])
        self.assertFalse(result["requestSucceeded"])
        self.assertEqual(result["outcome"], "budget_exhausted")
        self.assertEqual(result["phases"], [PHASE])
        self.assert_private(result)

    def observe_worker(self, fail_phase=None, oversized=False):
        calls, output = [], io.StringIO()
        test = self
        class Page:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_content(self, chunk_size):
                yield b"x" * (app.MAX_BODY + 1) if oversized else PRIVATE.encode()
        class Session:
            def __init__(self): self.headers = {"Accept-Encoding": "gzip", "Connection": "keep-alive"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def mount(self, origin, adapter): test.assertEqual(adapter.max_retries.total, 0)
            def get(self, url, **kwargs):
                calls.append(url)
                parsed = urllib.parse.urlparse(url)
                test.assertEqual((parsed.scheme, parsed.hostname, parsed.path), ("https", app.HOST, "/search/"))
                test.assertEqual(urllib.parse.parse_qs(parsed.query), {"srch_order": ["total"], "src_key": ["프로젝트 헤일메리"]})
                test.assertFalse(self.trust_env)
                test.assertEqual(kwargs["verify"], True)
                test.assertEqual(kwargs["allow_redirects"], False)
                test.assertEqual(kwargs["timeout"], 15)
                test.assertEqual(kwargs["headers"]["Referer"], "https://" + app.HOST)
                test.assertIn("Accept-Encoding", self.headers)
                test.assertNotIn("cookies", kwargs)
                util_connection.create_connection((app.HOST, 443), timeout=15)
                connection._ssl_wrap_socket_and_match_hostname(server_hostname=app.HOST)
                connection.HTTPConnection.getresponse(object())
                return Page()
        def original_connect(address, timeout):
            socket.getaddrinfo(address[0], address[1])
            socket.socket.connect(object(), (app.EXPECTED_ADDRESS, 443))
            return object()
        failures = {"dns": socket.gaierror(PRIVATE), "tcp": TimeoutError(PRIVATE), "tls": ssl.SSLError(PRIVATE), "http_headers": TimeoutError(PRIVATE)}
        with mock.patch.object(requests, "Session", Session), \
                mock.patch.object(socket, "getaddrinfo", side_effect=failures.get(fail_phase) if fail_phase == "dns" else None,
                                  return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (app.EXPECTED_ADDRESS, 443))]), \
                mock.patch.object(socket.socket, "connect", side_effect=failures.get(fail_phase) if fail_phase == "tcp" else None), \
                mock.patch.object(util_connection, "create_connection", side_effect=original_connect), \
                mock.patch.object(connection, "_ssl_wrap_socket_and_match_hostname", side_effect=failures.get(fail_phase) if fail_phase == "tls" else None,
                                  return_value=SimpleNamespace(socket=SimpleNamespace(version=lambda: "TLSv1.3"))), \
                mock.patch.object(connection.HTTPConnection, "getresponse", side_effect=failures.get(fail_phase) if fail_phase == "http_headers" else None,
                                  return_value=SimpleNamespace(status=200)), contextlib.redirect_stdout(output):
            app._worker()
        phases, versions, done = app._event_payload(output.getvalue().encode())
        self.assertEqual(len(calls), 1)
        self.assert_private({"phases": phases, "versions": versions})
        return phases, done

    def test_transport_observers_original_calls_and_fixed_single_get(self):
        phases, done = self.observe_worker()
        self.assertTrue(done)
        self.assertTrue(next(event for event in phases if event["phase"] == "dns" and event["state"] == "ok")["sameExpectedAddress"])
        self.assertEqual({event["phase"] for event in phases}, app.PHASES)
        for phase in ("dns", "tcp", "tls", "http_headers"):
            phases, done = self.observe_worker(fail_phase=phase)
            self.assertFalse(done)
            self.assertTrue(any(event["phase"] == phase and event["state"] == "failed" and event["errorKind"] in app.ERRORS for event in phases))
        phases, done = self.observe_worker(oversized=True)
        self.assertFalse(done)
        self.assertTrue(any(event.get("errorKind") == "body_too_large" for event in phases))

    def test_minimal_deploy_only_preview_no_key_in_argv_or_workspace(self):
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            self.assertNotIn(SECRET, json.dumps(args))
            if args == ["vercel", "--version"]:
                return subprocess.CompletedProcess(args, 0, "64.2.0", "")
            self.assertIn("--target=preview", args)
            self.assertIn("--regions=icn1", args)
            workspace = Path(kwargs["cwd"])
            self.assertEqual({path.name for path in workspace.iterdir()}, {"index.py", "requirements.txt", "vercel.json", "songpa_probe_app.py", ".vercel"})
            for path in workspace.rglob("*"):
                if path.is_file(): self.assertNotIn(SECRET, path.read_text())
            self.assertEqual(json.loads((workspace / ".vercel/project.json").read_text()), {"orgId": TEAM, "projectId": PROJECT})
            self.assertEqual(kwargs["env"]["SONGPA_PROBE_SECRET"], SECRET)
            self.assertEqual(kwargs["env"]["VERCEL_PROJECT_ID"], PROJECT)
            self.assertNotIn("--prod", args)
            self.assertEqual((workspace / "index.py").read_text(), "from songpa_probe_app import app\n")
            return subprocess.CompletedProcess(args, 0, URL, PRIVATE)
        self.assertEqual(client.deploy(ENV, SECRET, run=run), URL)
        self.assertEqual(len(calls), 2)

    def test_cloud_timeout_diagnosis_is_success_not_recovery_and_production_preserved(self):
        for changed, wrong_region in ((False, False), (True, False), (False, True)):
            project_reads = 0
            def metadata(resource, *args, **kwargs):
                nonlocal project_reads
                if resource == "project":
                    project_reads += 1
                    result = copy.deepcopy(PROJECT_DATA)
                    if changed and project_reads > 1: result["targets"]["production"]["id"] = "dpl_changed"
                    return result
                return {"projectId": PROJECT, "target": None, "readyState": "READY", "regions": ["iad1" if wrong_region else "icn1"]}
            opener, masks = Opener(), []
            with mock.patch.object(client.release.inspect, "request_metadata", side_effect=metadata), \
                    mock.patch.object(client, "deploy", return_value=URL), mock.patch.object(client.secrets, "token_hex", return_value=SECRET):
                report = client.diagnose(ENV, opener=opener, mask=masks.append)
            self.assertEqual(report["ok"], not changed and not wrong_region)
            self.assertFalse(report["serviceRecoveryVerified"] or report["productionMutationsRequested"])
            self.assertEqual(len(opener.calls), 0 if wrong_region else 2)
            self.assertEqual(masks, [SECRET])
            self.assertEqual(project_reads, 2)
            self.assert_private(report)

    def test_strict_context_before_deploy_or_network(self):
        for change in ({"GITHUB_REF": "refs/heads/main"}, {"GITHUB_EVENT_NAME": "push"}, {"GITHUB_REPOSITORY": "other/repo"}):
            with self.assertRaisesRegex(client.release.inspect.ProbeFailure, "ci_context_required"), mock.patch.object(client, "deploy") as deploy:
                client.diagnose({**ENV, **change}, opener=Opener())
            deploy.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
