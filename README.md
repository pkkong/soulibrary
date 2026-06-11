# Soulib

서울 공공 전자도서관을 한 번에 검색하는 모바일 우선 웹 서비스입니다.

- Production: https://www.soulib.kr
- Repository: https://github.com/pkkong/soulibrary
- Runtime: Vercel Serverless Functions + Flask
- Persistence: Supabase Postgres for shared shelves
- Search: live connectors, no prebuilt search database required

## What It Does

Soulib은 사용자가 검색하는 순간 여러 전자도서관 공급사를 직접 조회합니다. 미리 만든 검색 DB에 의존하지 않기 때문에 검색 결과와 상세 화면은 가능한 한 현재 도서관 상태에 가깝게 구성됩니다.

핵심 기능:

- 서울 전자도서관 통합 검색
- 교보, YES24, 북큐브 등 공급사별 실시간 조회
- 도서 상세와 도서관별 대출 상태 확인
- 브라우저 로컬 기반 내 서재
- 공유 가능한 서재 링크
- 오류 신고와 블로그 댓글의 GitHub Issues 연동
- Apps in Toss용 미니앱 클라이언트

## Architecture

```text
GitHub main
-> GitHub Actions smoke test
-> Vercel production deploy
-> index.py
-> web/app_search.py
-> web/live_search/*
```

현재 production entrypoint는 `vercel.json -> index.py -> web/app_search.py`입니다. Cloudtype 설정과 SQLite 기반 검색 앱은 운영 경로에서 제거했습니다.

## Tech Stack

- Python, Flask, Gunicorn
- Vercel
- Supabase Postgres
- GitHub Actions
- Vanilla JS/CSS templates
- React + Vite for `apps-in-toss/`

## Local Run

```bash
python -m pip install -r requirements.txt
python web/app_search.py
```

Open:

```text
http://127.0.0.1:5001
```

Verify:

```bash
python scripts/smoke_test.py
git diff --check
```

## Repository Layout

```text
web/                    Flask app, templates, static assets
web/live_search/         Real-time search connectors
scripts/                 QA, operations, and data utility scripts
content/blog/            Service blog content
supabase/migrations/     Shared shelf database schema
apps-in-toss/            Apps in Toss miniapp client
docs/                    Development and operations notes
```

Crawler and data-admin scripts are kept as optional tooling. They are not part of the default production search path.

## Public Repository Notes

This repository is safe to run without private data. Local `.env`, `.secrets/`, database files, crawler outputs, logs, and build artifacts are ignored.

Production secrets must live only in GitHub Actions, Vercel, Supabase, or local ignored files. Do not commit tokens, service-account JSON, SQLite databases, CSV exports, or generated crawl output.

## More Docs

- Development guide: [README_DEV.md](README_DEV.md)
- Production operations: [docs/production_operations.md](docs/production_operations.md)
- Public repository inventory: [docs/public_repository_inventory.md](docs/public_repository_inventory.md)
- Operating inventory: [docs/phase0_operating_inventory.md](docs/phase0_operating_inventory.md)
- Apps in Toss: [apps-in-toss/README.md](apps-in-toss/README.md)
