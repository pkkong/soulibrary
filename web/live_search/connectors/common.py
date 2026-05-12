import re
from urllib.parse import urljoin, urlparse

import requests

from utils.http import DEFAULT_HEADERS, TLSAdapter, _build_ssl_context


def make_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.mount("https://", TLSAdapter(ssl_context=_build_ssl_context()))
    return session


def text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def absolute_url(url: str, base_url: str) -> str:
    url = text(url)
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return urljoin(base_url.rstrip("/") + "/", url)


def origin_from_url(url: str) -> str:
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def request_headers(referer: str = "") -> dict:
    headers = dict(DEFAULT_HEADERS)
    if referer:
        headers["Referer"] = referer
    return headers
