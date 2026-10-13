#!/usr/bin/env python3
"""Small production smoke test for a deployed Soulib endpoint."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree


DEFAULT_TIMEOUT = 35


def join_url(base, path):
    return urllib.parse.urljoin(base.rstrip("/") + "/", path.lstrip("/"))


def request(base, path, method="GET", payload=None, timeout=DEFAULT_TIMEOUT):
    url = join_url(base, path)
    data = None
    headers = {"User-Agent": "soulib-live-smoke/1.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read()
            content_type = res.headers.get("content-type", "")
            parsed = None
            if "application/json" in content_type:
                parsed = json.loads(body.decode("utf-8"))
            return res.status, body, parsed
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise AssertionError(f"{method} {path} returned {exc.code}: {body[:500]!r}") from exc


def assert_status(base, path, expected=200):
    status, body, parsed = request(base, path)
    if status != expected:
        raise AssertionError(f"GET {path} returned {status}, expected {expected}")
    if not body:
        raise AssertionError(f"GET {path} returned an empty body")
    return parsed, body


def validate_live_search(payload):
    if not isinstance(payload, dict):
        raise AssertionError("/api/live_search did not return JSON")
    meta = payload.get("meta") or {}
    if meta.get("mode") != "live" or not isinstance(meta.get("searched_libraries"), int) or meta["searched_libraries"] <= 0:
        raise AssertionError("/api/live_search did not perform a live library search")
    if not isinstance(payload.get("items"), list) or type(payload.get("total")) is not int or payload["total"] < 0:
        raise AssertionError("/api/live_search returned invalid items/total")
    diagnostics = meta.get("diagnostics") or []
    failures = sum(d.get("error_count", len(d.get("errors") or [])) for d in diagnostics)
    failures = max(failures, len(meta.get("failed_libraries") or []))
    successful = meta.get("successful_libraries", meta["searched_libraries"] - failures)
    if not payload["items"] and (successful <= 0 or failures >= meta["searched_libraries"]):
        raise AssertionError("/api/live_search returned no results after every library failed")
    if meta.get("partial") or failures:
        print("warning: live search degraded; some upstream libraries failed", file=sys.stderr)


def smoke(base, check_shared=True, check_supporting=False):
    checks = [
        "/",
        "/search",
        "/my-shelf",
        "/robots.txt",
        "/static/css/search.css",
        "/static/js/search.js",
    ]
    for path in checks:
        assert_status(base, path)
        print(f"ok {path}")

    search_payload, _ = assert_status(base, "/api/live_search?query=python")
    validate_live_search(search_payload)
    print("ok /api/live_search")

    if check_supporting:
        assert_status(base, "/reports")
        _, sitemap = assert_status(base, "/sitemap.xml")
        if ElementTree.fromstring(sitemap).tag.rsplit("}", 1)[-1] not in {"sitemapindex", "urlset"}:
            raise AssertionError("/sitemap.xml did not return sitemap XML")
        print("ok reports/sitemap read checks")

    if check_shared:
        payload = {
            "list": {"name": "Migration smoke"},
            "books": [
                {
                    "title": "프로젝트 헤일메리",
                    "author": "앤디 위어",
                    "publisher": "알에이치코리아",
                    "counts": {"kyobo": 1, "yes24": 0, "other": 1, "total": 2},
                }
            ],
        }
        status, _, share_json = request(base, "/api/shelves/share", method="POST", payload=payload)
        if status != 201:
            raise AssertionError(f"POST /api/shelves/share returned {status}, expected 201")
        if not share_json or not share_json.get("slug"):
            raise AssertionError("shared shelf response did not include a slug")
        assert_status(base, f"/shelf/{share_json['slug']}")
        print("ok shared shelf create/read")


def main():
    parser = argparse.ArgumentParser(description="Run a live Soulib smoke test against a base URL.")
    parser.add_argument("base_url", help="Deployment base URL, for example https://www.soulib.kr")
    parser.add_argument("--skip-shared", action="store_true", help="Skip shared shelf create/read checks.")
    parser.add_argument("--check-supporting", action="store_true", help="Read reports and validate sitemap XML.")
    args = parser.parse_args()

    smoke(args.base_url, check_shared=not args.skip_shared, check_supporting=args.check_supporting)
    print("live_smoke: ok")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"live_smoke: failed: {exc}", file=sys.stderr)
        sys.exit(1)
