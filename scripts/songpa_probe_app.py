"""Single-use authenticated fixed-site probe; never returns pages or secrets."""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
import time

from flask import Flask, jsonify, request


BODY = b'{"version":1}'
HOST = "ebook.splib.or.kr"
EXPECTED_ADDRESS = "218.153.155.12"
BUDGET_SECONDS = 15
MAX_BODY = 2 * 1024 * 1024
PHASES = frozenset({"connection", "dns", "tcp", "tls", "http_headers", "body"})
ERRORS = frozenset({"timeout", "dns_error", "tls_error", "connection_error", "network_error", "body_too_large", "other"})
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024
_lock, _used = threading.Lock(), False


def _region():
    return "icn1" if os.environ.get("VERCEL_REGION") == "icn1" else "unknown"


def _event_payload(raw):
    """Rebuild an allowlisted summary, ignoring all arbitrary child output."""
    events, versions, done = [], {}, None
    for line in raw[:32768].splitlines()[:64]:
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                continue
            if event.get("kind") == "versions":
                versions = {key: value for key, value in event.items() if key in ("python", "requests", "urllib3")
                            and isinstance(value, str) and re.fullmatch(r"[0-9.]{1,32}", value)}
                continue
            if event.get("kind") == "done" and type(event.get("success")) is bool:
                done = event["success"]
                continue
            phase, state, elapsed = event.get("phase"), event.get("state"), event.get("elapsedSeconds")
            if phase not in PHASES or state not in ("started", "ok", "failed") or type(elapsed) not in (int, float) or not 0 <= elapsed <= 60:
                continue
            safe = {"phase": phase, "state": state, "elapsedSeconds": round(elapsed, 6)}
            if event.get("errorKind") in ERRORS:
                safe["errorKind"] = event["errorKind"]
            for key in ("ipv4Count", "ipv6Count", "bodyBytes"):
                if type(event.get(key)) is int and 0 <= event[key] <= MAX_BODY:
                    safe[key] = event[key]
            if type(event.get("sameExpectedAddress")) is bool:
                safe["sameExpectedAddress"] = event["sameExpectedAddress"]
            if event.get("tlsVersion") in ("TLSv1.2", "TLSv1.3"):
                safe["tlsVersion"] = event["tlsVersion"]
            if type(event.get("httpStatus")) is int and 100 <= event["httpStatus"] <= 599:
                safe["httpStatus"] = event["httpStatus"]
            events.append(safe)
        except (ValueError, TypeError):
            continue
    return events, versions, done


def diagnose(run=subprocess.run):
    started, timed_out = time.monotonic(), False
    # No management token, HMAC, cookies or proxy env reaches the worker.
    child_env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.pathsep.join(sys.path), "PYTHONUNBUFFERED": "1"}
    if os.environ.get("LD_LIBRARY_PATH"):
        # Lambda's Python/native extensions may need the existing runtime loader path.
        child_env["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"]
    try:
        result = run([sys.executable, os.path.abspath(__file__), "--worker"], env=child_env,
                     capture_output=True, timeout=BUDGET_SECONDS, check=False)
        raw = result.stdout if isinstance(result.stdout, bytes) else b""
    except subprocess.TimeoutExpired as exc:
        # subprocess.run kills and waits for the child before raising.
        raw, timed_out = exc.stdout or b"", True
    except OSError:
        raw = b""
    phases, versions, done = _event_payload(raw)
    return {"diagnosticComplete": bool(phases), "requestSucceeded": done is True and not timed_out,
            "outcome": "budget_exhausted" if timed_out else "request_completed" if done else "request_failed" if done is False else "probe_failed",
            "elapsedSeconds": round(time.monotonic() - started, 3), "phases": phases, "versions": versions}


@app.get("/health")
def health():
    return jsonify({"ok": True, "mode": "songpa-probe", "region": _region()})


@app.post("/diagnose")
def probe():
    global _used
    body = request.get_data(cache=False)
    timestamp, supplied = request.headers.get("X-Songpa-Probe-Timestamp", ""), request.headers.get("X-Songpa-Probe-Signature", "")
    secret = os.environ.get("SONGPA_PROBE_SECRET", "")
    if not re.fullmatch(r"[a-f0-9]{64}", secret):
        return jsonify({"ok": False, "errorKind": "configuration"}), 503
    if request.query_string or body != BODY or not re.fullmatch(r"[0-9]{10}", timestamp) or abs(time.time() - int(timestamp)) > 60:
        return jsonify({"ok": False, "errorKind": "invalid_request"}), 400
    expected = hmac.new(secret.encode(), timestamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(expected, supplied):
        return jsonify({"ok": False, "errorKind": "authentication"}), 401
    with _lock:
        if _used:
            return jsonify({"ok": False, "errorKind": "already_used"}), 409
        _used = True
    return jsonify({"ok": True, "mode": "songpa-probe", "region": _region(), **diagnose()})


def _worker():
    """Observe original transport calls; do not change their arguments/results."""
    import socket
    import ssl
    from unittest.mock import patch
    from urllib.parse import urlencode
    import requests
    import urllib3
    import urllib3.connection as connection
    import urllib3.util.connection as util_connection

    def emit(value):
        print(json.dumps(value, separators=(",", ":")), flush=True)

    def error_kind(error):
        if isinstance(error, (TimeoutError, requests.exceptions.Timeout, urllib3.exceptions.TimeoutError)):
            return "timeout"
        if isinstance(error, socket.gaierror):
            return "dns_error"
        if isinstance(error, (ssl.SSLError, requests.exceptions.SSLError, urllib3.exceptions.SSLError)):
            return "tls_error"
        if isinstance(error, requests.exceptions.ConnectionError):
            return "connection_error"
        return "network_error" if isinstance(error, OSError) else "other"

    def observe(phase, original, extra=None):
        def wrapped(*args, **kwargs):
            started = time.monotonic()
            emit({"phase": phase, "state": "started", "elapsedSeconds": 0})
            try:
                result = original(*args, **kwargs)
                fields = extra(result) if extra else {}
                emit({"phase": phase, "state": "ok", "elapsedSeconds": time.monotonic() - started, **fields})
                return result
            except Exception as error:
                emit({"phase": phase, "state": "failed", "elapsedSeconds": time.monotonic() - started, "errorKind": error_kind(error)})
                raise
        return wrapped

    def dns_fields(results):
        ipv4 = {item[4][0] for item in results if item[0] == socket.AF_INET}
        ipv6 = {item[4][0] for item in results if item[0] == socket.AF_INET6}
        return {"ipv4Count": len(ipv4), "ipv6Count": len(ipv6), "sameExpectedAddress": ipv4 == {EXPECTED_ADDRESS} and not ipv6}

    emit({"kind": "versions", "python": ".".join(map(str, sys.version_info[:3])), "requests": requests.__version__, "urllib3": urllib3.__version__})
    try:
        with patch.object(socket, "getaddrinfo", observe("dns", socket.getaddrinfo, dns_fields)), \
                patch.object(util_connection, "create_connection", observe("connection", util_connection.create_connection)), \
                patch.object(socket.socket, "connect", observe("tcp", socket.socket.connect)), \
                patch.object(connection, "_ssl_wrap_socket_and_match_hostname", observe("tls", connection._ssl_wrap_socket_and_match_hostname,
                             lambda result: {"tlsVersion": result.socket.version()})), \
                patch.object(connection.HTTPConnection, "getresponse", observe("http_headers", connection.HTTPConnection.getresponse,
                             lambda result: {"httpStatus": result.status})):
            with requests.Session() as session:
                session.trust_env = False
                session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                           "Referer": "https://" + HOST}
                url = "https://" + HOST + "/search/?" + urlencode({"srch_order": "total", "src_key": "프로젝트 헤일메리"})
                with session.get(url, headers=headers, timeout=BUDGET_SECONDS, verify=True, allow_redirects=False, stream=True) as response:
                    body_started, size = time.monotonic(), 0
                    emit({"phase": "body", "state": "started", "elapsedSeconds": 0})
                    try:
                        for chunk in response.iter_content(chunk_size=65536):
                            size += len(chunk)
                            if size > MAX_BODY:
                                emit({"phase": "body", "state": "failed", "elapsedSeconds": time.monotonic() - body_started, "errorKind": "body_too_large"})
                                emit({"kind": "done", "success": False})
                                return
                    except Exception as error:
                        emit({"phase": "body", "state": "failed", "elapsedSeconds": time.monotonic() - body_started, "errorKind": error_kind(error)})
                        emit({"kind": "done", "success": False})
                        return
                    emit({"phase": "body", "state": "ok", "elapsedSeconds": time.monotonic() - body_started, "bodyBytes": size})
                    emit({"kind": "done", "success": response.status_code == 200})
    except Exception:
        # Native exception messages may contain URLs/IPs; never print them.
        emit({"kind": "done", "success": False})


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    _worker()
