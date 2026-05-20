import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
sys.path.insert(0, str(WEB_DIR))

os.environ.setdefault("APP_MODE", "live")
os.environ.setdefault("LIVE_SEARCH_TOTAL_TIMEOUT", "8")
os.environ.setdefault("LIVE_SEARCH_LIBRARY_TIMEOUT", "3")
os.environ.setdefault("SHARED_SHELVES_STORAGE", "json")
os.environ.setdefault("SHARED_SHELVES_FILE", str(ROOT_DIR / "data" / "_tmp_regular_audit_shelves.json"))

import report_routes  # noqa: E402
from app_search import app  # noqa: E402
from live_search.normalizer import normalize_title_for_group  # noqa: E402
from seo_books import SEO_BOOKS, SEO_BOOK_BY_SLUG  # noqa: E402


KST = timezone(timedelta(hours=9), "Asia/Seoul")
AUDIT_ISSUE_TITLE = "[정기점검] 서비스 점검 실패"
DEFAULT_BASE_URL = "https://www.soulib.kr"


def _now_label():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")


def _github_repo():
    return (
        os.environ.get("GITHUB_ISSUE_REPO")
        or os.environ.get("GITHUB_REPOSITORY")
        or "pkkong/library_crawler"
    ).strip()


def _github_token():
    return os.environ.get("GITHUB_ISSUE_TOKEN") or os.environ.get("GITHUB_TOKEN")


def _github_headers():
    token = _github_token()
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required.")
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_request(method, path, **kwargs):
    url = f"https://api.github.com/repos/{_github_repo()}{path}"
    response = requests.request(method, url, headers=_github_headers(), timeout=15, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def _find_open_audit_issue():
    issues = _github_request("GET", "/issues", params={"state": "open", "per_page": 100})
    for issue in issues if isinstance(issues, list) else []:
        if issue.get("pull_request"):
            continue
        if issue.get("title") == AUDIT_ISSUE_TITLE:
            return issue
    return None


def _sync_audit_issue(failures, warnings):
    if os.environ.get("AUDIT_SYNC_ISSUE") != "1":
        return
    if not _github_token():
        print("[audit warning] GitHub token missing; audit issue sync skipped.")
        return

    body = _audit_issue_body(failures, warnings)
    existing = _find_open_audit_issue()
    if failures:
        if existing:
            _github_request("PATCH", f"/issues/{existing['number']}", json={"body": body})
            _github_request("POST", f"/issues/{existing['number']}/comments", json={"body": _short_failure_comment(failures)})
            print(f"[audit] updated issue #{existing['number']}")
        else:
            created = _github_request("POST", "/issues", json={"title": AUDIT_ISSUE_TITLE, "body": body})
            print(f"[audit] created issue #{created.get('number')}")
        return

    if existing:
        _github_request("POST", f"/issues/{existing['number']}/comments", json={"body": f"{_now_label()} 점검에서 문제가 재현되지 않아 자동으로 닫습니다."})
        _github_request("PATCH", f"/issues/{existing['number']}", json={"state": "closed", "state_reason": "completed"})
        print(f"[audit] closed issue #{existing['number']}")


def _audit_issue_body(failures, warnings):
    lines = [
        f"자동 정기점검 시각: {_now_label()}",
        "",
        "## 실패 항목",
    ]
    if failures:
        lines.extend(f"- {item}" for item in failures)
    else:
        lines.append("- 없음")
    lines.append("")
    lines.append("## 참고 경고")
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- 없음")
    lines.append("")
    lines.append("이 이슈는 `scripts/regular_audit.py`가 자동으로 생성/갱신합니다.")
    return "\n".join(lines)


def _short_failure_comment(failures):
    head = failures[:5]
    lines = [f"{_now_label()} 정기점검에서 문제가 계속 재현됐습니다.", ""]
    lines.extend(f"- {item}" for item in head)
    if len(failures) > len(head):
        lines.append(f"- 외 {len(failures) - len(head)}건")
    return "\n".join(lines)


class Audit:
    def __init__(self):
        self.failures = []
        self.warnings = []

    def check(self, name, func):
        started = time.time()
        try:
            func()
            print(f"[ok] {name} ({time.time() - started:.2f}s)")
        except Exception as exc:
            message = f"{name}: {exc}"
            self.failures.append(message)
            print(f"[fail] {message}")

    def warn(self, message):
        self.warnings.append(message)
        print(f"[warn] {message}")


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def check_local_routes():
    with app.test_client() as client:
        for path in ["/", "/search", "/reports", "/my-shelf", "/sitemap.xml", "/sitemap-static.xml"]:
            response = client.get(path)
            _assert(response.status_code == 200, f"{path} returned {response.status_code}")


def check_shared_shelf_fallback():
    tmp_file = Path(os.environ["SHARED_SHELVES_FILE"])
    tmp_file.unlink(missing_ok=True)
    with app.test_client() as client:
        response = client.post(
            "/api/shelves/share",
            json={
                "list": {"name": "정기점검 서재"},
                "books": [{"title": "프로젝트 헤일메리", "author": "앤디 위어"}],
            },
        )
        _assert(response.status_code == 201, f"share returned {response.status_code}")
        slug = (response.get_json() or {}).get("slug")
        _assert(slug, "share did not return slug")
        page = client.get(f"/shelf/{slug}")
        _assert(page.status_code == 200, f"shared shelf page returned {page.status_code}")
    tmp_file.unlink(missing_ok=True)


def check_seo_pages_fast():
    _assert(len(SEO_BOOKS) == len(SEO_BOOK_BY_SLUG), "SEO book slugs are duplicated")
    _assert(len(SEO_BOOKS) >= 50, f"SEO book list too small: {len(SEO_BOOKS)}")

    slow = []
    with app.test_client() as client:
        for book in SEO_BOOKS:
            started = time.time()
            response = client.get(f"/books/{book['slug']}")
            elapsed = time.time() - started
            _assert(response.status_code == 200, f"/books/{book['slug']} returned {response.status_code}")
            body = response.get_data(as_text=True)
            _assert("/api/live_book_detail?" in body, f"/books/{book['slug']} does not hydrate asynchronously")
            if elapsed > 0.5:
                slow.append((book["slug"], round(elapsed, 3)))
    _assert(not slow, f"SEO pages should render without blocking live search: {slow[:5]}")


def _get_json(url, **kwargs):
    response = requests.get(url, headers={"User-Agent": "soulib-regular-audit/1.0"}, timeout=kwargs.pop("timeout", 30), **kwargs)
    response.raise_for_status()
    return response.json()


def check_production_pages(audit):
    base_url = os.environ.get("AUDIT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    for path in ["/", "/search", "/reports"]:
        started = time.time()
        response = requests.get(urljoin(base_url, path), headers={"User-Agent": "soulib-regular-audit/1.0"}, timeout=20)
        elapsed = time.time() - started
        _assert(response.status_code == 200, f"{base_url}{path} returned {response.status_code}")
        if elapsed > 3:
            audit.warn(f"{path} production response was slow: {elapsed:.2f}s")

    started = time.time()
    response = requests.get(urljoin(base_url, "/books/project-hail-mary"), headers={"User-Agent": "soulib-regular-audit/1.0"}, timeout=20)
    elapsed = time.time() - started
    _assert(response.status_code == 200, f"/books/project-hail-mary returned {response.status_code}")
    _assert("/api/live_book_detail?" in response.text, "production SEO book page is blocking live detail lookup")
    if elapsed > 3:
        audit.warn(f"/books/project-hail-mary production response was slow: {elapsed:.2f}s")


def check_production_live_search():
    base_url = os.environ.get("AUDIT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    samples = [
        ("프로젝트 헤일메리", "프로젝트 헤일메리"),
        ("언스크립티드", "언스크립티드"),
        ("불편한 편의점", "불편한 편의점"),
    ]
    for query, expected_title in samples:
        data = _get_json(
            urljoin(base_url, "/api/live_search"),
            params={"query": query, "field": "title_author", "limit": "5", "offset": "0"},
            timeout=35,
        )
        items = data.get("items") if isinstance(data, dict) else []
        expected_key = normalize_title_for_group(expected_title)
        matched = [
            item
            for item in items or []
            if normalize_title_for_group(item.get("title")) == expected_key
            and int((item.get("counts") or {}).get("total") or 0) > 0
        ]
        _assert(matched, f"production live search did not find {expected_title!r}; top={[(item.get('title'), (item.get('counts') or {}).get('total')) for item in (items or [])[:3]]}")


def check_open_error_reports():
    if not _github_token():
        if os.environ.get("CI"):
            raise AssertionError("GitHub token missing; cannot check incoming error reports")
        print("[audit warning] GitHub token missing; report check skipped locally.")
        return

    reports = report_routes._recent_github_reports(limit=20)
    open_reports = [report for report in reports if report.get("status") == "open"]
    if open_reports:
        labels = [
            f"#{report.get('issue_number')} {report.get('message') or report.get('category')}"
            for report in open_reports[:10]
        ]
        raise AssertionError(f"unresolved error reports exist: {', '.join(labels)}")


def main():
    audit = Audit()
    audit.check("local core routes", check_local_routes)
    audit.check("shared shelf fallback", check_shared_shelf_fallback)
    audit.check("SEO pages render fast", check_seo_pages_fast)
    audit.check("production pages", lambda: check_production_pages(audit))
    audit.check("production live search samples", check_production_live_search)
    audit.check("incoming error reports", check_open_error_reports)

    _sync_audit_issue(audit.failures, audit.warnings)
    if audit.warnings:
        print("[audit warnings]")
        for warning in audit.warnings:
            print(f"- {warning}")
    if audit.failures:
        print("[audit failed]")
        for failure in audit.failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print(f"[audit ok] {_now_label()}")


if __name__ == "__main__":
    main()
