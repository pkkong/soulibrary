#!/usr/bin/env python3
"""Small production smoke test for a deployed Soulib endpoint."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


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


def smoke(base, check_shared=True):
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

    search_payload, _ = assert_status(base, "/api/search?q=python")
    if not isinstance(search_payload, dict):
        raise AssertionError("/api/search did not return JSON")
    print("ok /api/search")

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
    args = parser.parse_args()

    smoke(args.base_url, check_shared=not args.skip_shared)
    print("live_smoke: ok")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"live_smoke: failed: {exc}", file=sys.stderr)
        sys.exit(1)
