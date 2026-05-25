import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
DEFAULT_OAUTH_TOKEN_FILE = ".secrets/search-console-oauth-token.json"


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


def credential_help():
    return (
        "Use a service account with GSC_SERVICE_ACCOUNT_FILE or "
        "GSC_SERVICE_ACCOUNT_JSON, or use OAuth with GSC_OAUTH_CLIENT_FILE and "
        f"GSC_OAUTH_TOKEN_FILE (default: {DEFAULT_OAUTH_TOKEN_FILE}). Run once with "
        "--authorize to create the OAuth token file."
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


def load_oauth_credentials(client_file, token_file, authorize):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        fail("Google auth packages are not installed. Run `pip install -r requirements.txt` first.")

    token_path = Path(token_file or DEFAULT_OAUTH_TOKEN_FILE).expanduser()
    credentials = None
    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except ValueError:
            fail(
                "OAuth token file is not valid for Search Console access. "
                "Run with --authorize to create a fresh token."
            )

    if credentials and credentials.valid and not authorize:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token and not authorize:
        try:
            credentials.refresh(Request())
        except Exception:
            fail("OAuth token refresh failed. Run with --authorize to create a fresh token.")
        write_oauth_token(token_path, credentials)
        return credentials

    if not authorize:
        if token_path.exists():
            fail(
                "OAuth token is missing, expired, or cannot be refreshed. "
                "Run with --authorize to create a fresh token."
            )
        fail(
            f"OAuth token file does not exist: {token_path}. "
            "Run with --authorize after setting GSC_OAUTH_CLIENT_FILE."
        )

    if not client_file:
        fail(
            "Missing OAuth client file. Set GSC_OAUTH_CLIENT_FILE or pass "
            "--oauth-client-file before running --authorize."
        )

    client_path = Path(client_file).expanduser()
    if not client_path.exists():
        fail(f"OAuth client file does not exist: {client_path}")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        fail(
            "google-auth-oauthlib is not installed. Run `pip install -r requirements.txt` first."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    credentials = flow.run_local_server(port=0)
    write_oauth_token(token_path, credentials)
    print(f"OAuth token saved to {token_path}", file=sys.stderr)
    return credentials


def write_oauth_token(token_path, credentials):
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass


def load_credentials(service_account, args):
    has_oauth = bool(args.oauth_client_file or args.oauth_token_file or args.authorize)

    if args.authorize:
        return load_oauth_credentials(
            args.oauth_client_file,
            args.oauth_token_file,
            authorize=True,
        )

    if args.credentials_json:
        return load_service_account_credentials(
            service_account,
            args.credentials_file,
            args.credentials_json,
        )

    if args.credentials_file and Path(args.credentials_file).expanduser().exists():
        return load_service_account_credentials(
            service_account,
            args.credentials_file,
            args.credentials_json,
        )

    if has_oauth:
        return load_oauth_credentials(
            args.oauth_client_file,
            args.oauth_token_file,
            authorize=False,
        )

    if args.credentials_file:
        fail(
            f"Search Console credential file does not exist: "
            f"{Path(args.credentials_file).expanduser()}. {credential_help()}"
        )

    fail(f"Missing Search Console credentials. {credential_help()}")


def validate_credential_source(args):
    if args.authorize:
        if not args.oauth_client_file:
            fail(
                "Missing OAuth client file. Set GSC_OAUTH_CLIENT_FILE or pass "
                "--oauth-client-file before running --authorize."
            )
        return

    if args.credentials_json:
        return

    if args.credentials_file and Path(args.credentials_file).expanduser().exists():
        return

    if args.oauth_client_file or args.oauth_token_file:
        token_path = Path(args.oauth_token_file or DEFAULT_OAUTH_TOKEN_FILE).expanduser()
        if not token_path.exists():
            fail(
                f"OAuth token file does not exist: {token_path}. "
                "Run with --authorize after setting GSC_OAUTH_CLIENT_FILE."
            )
        return

    if args.credentials_file:
        fail(
            f"Search Console credential file does not exist: "
            f"{Path(args.credentials_file).expanduser()}. {credential_help()}"
        )

    fail(f"Missing Search Console credentials. {credential_help()}")


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
    parser.add_argument("--oauth-client-file", default=os.getenv("GSC_OAUTH_CLIENT_FILE"))
    parser.add_argument(
        "--oauth-token-file",
        default=os.getenv("GSC_OAUTH_TOKEN_FILE"),
        help=f"OAuth token file. Defaults to {DEFAULT_OAUTH_TOKEN_FILE} when OAuth is used.",
    )
    parser.add_argument(
        "--authorize",
        action="store_true",
        help="Run OAuth desktop browser consent and save the token file.",
    )
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
    if not args.site_url and not args.authorize:
        fail("Missing Search Console property. Set GSC_SITE_URL or pass --site-url.")
    if args.row_limit < 1:
        fail("--row-limit must be at least 1.")
    validate_credential_source(args)

    if args.end_date:
        try:
            end_date = date.fromisoformat(args.end_date)
        except ValueError:
            fail("--end-date must use YYYY-MM-DD format.")
    else:
        end_date = date.today() - timedelta(days=1)

    service_account, build, http_error = load_google_modules()
    credentials = load_credentials(service_account, args)
    if args.authorize and not args.site_url:
        print("OAuth authorization completed.", file=sys.stderr)
        return

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
            "Search Console API request failed. Check that the credential has access "
            f"to {args.site_url}. Details: {exc}",
            exit_code=1,
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
