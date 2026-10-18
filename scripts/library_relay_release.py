#!/usr/bin/env python3
"""Create and test one isolated preview using existing CI credentials.

Default mode only inspects metadata. Preview mode never modifies production.
Manual prepare/activate/disable only update four production relay variables;
none of these modes deploys production or changes project/protection settings.
Retain adds one fixed non-production alias without a production deploy or settings change.
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
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import library_connectivity_probe as inspect


ROOT = Path(__file__).resolve().parents[1]
BRANCH_REF = "refs/heads/codex/library-connectivity-recovery"
CLI_VERSION = "64.2.0"
CODES = ("seongbuk", "yeongdeungpo", "songpa_owned", "gangseo")
REQUIRED_CODES = CODES[:2]
STATUS_CODES = (*REQUIRED_CODES, "gangseo")
STAGED_CODE_VALUES = ("seongbuk,yeongdeungpo", "seongbuk,yeongdeungpo,gangseo")
RETAIN_ALIAS = "soulib-library-relay.vercel.app"
MAIN_REF = "refs/heads/main"
PRODUCTION_KEYS = frozenset({"LIBRARY_RELAY_URL", "LIBRARY_RELAY_SECRET", "LIBRARY_RELAY_CODES", "LIBRARY_RELAY_ENABLED"})
FIXED_QUERY = "프로젝트 헤일메리"
MAX_ENVELOPE = 3 * 1024 * 1024
ERRORS = frozenset({
    "configuration", "authentication", "invalid_request", "budget_exhausted",
    "transport_error", "upstream_http", "redirect", "body_too_large",
    "invalid_document", "invalid_response", "busy",
})
CLI_FAILURE_PATTERNS = (
    ("cli_invalid_token", r"invalid[_ -]token|token[^\n]{0,100}(?:not valid|invalid|expired|revoked)|(?:invalid|expired|revoked)[^\n]{0,80}token"),
    ("cli_authentication_required", r"no existing credentials|no credentials|authentication[_ -]required|missing[_ -]credentials|not authenticated"),
    ("cli_unknown_option", r"unknown (?:or unexpected )?(?:option|argument)|unexpected (?:option|argument)|unrecognized (?:option|argument)"),
    ("cli_environment_missing", r"no value specified for env variable|environment variable[^\n]{0,80}(?:missing|required|not found)"),
    ("cli_invalid_target", r"anonymous deployments always target production|(?:invalid|unknown)[^\n]{0,50}(?:target|environment)|(?:target|environment)[^\n]{0,100}(?:not available|does not exist|not found)|not a valid target directory"),
    ("cli_incompatible_options", r"(?:cannot|can't|can not)[^\n]{0,30}(?:combine|use)[^\n]{0,120}--|must be used (?:with|without)|mutually exclusive|incompatible[^\n]{0,60}(?:flag|option)|(?:flag|option)[^\n]{0,60}incompatible"),
    ("cli_git_author_access", r"git (?:commit )?author[^\n]{0,160}(?:access|member|team|permission)|commit author[^\n]{0,160}(?:access|team|permission)"),
    ("cli_scope_error", r"(?:team|scope)[^\n]{0,100}(?:not found|does not exist|not have access|not authorized|permission)|(?:not have access|not authorized)[^\n]{0,100}(?:team|scope)|team_not_found|scope_not_found"),
    ("cli_project_access", r"could not retrieve project settings|project[^\n]{0,100}(?:not found|does not exist|access|permission)|not authorized|not permitted|forbidden|insufficient_scope"),
    ("cli_project_unlinked", r"no linked project found|not linked to (?:a |an )?project|not linked to a vercel project|run[^\n]{0,40}vercel link"),
    ("cli_deploy_limit", r"rate[_ -]?limit|too many requests|too many deployments|deployment[_ -]limit|no more than [0-9]+[^\n]{0,50}functions|exceeded[^\n]{0,100}(?:limit|quota)|limit[^\n]{0,80}(?:exceeded|reached)"),
    ("cli_region_unsupported", r"(?:invalid|unsupported|not supported)[^\n]{0,80}region|region[^\n]{0,80}(?:not available|not supported|invalid|not allowed)"),
    ("cli_configuration_error", r"couldn't (?:find|parse)[^\n]{0,100}(?:config|json)|invalid[^\n]{0,80}(?:configuration|vercel\.json|config)|(?:vercel\.json|configuration)[^\n]{0,100}(?:invalid|error|not found)|must be (?:inside|within)|outside (?:the )?project|(?:path|directory)[^\n]{0,100}does not exist"),
    ("cli_build_failed", r"build[^\n]{0,80}(?:failed|error)|(?:failed|error)[^\n]{0,80}(?:build|compile)|command[^\n]{0,100}exited with"),
    ("cli_network_error", r"econnreset|econnrefused|enotfound|etimedout|fetch failed|network error|request timed out|certificate[^\n]{0,80}(?:invalid|expired|verify)"),
)


class CliDeployFailure(inspect.ProbeFailure):
    def __init__(self, kind, details):
        super().__init__(kind)
        self.details = details  # Already allowlisted and redacted; never raw output.


def require(condition, kind):
    if not condition:
        raise inspect.ProbeFailure(kind)


def manual_context(environ, ref):
    require(environ.get("GITHUB_ACTIONS") == "true"
            and environ.get("GITHUB_REPOSITORY") == "pkkong/soulibrary"
            and environ.get("GITHUB_REF") == ref
            and environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "ci_context_required")


def production_env(action, token, team_id, project_id, opener, key=None, value=None):
    """Fixed project env endpoint; return metadata only, never decrypted values.

    Contracts: vercel.com/docs/rest-api/projects/create-one-or-more-environment-variables
               vercel.com/docs/rest-api/projects/retrieve-the-environment-variables-of-a-project-by-id-or-name
    """
    inspect.credentials({"VERCEL_TOKEN": token, "VERCEL_ORG_ID": team_id, "VERCEL_PROJECT_ID": project_id})
    require(action in ("list", "upsert"), "invalid_env_operation")
    query = {"teamId": team_id, "decrypt": "false"} if action == "list" else {"teamId": team_id, "upsert": "true"}
    data = None
    if action == "upsert":
        require(key in PRODUCTION_KEYS and isinstance(value, str), "invalid_env_operation")
        valid = ((key == "LIBRARY_RELAY_ENABLED" and value in ("0", "1"))
                 or (key == "LIBRARY_RELAY_CODES" and value in STAGED_CODE_VALUES)
                 or (key == "LIBRARY_RELAY_SECRET" and bool(re.fullmatch(r"[0-9a-f]{64}", value)))
                 or (key == "LIBRARY_RELAY_URL" and safe_url(value) == value))
        require(valid, "invalid_env_value")
        data = json.dumps({"key": key, "value": value, "type": "encrypted", "target": ["production"]}).encode("utf-8")
    else:
        require(key is None and value is None, "invalid_env_operation")
    url = f"{inspect.API_ORIGIN}/v10/projects/{project_id}/env?{urllib.parse.urlencode(query)}"
    request = urllib.request.Request(url, data=data, method="GET" if data is None else "POST", headers={
        "Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": "soulib-relay-release/1.0",
    })
    try:
        with opener.open(request, timeout=inspect.TIMEOUT_SECONDS) as response:
            if response.status != (200 if action == "list" else 201):
                status = response.status if type(response.status) is int and 100 <= response.status <= 599 else None
                raise inspect.ProbeFailure("env_unexpected_status", status)
            declared = response.headers.get("Content-Length")
            if declared is not None:
                require(0 <= int(declared) <= inspect.MAX_RESPONSE_BYTES, "env_response_too_large")
            raw = response.read(inspect.MAX_RESPONSE_BYTES + 1)
            require(len(raw) <= inspect.MAX_RESPONSE_BYTES, "env_response_too_large")
            payload = json.loads(raw)
        if action == "list":
            rows = payload.get("envs") if isinstance(payload, dict) else payload
            require(isinstance(rows, list), "env_invalid_response")
        else:
            require(isinstance(payload, dict) and payload.get("failed") == [], "env_upsert_failed")
            created = payload.get("created")
            rows = created if isinstance(created, list) else [created]
            require(len(rows) == 1, "env_invalid_response")
        metadata = []
        for row in rows:
            require(isinstance(row, dict) and isinstance(row.get("key"), str), "env_invalid_response")
            # Deliberately discard value, legacyValue, vsmValue, content hints and IDs.
            metadata.append({name: row.get(name) for name in ("key", "type", "target", "gitBranch", "customEnvironmentIds", "system")})
        if action == "upsert":
            require(metadata[0]["key"] == key and production_row(metadata[0]), "env_upsert_unverified")
        return metadata
    except urllib.error.HTTPError as exc:
        status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        exc.close()
        raise inspect.ProbeFailure("env_http_error", status) from None
    except TimeoutError:
        raise inspect.ProbeFailure("env_timeout") from None
    except urllib.error.URLError:
        raise inspect.ProbeFailure("env_network_error") from None
    except (ValueError, UnicodeError):
        raise inspect.ProbeFailure("env_invalid_response") from None


def production_row(row):
    return (row.get("type") == "encrypted" and row.get("target") == ["production"]
            and not row.get("gitBranch") and not row.get("customEnvironmentIds") and not row.get("system"))


def prepared_keys(metadata, required=False):
    selected = {}
    for row in metadata:
        target = row.get("target")
        require(isinstance(target, list), "env_invalid_metadata")
        if "production" not in target:
            continue
        require(row["key"] != "LIBRARY_RELAY_MODE", "production_relay_mode_present")
        if row["key"] in PRODUCTION_KEYS:
            require(row["key"] not in selected and production_row(row), "env_scope_conflict")
            selected[row["key"]] = row
    require(not required or set(selected) == PRODUCTION_KEYS, "production_config_not_prepared")
    return selected


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


def cli_failure_kind(stdout, stderr, private_values=()):
    """Only fixed enums may leave this boundary, never raw/sanitized excerpts."""
    value = str(stdout or "") + "\n" + str(stderr or "")
    for private in private_values:
        if private:
            value = value.replace(private, "<redacted>")
    if len(value) > 1024 * 1024:
        value = value[:512 * 1024] + "\n" + value[-512 * 1024:]
    # Color and control bytes should not split fixed diagnostic phrases.
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    for kind, pattern in CLI_FAILURE_PATTERNS:
        if re.search(pattern, value, re.I):
            return kind
    return "cli_deploy_failed"


def cli_private_values(environ, secret):
    values = [secret]
    for name, value in environ.items():
        if name in ("VERCEL_ORG_ID", "VERCEL_PROJECT_ID") or re.search(r"TOKEN|SECRET|KEY|PASS|AUTH", name, re.I):
            if isinstance(value, str) and value:
                values.append(value)
    return tuple(sorted(set(values), key=len, reverse=True))


def cli_failure_details(stdout, stderr, return_code, private_values):
    """Expose at most one safe error sentence, never arbitrary CLI output."""
    raw = str(stdout or "") + "\n" + str(stderr or "")
    details = {"cliReturnCode": return_code if type(return_code) is int and -255 <= return_code <= 255 else None,
               "cliOutputChars": len(raw)}
    private_pattern = re.compile("|".join(re.escape(value) for value in private_values if value)) if any(private_values) else None

    def redact_private(value):
        return private_pattern.sub("<redacted>", value) if private_pattern else value

    value = redact_private(raw)
    value = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-_])", "", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(char for char in value if char == "\n" or not unicodedata.category(char).startswith("C"))
    value = redact_private(value)
    if len(value) > 1024 * 1024:
        value = value[:512 * 1024] + "\n" + value[-512 * 1024:]
    for line in value.splitlines():
        match = re.fullmatch(r"\s*(?:>\s*)?(?:error\s*:|\[error\]\s*:?)\s*(.{1,2000})", line, re.I)
        if not match:
            continue
        candidate = match.group(1).strip()
        # Error-prefixed documents, environment dumps and source are still not diagnostics.
        if (candidate.startswith(("{", "[", "```")) or "{" in candidate or "}" in candidate
                or re.search(r"</?(?!(?:redacted|url|email|query)>)[A-Za-z][A-Za-z0-9:_-]*(?:\s[^>]*)?/?>|<!|<\?", candidate, re.I)
                or re.search(r"\b[A-Z_][A-Z0-9_]{2,}\s*=", candidate)
                or re.search(r"process\.env|os\.environ|environment(?: variables)?\s*[:={]", candidate, re.I)
                or re.search(r"^(?:def|class|function|const|let|var|import|from|raise|return)\s|^[A-Za-z_]\w*\(", candidate)):
            continue
        candidate = re.sub(r"\b[A-Za-z][A-Za-z0-9+.-]{1,20}://[^\s<>\"']+", "<url>", candidate)
        candidate = re.sub(r"\b(?:eyJ[A-Za-z0-9_-]*|[A-Za-z0-9_-]{8,})\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "<redacted>", candidate)
        candidate = re.sub(r"[^\s<>\"']+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", candidate)
        candidate = re.sub(r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::[0-9]+)?(?:[/?#][^\s<>\"']*)?", "<url>", candidate)
        candidate = re.sub(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])", "<redacted>", candidate)
        candidate = re.sub(r"[?&][^\s<>\"']+", "<query>", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if candidate:
            details["cliDiagnostic"] = candidate[:400]
            break
    return details


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
            if result.returncode != 0:
                private = cli_private_values(environ, secret)
                details = cli_failure_details(result.stdout, result.stderr, result.returncode, private)
                raise CliDeployFailure(cli_failure_kind(result.stdout, result.stderr, private), details)
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
    # At most three real details, only for required codes and optional Gangseo.
    # Every status uses the identifier returned by that library's search.
    for code in STATUS_CODES:
        if code not in found:
            continue
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


def preview(environ, opener=None, run=subprocess.run, mask=None, mode="preview"):
    require(mode in ("preview", "prepare"), "invalid_release_mode")
    manual_context(environ, BRANCH_REF)
    token, team_id, project_id = inspect.credentials(environ)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), inspect.NoRedirects())
    before = inspect.request_metadata("project", token, team_id, project_id, opener)
    baseline = production_snapshot(before, team_id, project_id)
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    require(config.get("framework") == "flask" and config.get("regions") == ["iad1"], "source_configuration_changed")
    secret = secrets.token_hex(32)
    if mask:
        mask(secret)
    report = {"mode": mode, "ok": False, "productionMutationsRequested": False,
              "previewCreated": False, "productionPreserved": False, "records": []}
    if mode == "prepare":
        report.update({"productionConfigPrepared": False, "productionDeploymentRequested": False,
                       "requiresProductionDeployment": True, "effectiveProductionRecoveryVerified": False})
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
        if mode == "prepare":
            require(report["readyForSelectiveRelay"], "relay_verification_failed")
            staged_codes = STAGED_CODE_VALUES[1] if "gangseo" in verified_search & verified_status else STAGED_CODE_VALUES[0]
            # Re-check current production immediately before the first config write.
            current = inspect.request_metadata("project", token, team_id, project_id, opener)
            require(production_snapshot(current, team_id, project_id) == baseline, "production_changed_before_prepare")
            prepared_keys(production_env("list", token, team_id, project_id, opener))
            report["productionMutationsRequested"] = True
            # A partially completed preparation remains disabled for every new deployment.
            production_env("upsert", token, team_id, project_id, opener, "LIBRARY_RELAY_ENABLED", "0")
            report["productionConfigDisabled"] = True
            for key, value in (("LIBRARY_RELAY_URL", url), ("LIBRARY_RELAY_SECRET", secret),
                               ("LIBRARY_RELAY_CODES", staged_codes)):
                production_env("upsert", token, team_id, project_id, opener, key, value)
            prepared_keys(production_env("list", token, team_id, project_id, opener), required=True)
            report["productionConfigPrepared"] = True
            report["preparedRelayCodes"] = staged_codes.split(",")
    except inspect.ProbeFailure as exc:
        report["errorKind"] = exc.kind
        if exc.status is not None:
            report["errorHttpStatus"] = exc.status
        if isinstance(exc, CliDeployFailure):
            report.update(exc.details)
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


def toggle(environ, mode, opener=None):
    """Stage one production switch; applying it requires a separate deployment."""
    require(mode in ("activate", "disable"), "invalid_release_mode")
    manual_context(environ, MAIN_REF)
    token, team_id, project_id = inspect.credentials(environ)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), inspect.NoRedirects())
    before = inspect.request_metadata("project", token, team_id, project_id, opener)
    baseline = production_snapshot(before, team_id, project_id)
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    require(config.get("framework") == "flask" and config.get("regions") == ["iad1"], "source_configuration_changed")
    report = {"mode": mode, "ok": False, "productionMutationsRequested": False,
              "productionDeploymentRequested": False, "productionPreserved": False,
              "requiresProductionDeployment": True, "effectiveProductionRecoveryVerified": False}
    try:
        metadata = production_env("list", token, team_id, project_id, opener)
        prepared_keys(metadata, required=mode == "activate")
        report["productionMutationsRequested"] = True
        production_env("upsert", token, team_id, project_id, opener, "LIBRARY_RELAY_ENABLED", "1" if mode == "activate" else "0")
        prepared_keys(production_env("list", token, team_id, project_id, opener), required=mode == "activate")
        report["productionConfigEnabledForNextDeployment"] = mode == "activate"
    except inspect.ProbeFailure as exc:
        report["errorKind"] = exc.kind
        if exc.status is not None:
            report["errorHttpStatus"] = exc.status
    except Exception:
        report["errorKind"] = "unexpected_error"
    finally:
        try:
            after = inspect.request_metadata("project", token, team_id, project_id, opener)
            report["productionPreserved"] = production_snapshot(after, team_id, project_id) == baseline
        except Exception:
            report["productionVerificationError"] = "verification_failed"
    report["ok"] = bool(report["productionPreserved"] and "productionConfigEnabledForNextDeployment" in report and not report.get("errorKind"))
    return report


def relay_alias(action, token, team_id, project_id, opener, deployment_id=None):
    """Only inspect the fixed alias or assign it to a verified deployment ID.

    Contracts: vercel.com/docs/rest-api/aliases/{get-an-alias,assign-an-alias}
    """
    inspect.credentials({"VERCEL_TOKEN": token, "VERCEL_ORG_ID": team_id, "VERCEL_PROJECT_ID": project_id})
    require(action in ("get", "assign"), "invalid_alias_operation")
    data = None
    if action == "assign":
        require(isinstance(deployment_id, str) and bool(re.fullmatch(r"dpl_[A-Za-z0-9]{1,128}", deployment_id)), "invalid_alias_deployment")
        path = f"/v2/deployments/{deployment_id}/aliases"
        data = json.dumps({"alias": RETAIN_ALIAS}).encode("utf-8")
    else:
        require(deployment_id is None, "invalid_alias_operation")
        path = f"/v4/aliases/{RETAIN_ALIAS}"
    url = inspect.API_ORIGIN + path + "?" + urllib.parse.urlencode({"teamId": team_id})
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers={
        "Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json",
    })
    try:
        with opener.open(request, timeout=inspect.TIMEOUT_SECONDS) as response:
            if response.status != 200:
                status = response.status if type(response.status) is int and 100 <= response.status <= 599 else None
                raise inspect.ProbeFailure("alias_unexpected_status", status)
            declared = response.headers.get("Content-Length")
            if declared is not None:
                require(0 <= int(declared) <= inspect.MAX_RESPONSE_BYTES, "alias_response_too_large")
            raw = response.read(inspect.MAX_RESPONSE_BYTES + 1)
            require(len(raw) <= inspect.MAX_RESPONSE_BYTES, "alias_response_too_large")
            payload = json.loads(raw)
        require(isinstance(payload, dict) and payload.get("alias") == RETAIN_ALIAS, "alias_invalid_response")
        # Creator details, bypass settings, certificates and raw IDs never leave a report.
        return {name: payload.get(name) for name in ("alias", "projectId", "deploymentId", "oldDeploymentId", "redirect", "deletedAt")}
    except urllib.error.HTTPError as exc:
        status = exc.code if type(exc.code) is int and 100 <= exc.code <= 599 else None
        exc.close()
        if action == "get" and status == 404:
            return None
        raise inspect.ProbeFailure("alias_http_error", status) from None
    except TimeoutError:
        raise inspect.ProbeFailure("alias_timeout") from None
    except urllib.error.URLError:
        raise inspect.ProbeFailure("alias_network_error") from None
    except (ValueError, UnicodeError):
        raise inspect.ProbeFailure("alias_invalid_response") from None


def retain(environ, relay_url, opener=None):
    """Retain one existing non-production relay by adding one fixed custom alias."""
    manual_context(environ, MAIN_REF)
    url = safe_url(relay_url)
    require(url != "https://" + RETAIN_ALIAS, "immutable_relay_url_required")
    token, team_id, project_id = inspect.credentials(environ)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), inspect.NoRedirects())
    before = inspect.request_metadata("project", token, team_id, project_id, opener)
    baseline = production_snapshot(before, team_id, project_id)
    report = {"mode": "retain", "ok": False, "productionMutationsRequested": False,
              "productionDeploymentRequested": False, "aliasMutationRequested": False,
              "retentionExceptionVerified": False, "productionPreserved": False}
    try:
        deployment = inspect.request_metadata("deployment", token, team_id, project_id, opener,
                                              deployment_host=urllib.parse.urlparse(url).hostname)
        deployment_id = deployment.get("id") or deployment.get("uid")
        require((deployment.get("projectId") or inspect.object_field(deployment, "project").get("id")) == project_id
                and deployment.get("target") is None and deployment.get("readyState") == "READY"
                and inspect.allowed_regions(deployment.get("regions")) == ["icn1"]
                and isinstance(deployment_id, str) and bool(re.fullmatch(r"dpl_[A-Za-z0-9]{1,128}", deployment_id))
                and deployment_id != baseline["targetId"]
                and RETAIN_ALIAS not in (baseline["targetAliases"] or [])
                and RETAIN_ALIAS != baseline["targetUrl"], "relay_identity_mismatch")
        status, health, _ = read_json_response(opener, urllib.request.Request(url + "/health"), maximum=8192)
        require(status == 200 and health.get("ok") is True and health.get("mode") == "library-relay"
                and health.get("region") == "icn1", "relay_health_or_access_failed")
        existing = relay_alias("get", token, team_id, project_id, opener)
        if existing is not None:
            require(existing["projectId"] == project_id and existing["deploymentId"] == deployment_id
                    and not existing["redirect"] and not existing["deletedAt"], "alias_target_conflict")
        else:
            current = inspect.request_metadata("project", token, team_id, project_id, opener)
            require(production_snapshot(current, team_id, project_id) == baseline, "production_changed_before_retain")
            report["aliasMutationRequested"] = True
            assigned = relay_alias("assign", token, team_id, project_id, opener, deployment_id)
            require(assigned["oldDeploymentId"] in (None, deployment_id), "alias_previous_target_conflict")
        verified = relay_alias("get", token, team_id, project_id, opener)
        require(verified is not None and verified["projectId"] == project_id and verified["deploymentId"] == deployment_id
                and not verified["redirect"] and not verified["deletedAt"], "alias_verification_failed")
        status, health, _ = read_json_response(opener, urllib.request.Request("https://" + RETAIN_ALIAS + "/health"), maximum=8192)
        require(status == 200 and health.get("ok") is True and health.get("mode") == "library-relay"
                and health.get("region") == "icn1", "alias_health_or_access_failed")
        report.update({"retentionExceptionVerified": True, "retainedAlias": RETAIN_ALIAS})
    except inspect.ProbeFailure as exc:
        report["errorKind"] = exc.kind
        if exc.status is not None:
            report["errorHttpStatus"] = exc.status
    except Exception:
        report["errorKind"] = "unexpected_error"
    finally:
        try:
            after = inspect.request_metadata("project", token, team_id, project_id, opener)
            report["productionPreserved"] = production_snapshot(after, team_id, project_id) == baseline
        except Exception:
            report["productionVerificationError"] = "verification_failed"
    report["ok"] = bool(report["productionPreserved"] and report["retentionExceptionVerified"] and not report.get("errorKind"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "preview", "prepare", "activate", "disable", "retain"), default="inspect")
    parser.add_argument("--relay-url", default="", help="Existing immutable relay preview URL; retain mode only")
    args = parser.parse_args()
    try:
        require(args.mode == "retain" or not args.relay_url, "unexpected_relay_url")
        if args.mode == "inspect":
            report = inspect.probe(os.environ)
        elif args.mode in ("preview", "prepare"):
            report = preview(os.environ, mode=args.mode, mask=lambda value: print("::add-mask::" + value, flush=True))
        elif args.mode == "retain":
            report = retain(os.environ, args.relay_url)
        else:
            report = toggle(os.environ, args.mode)
    except inspect.ProbeFailure as exc:
        report = {"ok": False, "mode": args.mode, "errorKind": exc.kind, "productionMutationsRequested": False}
    except Exception:
        report = {"ok": False, "mode": args.mode, "errorKind": "unexpected_error", "productionMutationsRequested": False}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
