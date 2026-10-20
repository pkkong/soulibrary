"""Single-use authenticated fixed-target probe; never returns pages or secrets."""

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
COMPARE_BODY = b'{"version":1,"mode":"transport-compare"}'
HOST = "ebook.splib.or.kr"
EXPECTED_ADDRESS = "218.153.155.12"
TARGETS = {"songpa_owned": (HOST, EXPECTED_ADDRESS), "gangseo": ("ebook.gangseo.seoul.kr", None)}
COMPARE_CODES = ("gangseo", "songpa_owned")
FIXED_TITLE = "프로젝트 헤일메리"
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
            if type(event.get("certificateVerified")) is bool:
                safe["certificateVerified"] = event["certificateVerified"]
            if event.get("bookMatch") in ("matched", "not_found", "unverified"):
                safe["bookMatch"] = event["bookMatch"]
            if type(event.get("httpStatus")) is int and 100 <= event["httpStatus"] <= 599:
                safe["httpStatus"] = event["httpStatus"]
            events.append(safe)
        except (ValueError, TypeError):
            continue
    return events, versions, done


def diagnose(run=subprocess.run, code="songpa_owned"):
    if code not in TARGETS:
        raise ValueError("invalid_target")
    started, timed_out = time.monotonic(), False
    # No management token, HMAC, cookies or proxy env reaches the worker.
    child_env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.pathsep.join(sys.path), "PYTHONUNBUFFERED": "1"}
    if os.environ.get("LD_LIBRARY_PATH"):
        # Lambda's Python/native extensions may need the existing runtime loader path.
        child_env["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"]
    try:
        result = run([sys.executable, os.path.abspath(__file__), "--worker", code], env=child_env,
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


def compare():
    records = [{"libraryCode": code, **diagnose(code=code)} for code in COMPARE_CODES]
    return {"diagnosticComplete": all(record["diagnosticComplete"] for record in records), "comparison": records}


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
    if request.query_string or body not in (BODY, COMPARE_BODY) or not re.fullmatch(r"[0-9]{10}", timestamp) or abs(time.time() - int(timestamp)) > 60:
        return jsonify({"ok": False, "errorKind": "invalid_request"}), 400
    expected = hmac.new(secret.encode(), timestamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()
    if not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(expected, supplied):
        return jsonify({"ok": False, "errorKind": "authentication"}), 401
    with _lock:
        if _used:
            return jsonify({"ok": False, "errorKind": "already_used"}), 409
        _used = True
    return jsonify({"ok": True, "mode": "songpa-probe", "region": _region(), **(compare() if body == COMPARE_BODY else diagnose())})


def _book_match(body, host):
    """Only a fixed title inside a YES24 result's title/detail link can match."""
    from html.parser import HTMLParser
    from urllib.parse import parse_qs, urlparse

    class BookParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack, self.matched = [], False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            bx = (tag == "div" and "bx" in attrs.get("class", "").split()) or any(item[1] for item in self.stack)
            title = tag == "p" and "tit" in attrs.get("class", "").split() and bx
            anchor = None
            if tag == "a" and any(item[2] for item in self.stack):
                url = urlparse(attrs.get("href", ""))
                ids = parse_qs(url.query).get("goods_id", [])
                if url.scheme in ("", "https") and url.path in ("/ebook/detail", "/ebook/detail/") and url.hostname in (None, host) and len(ids) == 1 and re.fullmatch(r"[0-9]+", ids[0]):
                    anchor = []
            if tag not in ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"):
                self.stack.append((tag, bx, title, anchor))

        def handle_data(self, value):
            if any(item[0] in ("script", "style") for item in self.stack):
                return
            for item in reversed(self.stack):
                if item[3] is not None:
                    item[3].append(value)
                    break

        def handle_endtag(self, tag):
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    for item in self.stack[index:]:
                        if item[3] is not None and re.sub(r"\s+", "", "".join(item[3])) == re.sub(r"\s+", "", FIXED_TITLE):
                            self.matched = True
                    del self.stack[index:]
                    break

    for encoding in ("utf-8", "euc-kr"):
        try:
            parser = BookParser()
            parser.feed(body.decode(encoding))
            if parser.matched:
                return "matched"
        except (UnicodeError, ValueError):
            continue
    return "not_found"


def _worker(code="songpa_owned"):
    """Observe original transport calls; do not change their arguments/results."""
    import socket
    import ssl
    from unittest.mock import patch
    from urllib.parse import urlencode
    import requests
    import urllib3
    import urllib3.connection as connection
    import urllib3.util.connection as util_connection

    host, expected_address = TARGETS[code]

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
        fields = {"ipv4Count": len(ipv4), "ipv6Count": len(ipv6)}
        if expected_address:
            fields["sameExpectedAddress"] = ipv4 == {expected_address} and not ipv6
        return fields

    emit({"kind": "versions", "python": ".".join(map(str, sys.version_info[:3])), "requests": requests.__version__, "urllib3": urllib3.__version__})
    try:
        with patch.object(socket, "getaddrinfo", observe("dns", socket.getaddrinfo, dns_fields)), \
                patch.object(util_connection, "create_connection", observe("connection", util_connection.create_connection)), \
                patch.object(socket.socket, "connect", observe("tcp", socket.socket.connect)), \
                patch.object(connection, "_ssl_wrap_socket_and_match_hostname", observe("tls", connection._ssl_wrap_socket_and_match_hostname,
                             lambda result: {"tlsVersion": result.socket.version(), "certificateVerified": getattr(result, "is_verified", False) is True})), \
                patch.object(connection.HTTPConnection, "getresponse", observe("http_headers", connection.HTTPConnection.getresponse,
                             lambda result: {"httpStatus": result.status})):
            with requests.Session() as session:
                session.trust_env = False
                session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                           "Referer": "https://" + host}
                url = "https://" + host + "/search/?" + urlencode({"srch_order": "total", "src_key": FIXED_TITLE})
                with session.get(url, headers=headers, timeout=BUDGET_SECONDS, verify=True, allow_redirects=False, stream=True) as response:
                    body_started, size, content = time.monotonic(), 0, bytearray()
                    emit({"phase": "body", "state": "started", "elapsedSeconds": 0})
                    try:
                        for chunk in response.iter_content(chunk_size=65536):
                            size += len(chunk)
                            if size > MAX_BODY:
                                emit({"phase": "body", "state": "failed", "elapsedSeconds": time.monotonic() - body_started, "errorKind": "body_too_large"})
                                emit({"kind": "done", "success": False})
                                return
                            content.extend(chunk)
                    except Exception as error:
                        emit({"phase": "body", "state": "failed", "elapsedSeconds": time.monotonic() - body_started, "errorKind": error_kind(error)})
                        emit({"kind": "done", "success": False})
                        return
                    emit({"phase": "body", "state": "ok", "elapsedSeconds": time.monotonic() - body_started, "bodyBytes": size,
                          "bookMatch": _book_match(bytes(content), host) if response.status_code == 200 else "unverified"})
                    emit({"kind": "done", "success": response.status_code == 200})
    except Exception:
        # Native exception messages may contain URLs/IPs; never print them.
        emit({"kind": "done", "success": False})


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        _worker()
    elif len(sys.argv) == 3 and sys.argv[1] == "--worker" and sys.argv[2] in TARGETS:
        _worker(sys.argv[2])
