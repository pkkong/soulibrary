#!/usr/bin/env python3
"""Run one fixed Songpa transport diagnostic in an isolated Seoul preview."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import library_relay_release as release
import songpa_probe_app as probe_app


REF = "refs/heads/codex/songpa-connection-fix"
ROOT = Path(__file__).resolve().parents[1]
MAX_REPLY = 32768


def deploy(environ, secret, run=subprocess.run):
    _, team_id, project_id = release.inspect.credentials(environ)
    child_env = {**environ, "CI": "1", "NO_COLOR": "1", "VERCEL_TELEMETRY_DISABLED": "1", "SONGPA_PROBE_SECRET": secret}
    version = run(["vercel", "--version"], env=child_env, capture_output=True, text=True, timeout=20, check=False)
    release.require(version.returncode == 0 and re.search(r"(?<![0-9.])64\.2\.0(?![0-9.])", version.stdout + version.stderr), "cli_version_mismatch")
    with tempfile.TemporaryDirectory(prefix="soulib-songpa-probe-") as directory:
        workspace = Path(directory)
        shutil.copyfile(ROOT / "scripts/songpa_probe_app.py", workspace / "songpa_probe_app.py")
        (workspace / "index.py").write_text("from songpa_probe_app import app\n", encoding="utf-8")
        (workspace / "requirements.txt").write_text("Flask\nrequests\n", encoding="utf-8")
        (workspace / "vercel.json").write_text(json.dumps({"framework": "flask", "regions": ["icn1"]}), encoding="utf-8")
        # Explicit existing link prevents automatic creation in the empty workspace.
        # These are project identity metadata, never the token or HMAC secret.
        (workspace / ".vercel").mkdir()
        (workspace / ".vercel/project.json").write_text(json.dumps({"orgId": team_id, "projectId": project_id}), encoding="utf-8")
        args = ["vercel", "deploy", "--yes", "--target=preview", "--regions=icn1",
                "--env", "SONGPA_PROBE_SECRET", "--build-env", "SONGPA_PROBE_SECRET"]
        result = run(args, cwd=workspace, env=child_env, capture_output=True, text=True, timeout=420, check=False)
        if result.returncode != 0:
            private = release.cli_private_values(environ, secret)
            raise release.CliDeployFailure(release.cli_failure_kind(result.stdout, result.stderr, private),
                                           release.cli_failure_details(result.stdout, result.stderr, result.returncode, private))
        return release.safe_url(result.stdout.strip())


def invoke(opener, url, secret):
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"\n" + probe_app.BODY, hashlib.sha256).hexdigest()
    request = urllib.request.Request(url + "/diagnose", data=probe_app.BODY, method="POST", headers={
        "Content-Type": "application/json", "X-Songpa-Probe-Timestamp": stamp, "X-Songpa-Probe-Signature": signature})
    try:
        with opener.open(request, timeout=24) as response:
            release.require(response.status == 200, "diagnostic_http_error")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                release.require(0 <= int(declared) <= MAX_REPLY, "diagnostic_response_too_large")
            raw = response.read(MAX_REPLY + 1)
            release.require(len(raw) <= MAX_REPLY, "diagnostic_response_too_large")
            payload = json.loads(raw)
        release.require(isinstance(payload, dict) and payload.get("ok") is True
                        and payload.get("mode") == "songpa-probe" and payload.get("region") == "icn1"
                        and payload.get("diagnosticComplete") is True, "diagnostic_unverified")
        release.require(payload.get("outcome") in ("request_completed", "request_failed", "budget_exhausted", "probe_failed")
                        and type(payload.get("requestSucceeded")) is bool
                        and type(payload.get("elapsedSeconds")) in (int, float)
                        and 0 <= payload["elapsedSeconds"] <= 20
                        and isinstance(payload.get("phases"), list) and len(payload["phases"]) <= 64, "diagnostic_invalid_response")
        events = b"\n".join(json.dumps(event).encode() for event in payload["phases"])
        events += b"\n" + json.dumps({"kind": "versions", **(payload.get("versions") or {})}).encode()
        phases, versions, _ = probe_app._event_payload(events)
        release.require(bool(phases), "diagnostic_unverified")
        return {"outcome": payload["outcome"], "requestSucceeded": payload["requestSucceeded"],
                "elapsedSeconds": round(payload["elapsedSeconds"], 3), "phases": phases, "versions": versions}
    except urllib.error.HTTPError as exc:
        status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        exc.close()
        raise release.inspect.ProbeFailure("diagnostic_http_error", status) from None
    except TimeoutError:
        raise release.inspect.ProbeFailure("diagnostic_transport_timeout") from None
    except urllib.error.URLError:
        raise release.inspect.ProbeFailure("diagnostic_network_error") from None
    except (ValueError, UnicodeError, TypeError):
        raise release.inspect.ProbeFailure("diagnostic_invalid_response") from None


def diagnose(environ, opener=None, run=subprocess.run, mask=None):
    release.manual_context(environ, REF)
    token, team_id, project_id = release.inspect.credentials(environ)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), release.inspect.NoRedirects())
    before = release.inspect.request_metadata("project", token, team_id, project_id, opener)
    baseline = release.production_snapshot(before, team_id, project_id)
    secret = secrets.token_hex(32)
    if mask:
        mask(secret)
    report = {"mode": "songpa-diagnose", "ok": False, "previewCreated": False,
              "productionMutationsRequested": False, "productionPreserved": False, "serviceRecoveryVerified": False}
    try:
        url = deploy(environ, secret, run)
        release.require(not any(value in url for value in (token, team_id, project_id, secret)), "invalid_deployment_url")
        report["previewCreated"] = True
        deployment = release.inspect.request_metadata("deployment", token, team_id, project_id, opener,
                                                      deployment_host=urllib.parse.urlparse(url).hostname)
        release.require((deployment.get("projectId") or release.inspect.object_field(deployment, "project").get("id")) == project_id
                        and deployment.get("target") is None and deployment.get("readyState") == "READY"
                        and release.inspect.allowed_regions(deployment.get("regions")) == ["icn1"], "preview_identity_or_region_mismatch")
        status, health, _ = release.read_json_response(opener, urllib.request.Request(url + "/health"), maximum=8192)
        release.require(status == 200 and health.get("ok") is True and health.get("mode") == "songpa-probe"
                        and health.get("region") == "icn1", "preview_health_or_access_failed")
        report["diagnostic"] = invoke(opener, url, secret)
        report["invocationRegion"] = "icn1"
    except release.inspect.ProbeFailure as exc:
        report["errorKind"] = exc.kind
        if exc.status is not None:
            report["errorHttpStatus"] = exc.status
        if isinstance(exc, release.CliDeployFailure):
            report.update(exc.details)
    except (subprocess.TimeoutExpired, OSError):
        report["errorKind"] = "cli_timeout_or_unavailable"
    except Exception:
        report["errorKind"] = "unexpected_error"
    finally:
        try:
            after = release.inspect.request_metadata("project", token, team_id, project_id, opener)
            report["productionPreserved"] = release.production_snapshot(after, team_id, project_id) == baseline
        except Exception:
            report["errorKind"] = "production_verification_failed"
    report["ok"] = bool(report["productionPreserved"] and report.get("diagnostic") and not report.get("errorKind"))
    return report


def main():
    try:
        report = diagnose(os.environ, mask=lambda value: print("::add-mask::" + value, flush=True))
    except release.inspect.ProbeFailure as exc:
        report = {"ok": False, "mode": "songpa-diagnose", "errorKind": exc.kind, "productionMutationsRequested": False}
    except Exception:
        report = {"ok": False, "mode": "songpa-diagnose", "errorKind": "unexpected_error", "productionMutationsRequested": False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
