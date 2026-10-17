#!/usr/bin/env python3
"""Read existing Vercel metadata without exposing API responses or credentials.

This intentionally does not retrieve environment variables, deploy, modify project
settings, or probe upstream libraries. The token remains inside the CI process.
API contracts: https://vercel.com/docs/rest-api/projects/find-a-project-by-id-or-name
              https://vercel.com/docs/rest-api/teams/get-a-team
"""

import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request


API_ORIGIN = "https://api.vercel.com"
TIMEOUT_SECONDS = 12
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
PLANS = frozenset({"hobby", "pro", "enterprise"})
FRAMEWORKS = frozenset({"flask", "other"})
REGIONS = frozenset({
    "arn1", "bom1", "cdg1", "cle1", "cpt1", "dub1", "dxb1", "fra1",
    "gru1", "hkg1", "hnd1", "iad1", "icn1", "kix1", "lhr1", "pdx1",
    "sfo1", "sin1", "syd1", "yul1",
})


class ProbeFailure(Exception):
    """Carry only a fixed, public error category, never an upstream message."""

    def __init__(self, kind, status=None):
        super().__init__(kind)
        self.kind = kind
        self.status = status


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def credentials(environ):
    token = environ.get("VERCEL_TOKEN", "")
    team_id = environ.get("VERCEL_ORG_ID", "")
    project_id = environ.get("VERCEL_PROJECT_ID", "")
    if not token or len(token) > 4096 or any(char.isspace() for char in token):
        raise ProbeFailure("invalid_credentials")
    if not re.fullmatch(r"team_[A-Za-z0-9]{1,128}", team_id):
        raise ProbeFailure("invalid_credentials")
    if not re.fullmatch(r"prj_[A-Za-z0-9]{1,128}", project_id):
        raise ProbeFailure("invalid_credentials")
    return token, team_id, project_id


def request_metadata(resource, token, team_id, project_id, opener, deployment_host=None):
    # No caller-provided URLs, extra query arguments, redirects, or proxy envs.
    if resource == "project":
        url = f"{API_ORIGIN}/v9/projects/{project_id}?{urllib.parse.urlencode({'teamId': team_id})}"
    elif resource == "team":
        url = f"{API_ORIGIN}/v2/teams/{team_id}"
    elif resource == "deployment" and isinstance(deployment_host, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]*\.vercel\.app", deployment_host):
        url = f"{API_ORIGIN}/v13/deployments/{deployment_host}?{urllib.parse.urlencode({'teamId': team_id})}"
    else:
        raise ProbeFailure("invalid_resource")
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "soulib-connectivity-inspect/1.0"},
        method="GET",
    )
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise ProbeFailure("unexpected_status")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except ValueError:
                    raise ProbeFailure("invalid_response") from None
                if declared_size < 0 or declared_size > MAX_RESPONSE_BYTES:
                    raise ProbeFailure("response_too_large")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProbeFailure("response_too_large")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ProbeFailure("invalid_response")
            return payload
    except urllib.error.HTTPError as exc:
        status = exc.code if type(exc.code) is int and 300 <= exc.code <= 599 else None
        exc.close()
        raise ProbeFailure("http_error", status) from None
    except (TimeoutError, socket.timeout):
        raise ProbeFailure("timeout") from None
    except urllib.error.URLError:
        raise ProbeFailure("network_error") from None
    except (ValueError, UnicodeError):
        raise ProbeFailure("invalid_response") from None


def allowed_regions(value):
    if not isinstance(value, list) or any(not isinstance(item, str) or item not in REGIONS for item in value):
        return None
    return sorted(set(value))


def object_field(payload, name):
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def enum_value(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def protection_state(payload, name):
    """Report configuration presence, without guessing missing API fields are off."""
    if name not in payload:
        return "unknown"
    value = payload[name]
    if value is None:
        return "disabled"
    if not isinstance(value, dict):
        return "unknown"
    deployment_type = value.get("deploymentType")
    if enum_value(deployment_type, {"all", "preview", "prod_deployment_urls_and_all_previews", "all_except_custom_domains"}) != "unknown":
        return "enabled"
    return "unknown"


def summarize_project(payload, team_id, project_id):
    production = object_field(object_field(payload, "targets"), "production")
    states = {
        name: protection_state(payload, source)
        for name, source in (("vercelAuthentication", "ssoProtection"), ("password", "passwordProtection"), ("trustedIdentity", "passport"))
    }
    if "enabled" in states.values():
        overall = "enabled"
    elif all(state == "disabled" for state in states.values()):
        overall = "disabled"
    else:
        overall = "unknown"
    return {
        "existingProjectMatches": payload.get("id") == project_id,
        "existingTeamMatches": payload.get("accountId") == team_id,
        "framework": enum_value(payload.get("framework"), FRAMEWORKS),
        "projectDefaultRegions": allowed_regions(object_field(payload, "resourceConfig").get("functionDefaultRegions")),
        "productionDeploymentPresent": bool(production),
        "productionConfiguredRegions": allowed_regions(production.get("regions")),
        "productionExecutionRegionVerified": False,
        "previewProtection": {"state": overall, "methods": states},
    }


def probe(environ, opener=None):
    token, team_id, project_id = credentials(environ)
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects())
    report = {"mode": "read_only", "mutationsPerformed": False, "project": {}, "team": {}}
    success = True
    for resource in ("project", "team"):
        try:
            payload = request_metadata(resource, token, team_id, project_id, opener)
            if resource == "project":
                summary = summarize_project(payload, team_id, project_id)
                success = success and summary["existingProjectMatches"] and summary["existingTeamMatches"]
            else:
                plan = object_field(payload, "billing").get("plan")
                summary = {"existingTeamMatches": payload.get("id") == team_id, "plan": enum_value(plan, PLANS)}
                success = success and summary["existingTeamMatches"]
            report[resource] = {"access": "ok", **summary}
        except ProbeFailure as exc:
            report[resource] = {"access": "failed", "errorKind": exc.kind, "httpStatus": exc.status}
            success = False
    report["ok"] = bool(success)
    return report


def main():
    try:
        report = probe(os.environ)
    except ProbeFailure as exc:
        report = {"ok": False, "mode": "read_only", "mutationsPerformed": False, "errorKind": exc.kind}
    except Exception:
        # Even exception repr/traceback can contain URLs, response bodies or tokens.
        report = {"ok": False, "mode": "read_only", "mutationsPerformed": False, "errorKind": "unexpected_error"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
