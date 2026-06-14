# Public Repository Inventory

Soulib은 현재 공개 저장소로 운영해도 되는 구조를 목표로 정리합니다.

## 공개 유지 판단

공개 유지가 적합한 경우:

- production secret이 GitHub Actions, Vercel, Supabase, 로컬 `.env` 또는 `.secrets/`에만 있다.
- 현재 운영 entrypoint가 `vercel.json -> index.py -> web/app_search.py`로 명확하다.
- SQLite/Cloudtype/전수 크롤링 같은 과거 경로가 현재 운영 경로로 오해되지 않는다.
- README가 서비스의 목적, 구조, 실행 방법을 바로 보여준다.

비공개 전환 또는 history rewrite를 검토할 경우:

- 과거 커밋에 실제 토큰 원문, DB URL, service-account JSON, private key가 들어간 것이 확인된다.
- 공개하면 안 되는 데이터 원본, 계약 정보, 개인 정보가 Git history에 남아 있다.
- 토큰 회전이 끝나지 않은 상태에서 과거 Cloudtype/GitHub/Vercel credential 흔적이 의심된다.

## 이번 정리에서 제거한 항목

- `.tmp_update_guide.py`: 임시 문서 패치 스크립트.
- `web/app.py`: SQLite 기반 과거 Flask entrypoint.
- `run_admin.bat`: `web/app.py`만 실행하던 과거 Windows launcher.
- `crawler/scrapy`: 비어 있던 파일.
- `scripts/migrate_cloudtype_to_vercel.py`: 완료된 one-off migration runner.
- `docs/reports/*`: 과거 cleanup/stage report 산출물.
- `run_search.bat`: Windows 로컬 검색 launcher. 현재 운영 entrypoint가 아니므로 과거 제거됨.
- `run_data_admin.bat`: Windows 로컬 데이터 관리자 launcher. 현재 Vercel + Supabase 운영과 무관하므로 과거 제거됨.
- `run_curation_admin.bat`: Windows 로컬 큐레이션 관리자 launcher. 현재 운영 entrypoint가 아니므로 과거 제거됨.
- `run_tg_bot.example.bat`: Windows Telegram crawler bot 예시 launcher. 현재 운영 자동화가 아니므로 과거 제거됨.
- `scripts/build_sqlite.py`, `scripts/build_library_split.py`: SQLite 기반 과거 검색 DB 빌드 흐름이므로 과거 제거됨.
- `scripts/migrate_sqlite_to_postgres.py`, `scripts/migrate_split_to_postgres.py`: SQLite/split DB에서 PostgreSQL로 옮기던 과거 마이그레이션 흐름이므로 과거 제거됨.
- `scripts/rebuild_search_db_local.py`: 로컬 전체 검색 DB rebuild 흐름이므로 과거 제거됨. 데이터 품질 관리자에서는 해당 전체 rebuild operation도 함께 제거했습니다.
- `web/static/js/ai_search.js`: 1바이트 정적 JS 파일이며 참조가 없어 과거 제거됨.
- `web/templates/admin.html`: 현재 route map에 없는 과거 `/admin` 화면이며 내부 admin API도 없어 과거 제거됨.
- `web/templates/guide.html`: 현재 route map과 `render_template` 참조가 없는 과거 `/guide` 화면이므로 과거 제거됨.

## 유지한 항목

- `web/app_search.py`: 현재 production Flask 앱.
- `web/live_search/`: DB 없는 실시간 검색 경로.
- `web/report_routes.py`, `web/blog_comments.py`: GitHub Issues 연동.
- `supabase/migrations/`: 공유 서재 영속 저장 schema.
- `apps-in-toss/`: Toss miniapp client.
- `crawler/`, 남은 data/admin scripts: 현재 production 검색 경로는 아니지만, 데이터 점검과 향후 작업용으로 보류.

## 보류한 항목

아래 항목은 공개 저장소에서 노이즈가 될 수 있지만, 즉시 삭제하면 기능 검증 비용이 커서 보류합니다.

- CSV/PostgreSQL 적재 스크립트.
- 데이터 품질 관리자 코드.
- 큐레이션 관리자 코드.
- 전수 크롤링 spider.
- Search Console 분석 스크립트.

이 항목을 더 줄일 때는 production smoke test와 admin/data 작업 영향 범위를 먼저 분리합니다.

## 공개 저장소 운영 규칙

- `.env`, `.secrets/`, DB 파일, CSV 산출물, 로그, local cache는 커밋하지 않습니다.
- Vercel env `GITHUB_ISSUE_REPO`는 `pkkong/soulibrary`를 기준으로 둡니다.
- Cloudtype은 rollback 경로가 아니라 과거 운영 기록입니다.
- 과거 credential 노출이 의심되면 공개 여부와 별개로 토큰을 회전합니다.
