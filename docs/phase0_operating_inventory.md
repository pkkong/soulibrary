# Phase 0 운영 경로 Inventory

이 문서는 Phase 0에서 현재 운영 경로와 레거시/보류 항목을 분리하기 위한 기준 inventory입니다.

Phase 0의 범위는 문서와 inventory 정리입니다. Vercel 배포, DNS, GitHub Actions workflow, Cloudtype 설정 변경은 Phase 0에서 수행하지 않습니다.

## 현재 운영 경로

현재 운영 entrypoint는 아래 경로입니다.

```text
.cloudtype/app.yaml -> Dockerfile -> web/app_search.py
```

- `.cloudtype/app.yaml`: Cloudtype에서 `app: dockerfile`과 `dockerfile: Dockerfile`을 사용합니다.
- `Dockerfile`: `/app/web`에서 `gunicorn ... app_search:app`을 실행합니다.
- `web/app_search.py`: 운영 Flask 앱입니다. 검색, 상세, 내 서재, 공유 서재, 신고 접수 라우트를 포함합니다.
- `web/live_search/`: DB 없는 실시간 검색 커넥터와 결과 정규화 경로입니다.
- `web/report_routes.py`: 오류 신고를 GitHub Issues로 접수합니다.
- 기본 검증: `python scripts/smoke_test.py`, `git diff --check`.

`web/app_cloudtype.py -> web/app_search.py`는 현재 실제 운영 설정이 아닙니다. 현재 저장소에는 `web/app_cloudtype.py` 파일도 없으므로, 해당 표기는 과거 문서 잔재로 봅니다.

## 기본 운영 원칙

- 기본 검색은 DB 없는 실시간 검색입니다.
- PostgreSQL이 있어도 검색 자체를 PostgreSQL에 의존시키지 않습니다.
- 운영 산출물, 로컬 DB, CSV, dump, 캐시, 토큰은 Git에 포함하지 않습니다.
- 레거시 경로를 되살릴 때는 먼저 메인 채팅방에서 필요성, 범위, 운영 영향을 결정합니다.

## PostgreSQL 관련 코드 분류

### 1. 현재 운영 필요

production 기능을 지원하므로 유지 대상입니다.

- 공유 서재 영속 저장: `SHARED_SHELVES_STORAGE=auto`에서 `DATABASE_URL` 또는 `DB_HOST` 계열 env가 있으면 PostgreSQL `shared_shelves` 테이블을 사용할 수 있습니다.
- PostgreSQL 연결 헬퍼: `web/db.py`는 공유 서재와 선택적 DB 작업에서 쓰일 수 있습니다.

주의: 이 그룹은 검색 DB 의존성을 뜻하지 않습니다. DB 없는 실시간 검색은 계속 기본 운영 경로입니다.

### 2. 선택적 필요

운영 기본 경로는 아니지만 관리자, 데이터 품질, 로컬 점검, 데이터 작업이 필요할 때 별도 작업으로 검토할 수 있습니다.

- CSV -> PostgreSQL 적재와 부분 적재 스크립트.
- 데이터 품질 검토/적용 스크립트와 관리자 화면.
- 로컬 DB 점검, 통계 갱신, 품질 리포트 생성.
- 큐레이션 관리자 기능.

이 그룹은 작업 목적과 소유 파일을 명확히 정한 뒤 별도 Worker/QA 게이트를 거쳐야 합니다.

### 3. 완전 레거시/삭제 후보

현재 운영 경로도 아니고, 되살릴 필요성이 확인되지 않으면 제거 후보입니다.

- `web/app_cloudtype.py` 같은 미사용 entrypoint 또는 그 문서 표기.
- 과거 SQLite 기반 검색 앱과 SQLite 빌드 흐름.
- SQLite -> PostgreSQL 마이그레이션 스크립트.
- 과거 DB rebuild, dump/restore 운영 흐름.
- PostgreSQL 기반 전체 보유 책 검색을 전제로 한 운영 문서 또는 스크립트.

삭제 작업은 Phase 0 범위가 아닙니다. 실제 삭제는 영향 범위 조사, 소유 파일 지정, 검증 계획을 별도 작업으로 잡은 뒤 진행합니다.

## 유지/보류/제거 후보

### 유지

- `.cloudtype/app.yaml -> Dockerfile -> web/app_search.py` 운영 entrypoint.
- DB 없는 실시간 검색 경로.
- 오류 신고 GitHub Issues 연동.
- 공유 서재 영속 저장을 위한 PostgreSQL fallback/auto 경로.
- `python scripts/smoke_test.py` 중심 검증.

### 보류

- CSV/PostgreSQL 적재.
- 데이터 품질 관리자와 관련 리포트.
- 큐레이션 관리자.
- 전수 크롤링과 로컬 데이터 산출물.
- Search Console 분석 자동화.

보류 항목은 기본 운영 경로가 아니며, 실제 필요가 생길 때 별도 작업으로 재분류합니다.

### 제거 후보

- 오래된 `web/app_cloudtype.py -> web/app_search.py` 문서 표기.
- 미사용 entrypoint가 새로 발견될 경우 해당 파일 또는 참조.
- 과거 SQLite 검색 경로.
- 과거 DB rebuild 또는 SQLite -> PostgreSQL 마이그레이션 흐름.
- 운영 경로로 오해될 수 있는 레거시 배포/DB 문서.

## Vercel 이전 전 재판단 항목

Vercel 이전을 검토하더라도 Phase 0에서는 배포/DNS/workflow를 변경하지 않습니다. 이전 작업을 시작하기 전 아래 항목을 먼저 재판단해야 합니다.

- Vercel이 Cloudtype을 대체하는지, 병행 preview 용도인지.
- Vercel에서 사용할 실제 entrypoint와 런타임 방식.
- `PORT`, `LIBRARY_SEARCH_PORT`, `GITHUB_ISSUE_TOKEN`, `GITHUB_ISSUE_REPO`, `PUBLIC_BASE_URL`, `SHARED_SHELVES_STORAGE` env/secret 처리.
- 공유 서재 영속 저장을 PostgreSQL로 유지할지, 별도 storage로 바꿀지.
- GitHub Actions workflow 변경 필요성과 smoke test 위치.
- `soulib.kr` DNS, redirect, canonical URL, Search Console 영향.
- DB 없는 실시간 검색 원칙을 유지할 수 있는지.
- Cloudtype rollback 또는 병행 운영 계획.

위 항목이 정리되기 전에는 Vercel 설정, 배포, DNS, workflow 변경을 추가하지 않습니다.

## Phase 0 완료 기준

- 운영 entrypoint 문서가 `.cloudtype/app.yaml -> Dockerfile -> web/app_search.py`로 정정되어 있습니다.
- DB 없는 실시간 검색이 기본 운영 경로로 유지되어 있습니다.
- PostgreSQL 관련 코드가 현재 운영 필요, 선택적 필요, 레거시/삭제 후보로 분류되어 있습니다.
- Phase 0에서 Vercel 배포/DNS/workflow 변경을 하지 않는다는 경계가 문서화되어 있습니다.
- 변경 후 `git diff --check -- AGENTS.md README_DEV.md docs/tasks.md docs/Guide.md docs/phase0_operating_inventory.md`를 실행합니다.
