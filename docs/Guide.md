# Guide.md

서비스 구조와 운영 흐름을 빠르게 확인하는 현재 기준 가이드입니다.

## 1) 현재 서비스 기준

- Soulib은 서울 전자도서관 통합 검색 서비스입니다.
- 기본 검색은 DB 없이 동작합니다.
- 사용자가 검색하면 교보, YES24, 기타 도서관 커넥터를 실시간으로 조회합니다.
- 책 상세 화면도 검색 결과의 실시간 메타데이터와 외부 상태 조회를 기준으로 구성합니다.
- 내 서재는 브라우저 로컬 저장소 기반의 사용자 보조 기능입니다.
- 오류 신고는 GitHub Issues를 단일 저장소로 사용합니다.
- 공유 서재 영속 저장은 운영 PostgreSQL을 사용할 수 있지만, 검색 자체는 PostgreSQL에 의존하지 않습니다.
- 큐레이션, 데이터 관리자, PostgreSQL 기반 검색은 현재 운영 기본 흐름이 아닙니다.

## 2) 기준 저장소와 작업 위치

- 기준 원본: GitHub `pkkong/library_crawler`
- 기준 브랜치: `main`
- 기본 작업 환경: GitHub Codespaces 또는 Codex Cloud
- 집 PC, 회사 PC, 모바일은 작업 단말입니다. 프로젝트 원본을 각 PC에 따로 보관하는 구조가 아닙니다.

표준 흐름:

```text
GitHub main
-> Codespaces/Codex Cloud에서 branch 생성
-> 수정 및 smoke test
-> Pull Request
-> main merge
-> GitHub Actions
-> Vercel production 자동 배포
```

## 3) 실행 구조

운영 entrypoint:

```text
vercel.json -> index.py -> web/app_search.py
```

`index.py`는 기존 `web/app_search.py`의 Flask `app`을 그대로 export하고, `vercel.json`은 모든 요청을 이 Flask 앱으로 보냅니다. `.cloudtype/app.yaml`과 Dockerfile은 rollback/참고용으로 남아 있지만 현재 자동배포 경로가 아닙니다.

주요 코드:

- `web/app_search.py`: Flask 앱, 검색/상세/신고 라우트
- `web/live_search/`: 실시간 검색 커넥터와 결과 정규화
- `web/report_routes.py`: 오류 신고 접수 및 GitHub Issues 연동
- `web/templates/`: 화면 템플릿
- `web/static/`: CSS, JS, 이미지
- `.github/workflows/vercel-deploy.yml`: smoke test 후 Vercel production 배포와 live smoke test
- `vercel.json`, `index.py`: Vercel Flask entrypoint
- `.cloudtype/app.yaml`: Cloudtype rollback/참고용 앱 설정
- `.devcontainer/devcontainer.json`: Codespaces 개발환경

## 4) 로컬 또는 Codespaces 실행

의존성 설치:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

서버 실행:

```bash
python web/app_search.py
```

기본 URL:

```text
http://127.0.0.1:5001/
http://127.0.0.1:5001/search
http://127.0.0.1:5001/my-shelf
http://127.0.0.1:5001/reports
```

Codespaces에서는 포트 `5001`이 자동 포워딩됩니다.

## 5) 테스트

변경 후 최소 확인:

```bash
python scripts/smoke_test.py
```

확인 대상:

- `/`
- `/search`
- `/my-shelf`
- `/api/search`
- `/reports`
- DB 없이 서버가 시작되는지

## 6) 배포

`main`에 반영되면 GitHub Actions가 실행됩니다.

1. Python 설치
2. `requirements.txt` 설치
3. `python scripts/smoke_test.py`
4. Vercel production 배포
5. `python scripts/live_smoke.py https://www.soulib.kr`

자세한 production 운영 기준은 [production_operations.md](production_operations.md)를 봅니다.

필요한 GitHub Actions secret:

```text
VERCEL_TOKEN
VERCEL_ORG_ID
VERCEL_PROJECT_ID
```

Vercel production runtime env:

```text
PUBLIC_BASE_URL=https://www.soulib.kr
GITHUB_ISSUE_TOKEN=<Issues read/write token>
GITHUB_ISSUE_REPO=pkkong/library_crawler
DATABASE_URL=<Supabase Postgres pooler connection URL>
SHARED_SHELVES_STORAGE=auto
```

## 7) 데이터와 DB 원칙

현재 운영 검색은 DB가 필요 없습니다.

Git에 남기는 `data/` 파일:

```text
data/README.md
```

Git에 올리지 않는 것:

- 크롤링 CSV
- 임시 JSON
- SQLite DB
- PostgreSQL dump
- 캐시
- 로그
- 개인 토큰

PostgreSQL 관련 코드는 세 그룹으로 구분합니다.

- 현재 운영 필요: 공유 서재 영속 저장처럼 production 기능을 지원하는 코드. 검색 자체를 PostgreSQL에 의존시키지 않습니다.
- 선택적 필요: 관리자, 데이터 품질, 로컬 DB 점검, CSV/PostgreSQL 적재 작업.
- 완전 레거시/삭제 후보: 미사용 entrypoint, 과거 SQLite 검색, 과거 DB rebuild 또는 SQLite -> PostgreSQL 마이그레이션 흐름.

현재 production 운영은 [production_operations.md](production_operations.md)를 기준으로 확인합니다. 레거시 유지/보류/삭제 후보 분류는 [phase0_operating_inventory.md](phase0_operating_inventory.md)를 참고합니다.

## 8) 오류 신고 운영

사용자가 `/reports`에서 신고하면 GitHub Issue로 접수됩니다.

기대 동작:

- 사용자는 접수 완료/실패 메시지를 봅니다.
- 접수된 내용은 GitHub Issues에서 확인합니다.
- 해결 후에는 고객이 이해할 수 있는 말로 처리 내용을 남깁니다.

고객용 답변 기준:

```text
신고해주신 문제를 확인했습니다.
해당 도서관의 대출 상태가 표시되지 않는 문제가 있었고, 상태 조회 방식을 수정했습니다.
현재는 다시 정상적으로 확인됩니다.
```

개발자용 로그나 내부 함수명만 고객에게 노출하지 않습니다.

## 9) 레거시 범위

아래 항목은 코드에 남아 있을 수 있지만 현재 기본 운영 대상이 아닙니다.

- CSV 전수 크롤링
- PostgreSQL 기반 전체 보유 책 검색
- 큐레이션 관리자
- 데이터 품질 관리자
- 과거 DB dump/restore 절차
- `web/app_cloudtype.py` 같은 미사용 entrypoint
- 과거 SQLite 검색 앱과 DB rebuild 흐름

이 기능을 다시 사용할 때는 먼저 현재 실시간 검색 구조와 충돌하지 않는지 검토합니다.
