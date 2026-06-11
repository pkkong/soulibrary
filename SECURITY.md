# Security Policy

## Supported Surface

Security reports should focus on the current production path:

- `https://www.soulib.kr`
- `vercel.json -> index.py -> web/app_search.py`
- GitHub Issues-backed reports/comments
- Supabase-backed shared shelves
- Apps in Toss WebView client

Cloudtype, SQLite search, local crawler output, and one-off migration scripts are not supported production paths.

## Reporting A Vulnerability

Do not open a public issue with secrets, tokens, private URLs, database credentials, service-account JSON, or exploit details that expose user data.

Use GitHub's private vulnerability reporting if available for this repository. If it is not available, open a minimal public issue that says a private security report is needed, without including sensitive details.

## Secret Handling

Production secrets belong only in:

- GitHub Actions secrets
- Vercel environment variables
- Supabase project settings
- local ignored files such as `.env` or `.secrets/`

Never commit generated crawl data, credential JSON, DB dumps, `.env`, or token values.

## Rotation

If a secret may have been exposed, rotate it first, then update GitHub/Vercel/Supabase configuration, then deploy and run live smoke tests.
