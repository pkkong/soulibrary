import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse


SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
]
DEFAULT_OAUTH_TOKEN_FILE = ".secrets/search-console-oauth-token.json"
DEFAULT_BASE_URL = "https://www.soulib.kr"
DEFAULT_TARGET_PATHS = (
    "/",
    "/ebook-search",
    "/digital-library-search",
    "/seoul-ebook-library-search",
    "/blog/seoul-ebook-library-search-guide",
    "/blog/ebook-library-no-results-check",
    "/blog/ebook-search-guide",
    "/blog/seoul-on-library-guide",
)
DEFAULT_TARGET_KEYWORDS = (
    "전자도서관 검색",
    "전자 도서관 검색",
    "서울 전자도서관 검색",
    "서울 전자 도서관 검색",
    "서울시 전자책 검색",
    "서울시 전자 도서관",
    "서울시 전자도서관",
    "전자책 통합검색",
    "전자책 통합 검색",
    "전자책 검색",
)
DEFAULT_TECHNICAL_PATHS = (
    "/",
    "/search?q=%ED%8C%8C%EC%9D%B4%EC%8D%AC",
    "/ebook-search",
    "/digital-library-search",
    "/seoul-ebook-library-search",
    "/blog/seoul-ebook-library-search-guide",
    "/blog/ebook-library-no-results-check",
)


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.title_parts = []
        self.meta_description = None
        self.meta_robots = None
        self.canonical = None
        self.image_srcs = []
        self.link_hrefs = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = {name.lower(): value for name, value in attrs if name}
        if tag.lower() == "title":
            self.in_title = True
        elif tag.lower() == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            if name == "description":
                self.meta_description = attrs_dict.get("content")
            elif name == "robots":
                self.meta_robots = attrs_dict.get("content")
        elif tag.lower() == "link" and (attrs_dict.get("rel") or "").lower() == "canonical":
            self.canonical = attrs_dict.get("href")
        elif tag.lower() == "img" and attrs_dict.get("src"):
            self.image_srcs.append(attrs_dict["src"])
        elif tag.lower() == "a" and attrs_dict.get("href"):
            self.link_hrefs.append(attrs_dict["href"])

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data.strip())

    @property
    def title(self):
        return " ".join(part for part in self.title_parts if part).strip() or None


def fail(message, exit_code=2):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def parse_env_int(name, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        fail(f"{name} must be an integer.")


def split_csv(value):
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_google_modules():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        fail("Google API packages are not installed. Run `pip install -r requirements-data.txt`.")
    return service_account, build, HttpError


def credential_help():
    return (
        "Use GSC_SERVICE_ACCOUNT_JSON, GSC_SERVICE_ACCOUNT_FILE, "
        "GOOGLE_APPLICATION_CREDENTIALS, or OAuth token settings."
    )


def load_service_account_credentials(service_account, credentials_file, credentials_json):
    if credentials_json:
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            fail(f"GSC_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}")
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    if not credentials_file:
        fail(f"Missing Search Console credentials. {credential_help()}")

    path = Path(credentials_file).expanduser()
    if not path.exists():
        fail(f"Search Console credential file does not exist: {path}")
    return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)


def write_oauth_token(token_path, credentials):
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass


def load_oauth_credentials(client_file, token_file, token_json, authorize):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        fail("Google auth packages are not installed. Run `pip install -r requirements-data.txt`.")

    token_path = Path(token_file or DEFAULT_OAUTH_TOKEN_FILE).expanduser()
    credentials = None
    if token_json:
        try:
            token_info = json.loads(token_json)
        except json.JSONDecodeError as exc:
            fail(f"GSC_OAUTH_TOKEN_JSON is not valid JSON: {exc}")
        try:
            credentials = Credentials.from_authorized_user_info(token_info, SCOPES)
        except ValueError:
            fail("OAuth token JSON is not valid for Search Console access.")
    elif token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except ValueError:
            fail("OAuth token file is not valid for Search Console access.")

    if credentials and credentials.valid and not authorize:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token and not authorize:
        try:
            credentials.refresh(Request())
        except Exception:
            fail("OAuth token refresh failed. Run with --authorize to create a fresh token.")
        if not token_json:
            write_oauth_token(token_path, credentials)
        return credentials

    if not authorize:
        fail(f"OAuth token file does not exist or cannot be refreshed: {token_path}")

    if not client_file:
        fail("Missing OAuth client file. Set GSC_OAUTH_CLIENT_FILE or pass --oauth-client-file.")
    client_path = Path(client_file).expanduser()
    if not client_path.exists():
        fail(f"OAuth client file does not exist: {client_path}")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        fail("google-auth-oauthlib is not installed. Run `pip install -r requirements-data.txt`.")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    credentials = flow.run_local_server(port=0)
    write_oauth_token(token_path, credentials)
    print(f"OAuth token saved to {token_path}", file=sys.stderr)
    return credentials


def load_credentials(service_account, args):
    has_oauth = bool(
        args.oauth_client_file or args.oauth_token_file or args.oauth_token_json or args.authorize
    )
    if args.credentials_json:
        return load_service_account_credentials(
            service_account, args.credentials_file, args.credentials_json
        )
    if args.credentials_file and Path(args.credentials_file).expanduser().exists():
        return load_service_account_credentials(
            service_account, args.credentials_file, args.credentials_json
        )
    if has_oauth:
        return load_oauth_credentials(
            args.oauth_client_file,
            args.oauth_token_file,
            args.oauth_token_json,
            args.authorize,
        )
    if args.credentials_file:
        fail(f"Search Console credential file does not exist: {args.credentials_file}")
    fail(f"Missing Search Console credentials. {credential_help()}")


def normalize_url(base_url, value):
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return value
    return urljoin(base_url.rstrip("/") + "/", value.lstrip("/"))


def normalize_metric_row(row):
    clicks = int(row.get("clicks", 0))
    impressions = int(row.get("impressions", 0))
    ctr = float(row.get("ctr", 0.0))
    position = float(row.get("position", 0.0))
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(ctr, 4),
        "ctr_percent": round(ctr * 100, 2),
        "position": round(position, 2),
    }


def metric_delta(current, previous):
    previous = previous or normalize_metric_row({})
    return {
        **current,
        "delta_clicks": current["clicks"] - previous["clicks"],
        "delta_impressions": current["impressions"] - previous["impressions"],
        "delta_ctr_percent": round(current["ctr_percent"] - previous["ctr_percent"], 2),
        "delta_position": round(current["position"] - previous["position"], 2),
    }


def keyed_metrics(rows):
    result = {}
    for row in rows:
        result[tuple(row.get("keys") or [])] = normalize_metric_row(row)
    return result


def rows_with_deltas(rows, previous_rows, key_names):
    previous = keyed_metrics(previous_rows)
    output = []
    for row in rows:
        keys = row.get("keys") or []
        item = {name: keys[index] if index < len(keys) else "" for index, name in enumerate(key_names)}
        item.update(metric_delta(normalize_metric_row(row), previous.get(tuple(keys))))
        output.append(item)
    return output


def query_search_analytics(
    service,
    site_url,
    start_date,
    end_date,
    dimensions=None,
    row_limit=25,
    filters=None,
):
    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "rowLimit": row_limit,
    }
    if dimensions:
        body["dimensions"] = dimensions
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    return response.get("rows", [])


def summarize_period(service, site_url, end_date, days, row_limit):
    start_date = end_date - timedelta(days=days - 1)
    compare_end_date = start_date - timedelta(days=1)
    compare_start_date = compare_end_date - timedelta(days=days - 1)
    summary_rows = query_search_analytics(service, site_url, start_date, end_date, row_limit=1)
    previous_summary_rows = query_search_analytics(
        service, site_url, compare_start_date, compare_end_date, row_limit=1
    )
    query_rows = query_search_analytics(
        service, site_url, start_date, end_date, dimensions=["query"], row_limit=row_limit
    )
    previous_query_rows = query_search_analytics(
        service,
        site_url,
        compare_start_date,
        compare_end_date,
        dimensions=["query"],
        row_limit=row_limit * 2,
    )
    page_rows = query_search_analytics(
        service, site_url, start_date, end_date, dimensions=["page"], row_limit=row_limit
    )
    previous_page_rows = query_search_analytics(
        service,
        site_url,
        compare_start_date,
        compare_end_date,
        dimensions=["page"],
        row_limit=row_limit * 2,
    )
    page_query_rows = query_search_analytics(
        service,
        site_url,
        start_date,
        end_date,
        dimensions=["page", "query"],
        row_limit=row_limit,
    )
    previous_page_query_rows = query_search_analytics(
        service,
        site_url,
        compare_start_date,
        compare_end_date,
        dimensions=["page", "query"],
        row_limit=row_limit * 2,
    )
    return {
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "compare_start_date": compare_start_date.isoformat(),
        "compare_end_date": compare_end_date.isoformat(),
        "summary": metric_delta(
            normalize_metric_row(summary_rows[0]) if summary_rows else normalize_metric_row({}),
            normalize_metric_row(previous_summary_rows[0]) if previous_summary_rows else normalize_metric_row({}),
        ),
        "top_queries": rows_with_deltas(query_rows, previous_query_rows, ("query",)),
        "top_pages": rows_with_deltas(page_rows, previous_page_rows, ("page",)),
        "top_page_queries": rows_with_deltas(
            page_query_rows, previous_page_query_rows, ("page", "query")
        ),
    }


def target_metrics(service, site_url, end_date, days, dimension, expression):
    start_date = end_date - timedelta(days=days - 1)
    compare_end_date = start_date - timedelta(days=1)
    compare_start_date = compare_end_date - timedelta(days=days - 1)
    rows = query_search_analytics(
        service,
        site_url,
        start_date,
        end_date,
        row_limit=1,
        filters=[
            {
                "dimension": dimension,
                "operator": "equals",
                "expression": expression,
            }
        ],
    )
    previous_rows = query_search_analytics(
        service,
        site_url,
        compare_start_date,
        compare_end_date,
        row_limit=1,
        filters=[
            {
                "dimension": dimension,
                "operator": "equals",
                "expression": expression,
            }
        ],
    )
    return metric_delta(
        normalize_metric_row(rows[0]) if rows else normalize_metric_row({}),
        normalize_metric_row(previous_rows[0]) if previous_rows else normalize_metric_row({}),
    )


def target_batch_metrics(service, site_url, end_date, days, dimension, expressions):
    start_date = end_date - timedelta(days=days - 1)
    compare_end_date = start_date - timedelta(days=1)
    compare_start_date = compare_end_date - timedelta(days=days - 1)
    row_limit = max(1000, min(25000, len(expressions) * 100))
    rows = query_search_analytics(
        service,
        site_url,
        start_date,
        end_date,
        dimensions=[dimension],
        row_limit=row_limit,
    )
    previous_rows = query_search_analytics(
        service,
        site_url,
        compare_start_date,
        compare_end_date,
        dimensions=[dimension],
        row_limit=row_limit,
    )
    current = keyed_metrics(rows)
    previous = keyed_metrics(previous_rows)
    empty = normalize_metric_row({})
    return {
        expression: metric_delta(current.get((expression,), empty), previous.get((expression,), empty))
        for expression in expressions
    }


def build_target_report(service, site_url, end_date, periods, target_pages, target_keywords):
    page_periods = {
        days: target_batch_metrics(service, site_url, end_date, days, "page", target_pages)
        for days in periods
    }
    keyword_periods = {
        days: target_batch_metrics(service, site_url, end_date, days, "query", target_keywords)
        for days in periods
    }
    return {
        "pages": [
            {
                "page": page,
                "periods": {
                    str(days): page_periods[days].get(page, metric_delta(normalize_metric_row({}), normalize_metric_row({})))
                    for days in periods
                },
            }
            for page in target_pages
        ],
        "keywords": [
            {
                "query": keyword,
                "periods": {
                    str(days): keyword_periods[days].get(keyword, metric_delta(normalize_metric_row({}), normalize_metric_row({})))
                    for days in periods
                },
            }
            for keyword in target_keywords
        ],
    }


def inspect_urls(service, site_url, urls, limit, http_error):
    inspected = []
    capped_limit = max(0, min(limit, 20))
    for url in urls[:capped_limit]:
        try:
            response = (
                service.urlInspection()
                .index()
                .inspect(body={"inspectionUrl": url, "siteUrl": site_url})
                .execute()
            )
            result = response.get("inspectionResult", {})
            index_status = result.get("indexStatusResult", {})
            inspected.append(
                {
                    "url": url,
                    "verdict": index_status.get("verdict"),
                    "coverage_state": index_status.get("coverageState"),
                    "indexing_state": index_status.get("indexingState"),
                    "robots_txt_state": index_status.get("robotsTxtState"),
                    "page_fetch_state": index_status.get("pageFetchState"),
                    "google_canonical": index_status.get("googleCanonical"),
                    "user_canonical": index_status.get("userCanonical"),
                    "last_crawl_time": index_status.get("lastCrawlTime"),
                }
            )
        except http_error as exc:
            inspected.append({"url": url, "error": safe_error(exc)})
    return inspected


def load_state(path):
    if not path:
        return {"urls": {}}
    state_path = Path(path)
    if not state_path.exists():
        return {"urls": {}}
    try:
        with state_path.open(encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"urls": {}}
    if not isinstance(state, dict):
        return {"urls": {}}
    state.setdefault("urls", {})
    return state


def apply_indexing_state(inspected, state_file, write_state, today):
    state = load_state(state_file)
    urls = state.setdefault("urls", {})
    for item in inspected:
        url = item.get("url")
        if not url or item.get("error"):
            continue
        current = urls.setdefault(url, {})
        if item.get("verdict") == "PASS":
            current.pop("unindexed_since", None)
            current["last_indexed_at"] = today.isoformat()
            item["unindexed_since"] = None
            item["unindexed_days"] = 0
            continue
        unindexed_since = current.get("unindexed_since") or today.isoformat()
        current["unindexed_since"] = unindexed_since
        try:
            since_date = date.fromisoformat(unindexed_since)
            unindexed_days = max(0, (today - since_date).days)
        except ValueError:
            unindexed_days = 0
        item["unindexed_since"] = unindexed_since
        item["unindexed_days"] = unindexed_days
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    if state_file and write_state:
        state_path = Path(state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return inspected


def safe_error(exc):
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = getattr(getattr(exc, "resp", None), "reason", None)
    return {"status": status, "reason": reason or exc.__class__.__name__}


def fetch_page(session, url, timeout):
    started = time.monotonic()
    response = session.get(url, timeout=timeout, allow_redirects=True)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return response, elapsed_ms


def parse_html_head(body):
    parser = HeadParser()
    parser.feed(body[:200000])
    robots = (parser.meta_robots or "").lower()
    return {
        "title": parser.title,
        "meta_description_present": bool(parser.meta_description),
        "meta_robots": parser.meta_robots,
        "canonical": parser.canonical,
        "has_noindex": "noindex" in robots,
        "image_srcs": parser.image_srcs,
        "link_hrefs": parser.link_hrefs,
    }


def is_same_site_url(base_url, value):
    if not value or value.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False
    absolute = normalize_url(base_url, value)
    base_host = urlparse(base_url).netloc
    parsed = urlparse(absolute)
    return parsed.scheme in {"http", "https"} and parsed.netloc == base_host


def check_url_status(session, url, timeout):
    try:
        response = session.head(url, timeout=timeout, allow_redirects=True)
        if response.status_code in {405, 403}:
            response = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
        return response.status_code
    except Exception:
        return None


def find_broken_resources(session, base_url, current_url, values, timeout, limit):
    broken = []
    checked = 0
    seen = set()
    for value in values:
        absolute = urljoin(current_url, value)
        if not is_same_site_url(base_url, absolute) or absolute in seen:
            continue
        seen.add(absolute)
        checked += 1
        status = check_url_status(session, absolute, timeout)
        if status is None or status >= 400:
            broken.append({"url": absolute, "status_code": status})
        if checked >= limit:
            break
    return {"checked": checked, "broken": broken}


def fetch_sitemap_urls(session, base_url, timeout):
    sitemap_url = normalize_url(base_url, "/sitemap-static.xml")
    try:
        response, _ = fetch_page(session, sitemap_url, timeout)
    except Exception:
        return set()
    if response.status_code != 200:
        return set()
    urls = set()
    for part in response.text.split("<loc>")[1:]:
        loc = part.split("</loc>", 1)[0].strip()
        if loc:
            urls.add(loc)
    return urls


def canonical_matches(final_url, canonical):
    if not canonical:
        return False
    parsed_final = urlparse(final_url)
    parsed_canonical = urlparse(canonical)
    return (
        parsed_final.scheme == parsed_canonical.scheme
        and parsed_final.netloc == parsed_canonical.netloc
        and parsed_final.path.rstrip("/") == parsed_canonical.path.rstrip("/")
    )


def classify_monitored_url(final_url):
    parsed = urlparse(final_url)
    path = parsed.path or "/"
    if path == "/" or path == "":
        return "home"
    if path == "/search":
        return "search"
    if path in {"/ebook-search", "/digital-library-search", "/seoul-ebook-library-search"}:
        return "seo_landing"
    if path.startswith("/blog/"):
        return "blog"
    if path.startswith("/books/"):
        return "seo_book"
    return "other"


def run_technical_checks(base_url, paths, timeout):
    try:
        import requests
    except ImportError:
        fail("requests is not installed. Run `pip install -r requirements.txt`.")

    session = requests.Session()
    session.headers.update({"User-Agent": "Soulib SEO Growth Audit/1.0"})
    sitemap_urls = fetch_sitemap_urls(session, base_url, timeout)
    checks = []
    for path in paths:
        url = normalize_url(base_url, path)
        try:
            response, elapsed_ms = fetch_page(session, url, timeout)
            content_type = response.headers.get("content-type", "")
            html = parse_html_head(response.text) if "html" in content_type.lower() else {}
            images = find_broken_resources(
                session, base_url, response.url, html.get("image_srcs", []), timeout, 25
            ) if html else {"checked": 0, "broken": []}
            internal_links = find_broken_resources(
                session, base_url, response.url, html.get("link_hrefs", []), timeout, 25
            ) if html else {"checked": 0, "broken": []}
            html.pop("image_srcs", None)
            html.pop("link_hrefs", None)
            checks.append(
                {
                    "url": url,
                    "page_type": classify_monitored_url(response.url),
                    "status_code": response.status_code,
                    "ok": 200 <= response.status_code < 400,
                    "final_url": response.url,
                    "elapsed_ms": elapsed_ms,
                    "content_type": content_type.split(";")[0],
                    "indexable": bool(response.status_code == 200 and not html.get("has_noindex")),
                    "canonical_matches_final_url": canonical_matches(response.url, html.get("canonical"))
                    if html
                    else None,
                    "in_static_sitemap": response.url.split("?", 1)[0] in sitemap_urls,
                    "images_checked": images["checked"],
                    "broken_images": images["broken"][:5],
                    "internal_links_checked": internal_links["checked"],
                    "broken_internal_links": internal_links["broken"][:5],
                    **html,
                }
            )
        except requests.RequestException as exc:
            checks.append({"url": url, "ok": False, "error": exc.__class__.__name__})

    aux_checks = []
    for path in ("/robots.txt", "/sitemap.xml"):
        url = normalize_url(base_url, path)
        try:
            response, elapsed_ms = fetch_page(session, url, timeout)
            aux_checks.append(
                {
                    "url": url,
                    "status_code": response.status_code,
                    "ok": response.status_code == 200,
                    "elapsed_ms": elapsed_ms,
                    "content_type": response.headers.get("content-type", "").split(";")[0],
                }
            )
        except requests.RequestException as exc:
            aux_checks.append({"url": url, "ok": False, "error": exc.__class__.__name__})

    return {"pages": checks, "supporting_files": aux_checks}


def dry_run_report(args, end_date):
    periods = [empty_period(end_date, days) for days in (7, 28, 90)]
    target_pages = unique_ordered(
        [normalize_url(args.base_url, value) for value in DEFAULT_TARGET_PATHS + tuple(args.target_page)]
    )
    target_keywords = unique_ordered(list(DEFAULT_TARGET_KEYWORDS) + args.target_keyword)
    return {
        "schema_version": "seo_growth_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": True,
        "site_url": args.site_url,
        "base_url": args.base_url,
        "end_date": end_date.isoformat(),
        "search_console": {
            "periods": periods,
            "targets": {
                "pages": [
                    {
                        "page": page,
                        "periods": {
                            str(days): metric_delta(normalize_metric_row({}), normalize_metric_row({}))
                            for days in (7, 28, 90)
                        },
                    }
                    for page in target_pages
                ],
                "keywords": [
                    {
                        "query": keyword,
                        "periods": {
                            str(days): metric_delta(normalize_metric_row({}), normalize_metric_row({}))
                            for days in (7, 28, 90)
                        },
                    }
                    for keyword in target_keywords
                ],
            },
        },
        "url_inspection": {
            "limit": min(max(args.url_inspection_limit, 0), 20),
            "inspected": [],
            "skipped_reason": "dry_run",
        },
        "technical_checks": {"skipped_reason": "dry_run"},
        "risk_notes": ["Dry run skipped Google API and production HTTP requests."],
    }


def empty_period(end_date, days):
    start_date = end_date - timedelta(days=days - 1)
    return {
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "summary": metric_delta(normalize_metric_row({}), normalize_metric_row({})),
        "top_queries": [],
        "top_pages": [],
        "top_page_queries": [],
    }


def unique_ordered(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit Soulib SEO growth signals from Search Console and production checks."
    )
    parser.add_argument("--site-url", default=os.getenv("GSC_SITE_URL"))
    parser.add_argument("--base-url", default=os.getenv("PRODUCTION_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument(
        "--credentials-file",
        default=os.getenv("GSC_SERVICE_ACCOUNT_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    )
    parser.add_argument("--credentials-json", default=os.getenv("GSC_SERVICE_ACCOUNT_JSON"))
    parser.add_argument("--oauth-client-file", default=os.getenv("GSC_OAUTH_CLIENT_FILE"))
    parser.add_argument("--oauth-token-file", default=os.getenv("GSC_OAUTH_TOKEN_FILE"))
    parser.add_argument("--oauth-token-json", default=os.getenv("GSC_OAUTH_TOKEN_JSON"))
    parser.add_argument("--authorize", action="store_true")
    parser.add_argument("--row-limit", type=int, default=parse_env_int("SEO_AUDIT_ROW_LIMIT", 25))
    parser.add_argument("--end-date", help="Inclusive end date in YYYY-MM-DD. Defaults to yesterday.")
    parser.add_argument("--target-page", action="append", default=split_csv(os.getenv("SEO_TARGET_PAGES")))
    parser.add_argument(
        "--target-keyword", action="append", default=split_csv(os.getenv("SEO_TARGET_KEYWORDS"))
    )
    parser.add_argument(
        "--inspection-url", action="append", default=split_csv(os.getenv("SEO_INSPECTION_URLS"))
    )
    parser.add_argument(
        "--url-inspection-limit",
        type=int,
        default=parse_env_int("SEO_URL_INSPECTION_LIMIT", 0),
        help="Inspect at most 20 URLs. Use 0 for daily non-inspection audits.",
    )
    parser.add_argument(
        "--technical-path",
        action="append",
        default=split_csv(os.getenv("SEO_TECHNICAL_PATHS")) or list(DEFAULT_TECHNICAL_PATHS),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--state-file", default=os.getenv("SEO_GROWTH_STATE_FILE"))
    parser.add_argument("--write-state", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.row_limit < 1:
        fail("--row-limit must be at least 1.")
    if args.url_inspection_limit < 0:
        fail("--url-inspection-limit must be 0 or greater.")
    if args.url_inspection_limit > 20:
        fail("--url-inspection-limit must not exceed 20.")
    if args.end_date:
        try:
            end_date = date.fromisoformat(args.end_date)
        except ValueError:
            fail("--end-date must use YYYY-MM-DD format.")
    else:
        end_date = date.today() - timedelta(days=1)

    if args.dry_run:
        print(json.dumps(dry_run_report(args, end_date), ensure_ascii=False, indent=2))
        return

    if not args.site_url:
        fail("Missing Search Console property. Set GSC_SITE_URL or pass --site-url.")

    service_account, build, http_error = load_google_modules()
    credentials = load_credentials(service_account, args)
    if args.authorize:
        print("OAuth authorization completed.", file=sys.stderr)
        return

    service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)
    periods = [summarize_period(service, args.site_url, end_date, days, args.row_limit) for days in (7, 28, 90)]
    period_28 = next(period for period in periods if period["days"] == 28)

    inferred_pages = [row["page"] for row in period_28["top_pages"][:5]]
    inferred_keywords = [row["query"] for row in period_28["top_queries"][:5]]
    target_pages = unique_ordered(
        [normalize_url(args.base_url, value) for value in DEFAULT_TARGET_PATHS + tuple(args.target_page)]
        + inferred_pages
    )
    target_keywords = unique_ordered(list(DEFAULT_TARGET_KEYWORDS) + args.target_keyword + inferred_keywords)
    normalized_inspection_urls = unique_ordered(
        [normalize_url(args.base_url, value) for value in args.inspection_url + target_pages]
    )

    inspected = inspect_urls(
        service,
        args.site_url,
        normalized_inspection_urls,
        args.url_inspection_limit,
        http_error,
    ) if args.url_inspection_limit else []
    inspected = apply_indexing_state(inspected, args.state_file, args.write_state, date.today())

    report = {
        "schema_version": "seo_growth_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": False,
        "site_url": args.site_url,
        "base_url": args.base_url,
        "end_date": end_date.isoformat(),
        "search_console": {
            "periods": periods,
            "targets": build_target_report(
                service, args.site_url, end_date, (7, 28, 90), target_pages, target_keywords
            ),
        },
        "url_inspection": {
            "limit": min(max(args.url_inspection_limit, 0), 20),
            "inspected": inspected,
            "skipped_reason": None if args.url_inspection_limit else "url_inspection_limit_is_0",
        },
        "technical_checks": run_technical_checks(args.base_url, args.technical_path, args.timeout),
        "risk_notes": [],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
