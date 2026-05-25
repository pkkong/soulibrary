import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def fail(message, exit_code=2):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(exit_code)


def load_google_modules():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        fail(
            "Google API packages are not installed. Run `pip install -r requirements.txt` first."
        )
    return service_account, build, HttpError


def load_credentials(service_account, credentials_file, credentials_json):
    if credentials_json:
        try:
            info = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            fail(f"GSC_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}")
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    if not credentials_file:
        fail(
            "Missing Search Console credentials. Set GSC_SERVICE_ACCOUNT_FILE or "
            "GSC_SERVICE_ACCOUNT_JSON."
        )

    path = Path(credentials_file).expanduser()
    if not path.exists():
        fail(f"Search Console credential file does not exist: {path}")

    return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)


def validate_credential_source(credentials_file, credentials_json):
    if credentials_json:
        return
    if not credentials_file:
        fail(
            "Missing Search Console credentials. Set GSC_SERVICE_ACCOUNT_FILE or "
            "GSC_SERVICE_ACCOUNT_JSON."
        )
    path = Path(credentials_file).expanduser()
    if not path.exists():
        fail(f"Search Console credential file does not exist: {path}")


def query_search_analytics(
    service,
    site_url,
    start_date,
    end_date,
    dimensions=None,
    row_limit=10,
):
    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "rowLimit": row_limit,
    }
    if dimensions:
        body["dimensions"] = dimensions
    response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    return response.get("rows", [])


def normalize_row(row):
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


def summarize_period(service, site_url, end_date, days, row_limit):
    start_date = end_date - timedelta(days=days - 1)
    summary_rows = query_search_analytics(
        service,
        site_url,
        start_date,
        end_date,
        dimensions=None,
        row_limit=1,
    )
    query_rows = query_search_analytics(
        service,
        site_url,
        start_date,
        end_date,
        dimensions=["query"],
        row_limit=row_limit,
    )
    page_rows = query_search_analytics(
        service,
        site_url,
        start_date,
        end_date,
        dimensions=["page"],
        row_limit=row_limit,
    )

    return {
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "summary": normalize_row(summary_rows[0]) if summary_rows else normalize_row({}),
        "top_queries": [
            {"query": row.get("keys", [""])[0], **normalize_row(row)} for row in query_rows
        ],
        "top_pages": [
            {"page": row.get("keys", [""])[0], **normalize_row(row)} for row in page_rows
        ],
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Print Google Search Console Search Analytics summaries."
    )
    parser.add_argument("--site-url", default=os.getenv("GSC_SITE_URL"))
    parser.add_argument(
        "--credentials-file",
        default=(
            os.getenv("GSC_SERVICE_ACCOUNT_FILE")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        ),
    )
    parser.add_argument("--credentials-json", default=os.getenv("GSC_SERVICE_ACCOUNT_JSON"))
    parser.add_argument(
        "--row-limit",
        type=int,
        default=parse_env_int("GSC_REPORT_ROW_LIMIT", 10),
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="Inclusive end date in YYYY-MM-DD. Defaults to yesterday.",
    )
    return parser.parse_args()


def parse_env_int(name, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        fail(f"{name} must be an integer.")


def main():
    args = parse_args()
    if not args.site_url:
        fail("Missing Search Console property. Set GSC_SITE_URL or pass --site-url.")
    if args.row_limit < 1:
        fail("--row-limit must be at least 1.")
    validate_credential_source(args.credentials_file, args.credentials_json)

    if args.end_date:
        try:
            end_date = date.fromisoformat(args.end_date)
        except ValueError:
            fail("--end-date must use YYYY-MM-DD format.")
    else:
        end_date = date.today() - timedelta(days=1)

    service_account, build, http_error = load_google_modules()
    credentials = load_credentials(
        service_account,
        args.credentials_file,
        args.credentials_json,
    )
    service = build("searchconsole", "v1", credentials=credentials, cache_discovery=False)

    try:
        report = {
            "site_url": args.site_url,
            "generated_date": date.today().isoformat(),
            "periods": [
                summarize_period(service, args.site_url, end_date, 7, args.row_limit),
                summarize_period(service, args.site_url, end_date, 28, args.row_limit),
            ],
        }
    except http_error as exc:
        fail(
            "Search Console API request failed. Check that the service account has access "
            f"to {args.site_url}. Details: {exc}",
            exit_code=1,
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
