# Contributing

Soulib is a production service repository. Contributions should keep the live search path small, verifiable, and safe to deploy.

## Local Setup

```bash
python -m pip install -r requirements.txt
python web/app_search.py
```

Open `http://127.0.0.1:5001`.

## Verification

Run these before opening a pull request:

```bash
python scripts/smoke_test.py
git diff --check
```

For production-facing changes, also run:

```bash
python scripts/live_smoke.py https://www.soulib.kr
```

## Change Guidelines

- Keep the default search path DB-free.
- Do not commit `.env`, `.secrets/`, database files, CSV exports, crawler output, logs, or local cache.
- Do not reintroduce Cloudtype or SQLite search as a production path.
- Keep Vercel production behavior compatible with `vercel.json -> index.py -> web/app_search.py`.
- For Apps in Toss changes, preserve the existing search/detail/shelf flow unless there is a documented reason to diverge.

## Pull Requests

Each pull request should include:

- user-visible change summary
- verification commands and result
- deployment or rollback risk, if any
- screenshots for UI changes

Small documentation fixes can be direct, but production behavior changes need a smoke test.
