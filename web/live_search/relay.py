"""Bounded, authenticated transport for a few fixed public library pages.

The relay fetches bytes only; normal search/status parsers and caches stay in the
main application. No user supplied URL, cookie, or header crosses this boundary.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from lxml import html as lxml_html
from urllib3.util import Timeout

from live_search.connectors.common import make_session, request_headers

RELAY_PATH = "/internal/library-page"
MAX_REQUEST_BYTES = 8192
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_ENVELOPE_BYTES = 3 * 1024 * 1024
MAX_BUDGET_MS = 4500
AUTH_WINDOW_SEC = 60
TIMESTAMP_HEADER = "X-Library-Relay-Timestamp"
SIGNATURE_HEADER = "X-Library-Relay-Signature"
ORIGINS = {
    "seongbuk": "https://elibrary.sblib.seoul.kr",
    "yeongdeungpo": "https://ebook.ydplib.or.kr",
    "songpa_owned": "https://ebook.splib.or.kr",
    "gangseo": "https://ebook.gangseo.seoul.kr",
}
ERRORS = frozenset({
    "configuration", "authentication", "invalid_request", "budget_exhausted",
    "transport_error", "upstream_http", "redirect", "body_too_large",
    "invalid_document", "invalid_response", "busy",
})


class RelayError(requests.RequestException):
    """Only a fixed error code may reach existing application error logs."""

    def __init__(self, code):
        self.code = code if code in ERRORS else "transport_error"
        super().__init__("library_relay_" + self.code)


def relay_enabled(library_code):
    return (
        os.environ.get("LIBRARY_RELAY_MODE") != "1"
        and os.environ.get("LIBRARY_RELAY_ENABLED") == "1"
        and library_code in ORIGINS
        and library_code in {
            item.strip() for item in os.environ.get("LIBRARY_RELAY_CODES", "").split(",")
        }
    )


def operation_deadline(timeout):
    return time.monotonic() + min(float(timeout), MAX_BUDGET_MS / 1000)


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise RelayError("budget_exhausted")
    return value


def _secret():
    secret = os.environ.get("LIBRARY_RELAY_SECRET", "").encode("utf-8")
    if len(secret) < 32:
        raise RelayError("configuration")
    return secret


def signature(timestamp, body):
    return hmac.new(_secret(), timestamp.encode("ascii") + b"\n" + body, hashlib.sha256).hexdigest()


def authenticated(timestamp, supplied_signature, body):
    try:
        if not re.fullmatch(r"[0-9]{10}", timestamp or ""):
            return False
        if abs(time.time() - int(timestamp)) > AUTH_WINDOW_SEC:
            return False
        if not re.fullmatch(r"[a-f0-9]{64}", supplied_signature or ""):
            return False
        return hmac.compare_digest(signature(timestamp, body), supplied_signature)
    except RelayError:
        return False


def _keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise RelayError("invalid_request")


def _string(value, maximum, pattern=None, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not value and not empty):
        raise RelayError("invalid_request")
    if any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise RelayError("invalid_request")
    if pattern and not re.fullmatch(pattern, value):
        raise RelayError("invalid_request")
    return value


def page_recipe(payload):
    """Validate every field before producing a fixed public HTTPS request."""
    _keys(payload, ("version", "library_code", "operation", "params", "budget_ms"))
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise RelayError("invalid_request")
    budget = payload["budget_ms"]
    if type(budget) is not int or not 1 <= budget <= MAX_BUDGET_MS:
        raise RelayError("invalid_request")
    code, operation, params = payload["library_code"], payload["operation"], payload["params"]
    if not isinstance(code, str) or code not in ORIGINS or not isinstance(operation, str):
        raise RelayError("invalid_request")
    origin = ORIGINS[code]
    if code == "seongbuk" and operation == "kyobo_search":
        _keys(params, ("query", "field", "limit"))
        query = _string(params["query"], 500)
        if params["field"] not in ("ctts", "autr", "pbcm"):
            raise RelayError("invalid_request")
        if type(params["limit"]) is not int or not 1 <= params["limit"] <= 50:
            raise RelayError("invalid_request")
        path = "/elibrary-front/search/searchList.ink"
        values = {"schTxt": query, "schClst": params["field"], "pageIndex": "1",
                  "recordCount": str(params["limit"]), "dvsnCheck": "001"}
    elif code == "seongbuk" and operation == "kyobo_detail":
        _keys(params, ("brcd", "ctts_dvsn_code", "ctgr_id", "sntn_auth_code"))
        values = {}
        for source, target, maximum in (("brcd", "brcd", 80), ("ctts_dvsn_code", "cttsDvsnCode", 16),
                                        ("ctgr_id", "ctgrId", 64), ("sntn_auth_code", "sntnAuthCode", 128)):
            value = _string(params[source], maximum, r"[A-Za-z0-9_-]*", empty=source != "brcd")
            if value or source != "sntn_auth_code":
                values[target] = value
        path = "/elibrary-front/content/contentView.ink"
    elif code != "seongbuk" and operation == "yes24_search":
        _keys(params, ("query", "field"))
        query = _string(params["query"], 500)
        if params["field"] not in ("total", "title", "author", "publisher"):
            raise RelayError("invalid_request")
        path, values = "/search/", {"srch_order": params["field"], "src_key": query}
    elif code != "seongbuk" and operation == "yes24_detail":
        _keys(params, ("goods_id",))
        path, values = "/ebook/detail/", {"goods_id": _string(params["goods_id"], 32, r"[0-9]+")}
    elif code != "seongbuk" and operation == "yes24_list":
        _keys(params, ())
        path, values = "/ebook/", {"mode": "total", "sort": "pubdt", "cate_id": "", "page_num": "1"}
    else:
        raise RelayError("invalid_request")
    return origin + path + "?" + urlencode(values), request_headers(origin)


def load_payload(body):
    try:
        # Duplicate keys are invalid too, rather than accepting the last value.
        def unique_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise RelayError("invalid_request")
                result[key] = value
            return result
        payload = json.loads(body, object_pairs_hook=unique_keys)
        page_recipe(payload)
        return payload
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise RelayError("invalid_request") from None


def _set_read_timeout(response, timeout):
    # requests uses an inactivity timeout. Refresh the actual socket with the
    # absolute remaining budget before each bounded streamed read as well.
    try:
        response.raw._fp.fp.raw._sock.settimeout(timeout)
    except AttributeError:
        pass  # In-memory/mock response; the deadline is still checked below.


def _request_timeout(deadline):
    budget = remaining(deadline)
    return Timeout(total=budget, connect=budget, read=budget)


def _read_bounded(response, maximum, deadline):
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            if int(declared) < 0 or int(declared) > maximum:
                raise RelayError("body_too_large")
        except ValueError:
            raise RelayError("invalid_response") from None
    chunks, size = [], 0
    stream = iter(response.iter_content(chunk_size=16384))
    while True:
        _set_read_timeout(response, remaining(deadline))
        try:
            chunk = next(stream)
        except StopIteration:
            break
        remaining(deadline)
        size += len(chunk)
        if size > maximum:
            raise RelayError("body_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _content_type(value):
    if not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise RelayError("invalid_document")
    if value.split(";", 1)[0].strip().lower() not in ("text/html", "application/xhtml+xml"):
        raise RelayError("invalid_document")
    return value


def _response(body, content_type, status=200):
    response = requests.Response()
    response.status_code = status
    response.headers["Content-Type"] = _content_type(content_type)
    response._content = body
    response.encoding = requests.utils.get_encoding_from_headers(response.headers)
    if not response.encoding or "charset" not in content_type.lower():
        encodings = requests.utils.get_encodings_from_content(body[:4096].decode("ascii", "ignore"))
        response.encoding = encodings[0] if encodings else None
    return response


def validate_document(response):
    value = response.text
    if not value.strip() or not re.search(r"</html\s*>", value, re.I):
        raise RelayError("invalid_document")


def validate_search_document(response, library_code, results):
    """A login/block/error document is a failure, never a successful zero."""
    validate_document(response)
    try:
        doc = lxml_html.fromstring(response.text)
        if library_code == "seongbuk":
            summary = doc.xpath("//*[contains(concat(' ',normalize-space(@class),' '),' book_resultTxt ')]")
            summary_text = " ".join(summary[0].itertext()) if summary else ""
            if results:
                valid = bool(summary) and bool(doc.xpath("//ul[contains(@class,'book_resultList')]"))
            else:
                valid = bool(summary) and "검색 결과가 없습니다" in summary_text
        else:
            total = doc.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' total ')]/em")
            listing = doc.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' ebook-list ')]")
            count = "".join(total[0].itertext()).strip().replace(",", "") if total else ""
            valid = bool(listing) and count.isdigit() and (int(count) > 0 if results else int(count) == 0)
        if not valid:
            raise RelayError("invalid_document")
    except (ValueError, TypeError, IndexError):
        raise RelayError("invalid_document") from None


def yes24_status_html(response, operation, goods_id):
    """Give the existing status parser only the requested book's verified stat.

    List pages contain other books first. The legacy parser scans the first stat
    before checking goods_id, so narrow the input here on the relay path only.
    """
    validate_document(response)
    _string(goods_id, 32, r"[0-9]+")
    try:
        doc = lxml_html.fromstring(response.text, parser=lxml_html.HTMLParser(remove_comments=True))

        def matches_detail(value):
            parsed = urlparse(value)
            return (parsed.path in ("/ebook/detail", "/ebook/detail/")
                    and parse_qs(parsed.query).get("goods_id") == [goods_id])

        if operation == "yes24_list":
            books = doc.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' ebook-list ')]"
                              "//div[contains(concat(' ',normalize-space(@class),' '),' bx ')]")
            selected = [book for book in books if any(matches_detail(href) for href in book.xpath(".//a/@href"))]
        elif operation == "yes24_detail":
            selected = doc.xpath("//div[contains(concat(' ',normalize-space(@class),' '),' ebook-view ')]")
            references = doc.xpath("//input[@name='return_url']/@value")
            if not any(matches_detail(value) for value in references):
                raise RelayError("invalid_document")
        else:
            raise RelayError("invalid_request")
        if len(selected) != 1:
            raise RelayError("invalid_document")
        stats = selected[0].xpath(".//div[contains(concat(' ',normalize-space(@class),' '),' stat ')]")
        if len(stats) != 1:
            raise RelayError("invalid_document")
        stat = lxml_html.tostring(stats[0], encoding="unicode")
        for label in ("보유", "대출", "예약"):
            if not re.search(r"<li>\s*" + label + r"\s*<strong>[0-9]+</strong>", stat):
                raise RelayError("invalid_document")
        return stat
    except (ValueError, TypeError, IndexError):
        raise RelayError("invalid_document") from None


def fetch_upstream(payload):
    """Relay server only: one bounded fixed-origin fetch, with no retry/cache."""
    url, headers = page_recipe(payload)
    deadline = operation_deadline(payload["budget_ms"] / 1000)
    try:
        # Songpa's public host accepts the modern, certificate-verified default
        # TLS session. Keep the other libraries' existing transport unchanged.
        strict_tls = payload["library_code"] == "songpa_owned"
        session_factory = requests.Session if strict_tls else make_session
        with session_factory() as session:
            session.trust_env = False
            with session.get(url, headers=headers, timeout=_request_timeout(deadline), verify=strict_tls,
                             allow_redirects=False, stream=True) as upstream:
                if 300 <= upstream.status_code < 400:
                    raise RelayError("redirect")
                if upstream.status_code != 200:
                    raise RelayError("upstream_http")
                content_type = _content_type(upstream.headers.get("Content-Type", ""))
                body = _read_bounded(upstream, MAX_PAGE_BYTES, deadline)
        response = _response(body, content_type)
        validate_document(response)
        remaining(deadline)
        return {"version": 1, "ok": True, "upstream_status": 200,
                "content_type": content_type, "body_base64": base64.b64encode(body).decode("ascii"),
                "region": os.environ.get("VERCEL_REGION", "unknown")}
    except RelayError:
        raise
    except requests.Timeout:
        raise RelayError("budget_exhausted") from None
    except Exception:
        raise RelayError("transport_error") from None


def _relay_url():
    value = os.environ.get("LIBRARY_RELAY_URL", "")
    try:
        parsed = urlparse(value)
    except ValueError:
        raise RelayError("configuration") from None
    if (parsed.scheme != "https" or not parsed.hostname
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.vercel\.app", parsed.hostname)
            or parsed.netloc != parsed.hostname or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or len(parsed.hostname) > 253):
        raise RelayError("configuration")
    return value.rstrip("/") + RELAY_PATH


def fetch_page(library_code, operation, params, deadline):
    """Main server only: preserve raw bytes for the existing Python parsers."""
    if os.environ.get("LIBRARY_RELAY_MODE") == "1":
        raise RelayError("configuration")
    # Reserve a small amount of the existing budget for network return/parsing.
    budget_ms = min(MAX_BUDGET_MS, int(remaining(deadline) * 1000) - 150)
    if budget_ms < 1:
        raise RelayError("budget_exhausted")
    payload = {"version": 1, "library_code": library_code, "operation": operation,
               "params": params, "budget_ms": budget_ms}
    page_recipe(payload)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise RelayError("invalid_request")
    timestamp = str(int(time.time()))
    headers = {"Content-Type": "application/json", TIMESTAMP_HEADER: timestamp,
               SIGNATURE_HEADER: signature(timestamp, body)}
    url = _relay_url()
    try:
        # Do not use the legacy-origin TLS adapter for server-to-server traffic.
        with requests.Session() as session:
            session.trust_env = False
            with session.post(url, data=body, headers=headers, timeout=_request_timeout(deadline),
                              verify=True, allow_redirects=False, stream=True) as remote:
                data = _read_bounded(remote, MAX_ENVELOPE_BYTES, deadline)
                if remote.status_code != 200:
                    try:
                        failure = json.loads(data)
                        _keys(failure, ("version", "ok", "error", "region"))
                        if (type(failure["version"]) is int and failure["version"] == 1
                                and failure["ok"] is False and failure["error"] in ERRORS):
                            raise RelayError(failure["error"])
                    except RelayError:
                        raise
                    except Exception:
                        pass
                    raise RelayError("transport_error")
        envelope = json.loads(data)
        _keys(envelope, ("version", "ok", "upstream_status", "content_type", "body_base64", "region"))
        if (type(envelope["version"]) is not int or envelope["version"] != 1
                or envelope["ok"] is not True or type(envelope["upstream_status"]) is not int
                or envelope["upstream_status"] != 200 or envelope["region"] != "icn1"):
            raise RelayError("invalid_response")
        raw = base64.b64decode(envelope["body_base64"], validate=True)
        if len(raw) > MAX_PAGE_BYTES:
            raise RelayError("body_too_large")
        response = _response(raw, envelope["content_type"])
        validate_document(response)
        remaining(deadline)
        return response
    except RelayError:
        raise
    except requests.Timeout:
        raise RelayError("budget_exhausted") from None
    except Exception:
        raise RelayError("transport_error") from None
