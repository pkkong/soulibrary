#!/usr/bin/env python3
"""Create and test one isolated preview using existing CI credentials.

Default mode only inspects metadata. Preview mode never modifies production,
project environment variables, protection settings, domains, or paid services.
Raw CLI/API responses and page content must never be printed or persisted.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import library_connectivity_probe as inspect


ROOT = Path(__file__).resolve().parents[1]
BRANCH_REF = "refs/heads/codex/library-connectivity-recovery"
CLI_VERSION = "64.2.0"
CODES = ("seongbuk", "yeongdeungpo", "songpa_owned", "gangseo")
REQUIRED_CODES = CODES[:2]
FIXED_QUERY = "프로젝트 헤일메리"
MAX_ENVELOPE = 3 * 1024 * 1024
ERRORS = frozenset({
    "configuration", "authentication", "invalid_request", "budget_exhausted",
    "transport_error", "upstream_http", "redirect", "body_too_large",
    "invalid_document", "invalid_response", "busy",
})


def require(condition, kind):
    if not condition:
        raise inspect.ProbeFailure(kind)


def safe_url(value):
    require(isinstance(value, str) and len(value) <= 300, "invalid_deployment_url")
    parsed = urllib.parse.urlparse(value)
    require(
        parsed.scheme == "https" and parsed.netloc == parsed.hostname
        and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.vercel\.app", parsed.hostname or ""))
        and parsed.path in ("", "/") and not parsed.query and not parsed.fragment,
        "invalid_deployment_url",
    )
    return "https://" + parsed.hostname


def production_snapshot(project, team_id, project_id):
    summary = inspect.summarize_project(project, team_id, project_id)
    require(summary["existingProjectMatches"] and summary["existingTeamMatches"], "project_mismatch")
    require(summary["framework"] == "flask" and summary["projectDefaultRegions"] == ["iad1"], "production_configuration_changed")
    production = inspect.object_field(inspect.object_field(project, "targets"), "production")
    require(isinstance(production.get("id"), str) and production["id"].startswith("dpl_"), "production_target_missing")
    require(isinstance(production.get("url"), str) and production["url"], "production_target_missing")
    # Keep identities/protection entirely in memory and publish only comparisons.
    return {
        "targetId": production["id"], "targetUrl": production["url"],
        "targetAliases": production.get("alias"),
        "defaultRegions": summary["projectDefaultRegions"],
        "framework": summary["framework"],
        "protection": {key: project.get(key) for key in ("ssoProtection", "passwordProtection", "passport", "trustedIps")},
    }


def deploy_preview(environ, secret, run=subprocess.run):
    child_env = dict(environ)
    child_env.update({
        "CI": "1", "NO_COLOR": "1", "VERCEL_TELEMETRY_DISABLED": "1",
        "LIBRARY_RELAY_MODE": "1", "LIBRARY_RELAY_SECRET": secret,
        "LIBRARY_RELAY_ENABLED": "0",
    })
    try:
        version = run(["vercel", "--version"], cwd=ROOT, env=child_env,
                      capture_output=True, text=True, timeout=20, check=False)
        require(version.returncode == 0 and bool(re.search(r"(?<![0-9.])64\.2\.0(?![0-9.])", version.stdout + version.stderr)), "cli_version_mismatch")
        with tempfile.TemporaryDirectory(prefix="soulib-relay-preview-") as temporary:
            # No secret is written to configuration, source, artifact or env file.
            config = Path(temporary) / "vercel.json"
            config.write_text(json.dumps({"framework": "flask", "regions": ["icn1"]}), encoding="utf-8")
            args = ["vercel", "deploy", "--yes", "--target=preview", "--regions=icn1", "--local-config", str(config)]
            for name in ("LIBRARY_RELAY_MODE", "LIBRARY_RELAY_SECRET", "LIBRARY_RELAY_ENABLED"):
                # CLI reads the value from its process environment when no '=' is supplied.
                args.extend(["--env", name, "--build-env", name])
            result = run(args, cwd=ROOT, env=child_env, capture_output=True,
                         text=True, timeout=420, check=False)
            require(result.returncode == 0, "cli_deploy_failed")
            return safe_url(result.stdout.strip())
    except subprocess.TimeoutExpired:
        raise inspect.ProbeFailure("cli_timeout") from None
    except OSError:
        raise inspect.ProbeFailure("cli_unavailable") from None


def read_json_response(opener, request, maximum=MAX_ENVELOPE):
    """Unauthenticated preview transport; never attach the Vercel management token."""
    started = time.monotonic()
    try:
        with opener.open(request, timeout=9) as response:
            declared = response.headers.get("Content-Length")
            if declared is not None:
                require(0 <= int(declared) <= maximum, "response_too_large")
            body = response.read(maximum + 1)
            require(len(body) <= maximum, "response_too_large")
            payload = json.loads(body)
            require(isinstance(payload, dict), "invalid_response")
            return response.status, payload, round(time.monotonic() - started, 3)
    except urllib.error.HTTPError as exc:
        status = exc.code if type(exc.code) is int and 300 <= exc.code <= 599 else None
        try:
            raw = exc.read(min(maximum, 8192) + 1)
            payload = json.loads(raw) if len(raw) <= 8192 else {}
        except Exception:
            payload = {}
        finally:
            exc.close()
        payload = payload if isinstance(payload, dict) else {}
        return status, payload, round(time.monotonic() - started, 3)
    except (ValueError, UnicodeError):
        raise inspect.ProbeFailure("invalid_response") from None
    except TimeoutError:
        raise inspect.ProbeFailure("timeout") from None
    except urllib.error.URLError:
        raise inspect.ProbeFailure("network_error") from None


def signed_request(url, secret, code, operation, params):
    payload = {"version": 1, "library_code": code, "operation": operation,
               "params": params, "budget_ms": 4500}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"\n" + body, hashlib.sha256).hexdigest()
    return urllib.request.Request(url + "/internal/library-page", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Library-Relay-Timestamp": timestamp,
        "X-Library-Relay-Signature": signature,
    })


def envelope_page(payload):
    require(set(payload) == {"version", "ok", "upstream_status", "content_type", "body_base64", "region"}, "invalid_response")
    require(type(payload["version"]) is int and payload["version"] == 1
            and payload["ok"] is True and payload["upstream_status"] == 200
            and payload["region"] == "icn1", "invalid_response")
    try:
        raw = base64.b64decode(payload["body_base64"], validate=True)
    except Exception:
        raise inspect.ProbeFailure("invalid_response") from None
    require(len(raw) <= 2 * 1024 * 1024, "response_too_large")
    from live_search.relay import _response, validate_document
    response = _response(raw, payload["content_type"])
    validate_document(response)
    return response


def parse_search(response, code):
    from config import LIBRARIES
    from live_search.connectors.kyobo import KyoboNewConnector
    from live_search.connectors.yes24 import Yes24Connector
    from live_search.relay import ORIGINS, validate_search_document
    if code == "seongbuk":
        results = KyoboNewConnector()._parse_results(response.text, ORIGINS[code], code, LIBRARIES[code])
    else:
        results = Yes24Connector()._parse_results(response.text, ORIGINS[code], code, LIBRARIES[code])
    validate_search_document(response, code, results)
    for result in results:
        identifiers = result.identifiers or {}
        required = "brcd" if code == "seongbuk" else "goods_id"
        if identifiers.get(required):
            return identifiers
    return None


def parse_status(response, code, identifiers):
    from adapters.status_parsers import parse_kyobo_status, parse_yes24_status
    from live_search.relay import yes24_status_html
    if code == "seongbuk":
        return bool(parse_kyobo_status(response.text))
    selected = yes24_status_html(response, "yes24_detail", identifiers["goods_id"])
    return bool(parse_yes24_status(selected, identifiers["goods_id"]))


def page_check(opener, url, secret, code, operation, params):
    record = {"libraryCode": code, "operation": operation, "status": "failed",
              "httpStatus": None, "upstreamStatus": None, "elapsedSeconds": None, "region": "unknown"}
    try:
        status, payload, elapsed = read_json_response(opener, signed_request(url, secret, code, operation, params))
        record.update({"httpStatus": status, "elapsedSeconds": elapsed,
                       "region": "icn1" if payload.get("region") == "icn1" else "unknown"})
        if status != 200:
            error = inspect.enum_value(payload.get("error"), ERRORS)
            record["errorKind"] = "preview_access_denied" if status in (401, 403) and error == "unknown" else error
            return record, None
        response = envelope_page(payload)
        record.update({"status": "ok", "upstreamStatus": 200})
        return record, response
    except inspect.ProbeFailure as exc:
        record["errorKind"] = exc.kind
    except Exception:
        # Parser/transport exception strings can contain book identifiers or URLs.
        record["errorKind"] = "invalid_response"
    return record, None


def check_libraries(opener, url, secret):
    records, found = [], {}
    for code in CODES:
        operation = "kyobo_search" if code == "seongbuk" else "yes24_search"
        params = {"query": FIXED_QUERY, "field": "ctts" if code == "seongbuk" else "title"}
        if code == "seongbuk":
            params["limit"] = 10
        record, response = page_check(opener, url, secret, code, operation, params)
        record["hasIdentifier"] = False
        if response is not None:
            try:
                identifiers = parse_search(response, code)
                record["hasIdentifier"] = bool(identifiers)
                if identifiers:
                    found[code] = identifiers
            except Exception:
                record.update({"status": "failed", "errorKind": "invalid_document"})
        records.append(record)
    # At most two real detail/status requests; each uses an ID returned above.
    for code in list(found)[:2]:
        identifiers = found[code]
        if code == "seongbuk":
            operation = "kyobo_detail"
            params = {name: identifiers.get(name, "") for name in ("brcd", "ctts_dvsn_code", "ctgr_id", "sntn_auth_code")}
        else:
            operation, params = "yes24_detail", {"goods_id": identifiers["goods_id"]}
        record, response = page_check(opener, url, secret, code, operation, params)
        record["hasStatus"] = False
        if response is not None:
            try:
                record["hasStatus"] = parse_status(response, code, identifiers)
            except Exception:
                record.update({"status": "failed", "errorKind": "invalid_document"})
        records.append(record)
    return records


def preview(environ, opener=None, run=subprocess.run, mask=None):
    require(environ.get("GITHUB_ACTIONS") == "true" and environ.get("GITHUB_REPOSITORY") == "pkkong/soulibrary"
            and environ.get("GITHUB_REF") == BRANCH_REF, "ci_context_required")
    token, team_id, project_id = inspect.credentials(environ)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), inspect.NoRedirects())
    before = inspect.request_metadata("project", token, team_id, project_id, opener)
    baseline = production_snapshot(before, team_id, project_id)
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    require(config.get("framework") == "flask" and config.get("regions") == ["iad1"], "source_configuration_changed")
    secret = secrets.token_hex(32)
    if mask:
        mask(secret)
    report = {"mode": "preview", "ok": False, "productionMutationsRequested": False,
              "previewCreated": False, "productionPreserved": False, "records": []}
    try:
        url = deploy_preview(environ, secret, run)
        require(not any(value in url for value in (token, team_id, project_id, secret)), "invalid_deployment_url")
        report.update({"previewCreated": True, "previewUrl": url})
        deployment = inspect.request_metadata("deployment", token, team_id, project_id, opener,
                                              deployment_host=urllib.parse.urlparse(url).hostname)
        existing_id = deployment.get("projectId") or inspect.object_field(deployment, "project").get("id")
        require(existing_id == project_id and deployment.get("target") is None
                and deployment.get("readyState") == "READY", "preview_identity_mismatch")
        require(inspect.allowed_regions(deployment.get("regions")) == ["icn1"], "preview_region_mismatch")
        report["previewIdentityVerified"] = True
        request = urllib.request.Request(url + "/health", method="GET")
        status, health, _ = read_json_response(opener, request, maximum=8192)
        require(status == 200 and health.get("ok") is True and health.get("mode") == "library-relay"
                and health.get("region") == "icn1", "preview_health_or_access_failed")
        report["invocationRegion"] = "icn1"
        sys.path.insert(0, str(ROOT / "web"))
        report["records"] = check_libraries(opener, url, secret)
        verified_search = {row["libraryCode"] for row in report["records"] if row.get("hasIdentifier") and row["status"] == "ok" and row["region"] == "icn1"}
        verified_status = {row["libraryCode"] for row in report["records"] if row.get("hasStatus") and row["status"] == "ok" and row["region"] == "icn1"}
        report["readyForSelectiveRelay"] = set(REQUIRED_CODES) <= verified_search & verified_status
        report["allFourSearchesRecovered"] = set(CODES) <= verified_search
    except inspect.ProbeFailure as exc:
        report["errorKind"] = exc.kind
    except Exception:
        report["errorKind"] = "unexpected_error"
    finally:
        try:
            after = inspect.request_metadata("project", token, team_id, project_id, opener)
            report["productionPreserved"] = production_snapshot(after, team_id, project_id) == baseline
        except Exception:
            report["productionVerificationError"] = "verification_failed"
    report["ok"] = bool(report["productionPreserved"] and report.get("readyForSelectiveRelay") and not report.get("errorKind"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "preview"), default="inspect")
    args = parser.parse_args()
    try:
        if args.mode == "inspect":
            report = inspect.probe(os.environ)
        else:
            report = preview(os.environ, mask=lambda value: print("::add-mask::" + value, flush=True))
    except inspect.ProbeFailure as exc:
        report = {"ok": False, "mode": args.mode, "errorKind": exc.kind, "productionMutationsRequested": False}
    except Exception:
        report = {"ok": False, "mode": args.mode, "errorKind": "unexpected_error", "productionMutationsRequested": False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
