﻿# Guide.md

서비스 개요, 구조, 운영 흐름을 빠르게 이해할 수 있는 가이드입니다.

## 1) 서비스 개요
- 목적: 서울시 전자도서 통합검색(검색/큐레이션/상세 페이지 제공)
- 구성:
  - 관리자(admin): 크롤러/체커 + CSV 기준 현황
  - 검색 서비스(search): PostgreSQL 기반 검색/상세/API

## 2) 시스템 구성(아키텍처)
- 크롤러: crawler/ (CSV 생성)
- 관리자: web/app.py (CSV 기준, DB 미사용)
- 검색: web/app_search.py (PostgreSQL 사용)
- 정적 리소스: web/static/
- 템플릿: web/templates/

## 3) 데이터 흐름(핵심)
### A. 크롤링(로컬)
1) 크롤러 실행 → CSV 생성 (data/*.csv)
2) admin에서 CSV 권수/상태 확인

### B. 데이터 적재
1) CSV → 로컬 PostgreSQL 적재 (scripts/load_csv_to_postgres.py)
2) 로컬에서 검색/화면 확인
3) 덤프/복원으로 서버 PostgreSQL 반영

### C. 상세/상태 조회
- 상세 페이지는 플랫폼별 고유 ID로 외부 상세 URL을 생성.
- 대출/예약 현황은 **실시간 API 호출**로 조회(크롤링 시점 데이터는 사용하지 않음).

## 4) 로컬 실행
### 관리자
run_admin.bat

### 검색 서비스
- `run_search.bat`
  - 로컬 검색/상세 테스트 전용
  - 큐레이션 관리자 비활성(`ENABLE_CURATION_ADMIN=0`)

### 큐레이션 관리자(로컬 전용)
- `run_curation_admin.bat`
  - 기본 포트 5002
  - 큐레이션 수정 모드 활성(`ENABLE_CURATION_ADMIN=1`)
  - 목적: 로컬에서 큐레이션 데이터 갱신 후 결과물만 GitHub 반영

### 데이터 품질 관리자(로컬 전용)
- `run_data_admin.bat`
  - 기본 포트 5002
  - 데이터 품질 관리자 모드 활성(`ENABLE_CURATION_ADMIN=1`)
  - 접속 URL: `/admin/data-quality`
  - 기능:
    - CSV → PostgreSQL 적재 버튼(증분: `CSV_ONLY`, 전체 재구축: `MIGRATE_DROP=1`)
    - Stage1/Stage2 `dry-run`/`apply` 버튼 실행
    - 핵심 품질 지표 카드 표시(중복 그룹/orphan/canonical 누락 등)
    - 최근 실행 로그/JSON 결과 확인

## 5) DB 환경변수(로컬)
기본값은 run_search.bat에 설정되어 있음.
DB_HOST=localhost
DB_PORT=5432
DB_NAME=soulib_test
DB_USER=root
DB_PASSWORD=localpass

## 6) 서버 반영(덤프/복원)
### 로컬 덤프 생성
`docker exec -e PGPASSWORD=localpass soulib-postgres pg_dump -U root -d soulib_test -Fc -f /tmp/soulib_test.dump`

### 서버 DB 재생성
`docker exec -e PGPASSWORD=<pw> soulib-postgres psql -h <host> -p <port> -U root -d postgres -c "DROP DATABASE IF EXISTS soulib_test;"`
`docker exec -e PGPASSWORD=<pw> soulib-postgres psql -h <host> -p <port> -U root -d postgres -c "CREATE DATABASE soulib_test;"`

### 서버 복원
`docker exec -e PGPASSWORD=<pw> soulib-postgres pg_restore -h <host> -p <port> -U root -d soulib_test --clean --if-exists /tmp/soulib_test.dump`

## 6-1) 적재/병합/중복/인덱스 (상세)

### A. 적재(books + holdings)
- CSV → PostgreSQL 적재 스크립트: `scripts/load_csv_to_postgres.py`
- 적재 테이블: `books`, `holdings`
- 정규화 컬럼 생성: `title_norm`, `author_norm`, `publisher_norm`
- 정규화 기준 키: `title_norm + author_norm + publisher_norm`

### B. 병합/중복 정리 로직(개요)
- 스크립트: `scripts/merge_internal_duplicates.py`
1) `holdings.canonical_id` 생성
   - YES24: `yes24:<goods_id>`
   - 교보: `kyobo:<brcd>`
   - 북큐브/FxLibrary: `bookcube:<content_id>`
2) `books.canonical_id` 생성
   - 같은 상품(플랫폼 단위) 기준으로 book_id를 묶는 1차 식별자
3) 1차 병합: `books.merge_group_id = books.canonical_id`
4) 2차 병합(플랫폼 교차 병합)
   - 기준: `title_norm + author_norm (+ publisher_norm)`
   - 교보/YES24/북큐브 등 플랫폼을 넘어서 같은 책을 묶음
5) canonical_id 기준의 book_id 매핑 정리
   - holdings.canonical_id → books.canonical_id → holdings.book_id 연결

### C. 상세 페이지용 그룹 묶기(현재 서버 로직)
- `merge_group_id / canonical_id / id`로 그룹 book_id를 찾고,
  동일 `publisher_norm`까지 조건으로 맞춰서 holdings를 모음.
- 이 단계가 무거우면 상세 페이지 진입 시 느려질 수 있음.

### D. 인덱스(기본)
- `books`: title_norm/author_norm/publisher_norm + trgm
- `holdings`: book_id

### E. 추가 인덱스(속도 개선 후보)
- 그룹 조회 최적화용:
  - `books(merge_group_id, publisher_norm)`
  - `books(canonical_id, publisher_norm)`

### F. 구조 개선 아이디어(선택)
- `group_key` (예: `merge_group_id + ':' + publisher_norm`)를 사전 계산해
  서버에서 매번 그룹을 계산하지 않도록 개선 가능.

### G. 2026-02-11 중복 정리 1단계(범위 고정)
목표: 과거에 유입된 "완전 동일 중복"만 안전하게 정리하고, 재유입을 막는 잠금 조건을 확정한다.

이번 단계에서 자동 처리(포함):
- `books` 기준 `title_norm + author_norm + publisher_norm` 3개가 모두 같은 중복만 처리.
- 같은 중복 그룹에서 대표 `book_id` 1개를 남기고 나머지 `holdings`를 대표로 이관.
- 이관 완료 후 중복 `books` 행 정리 및 재유입 방지(복합 UNIQUE) 준비.

이번 단계에서 자동 처리하지 않음(제외):
- `goods_id/content_id/brcd`는 같은데 norm 3키가 다른 케이스(2단계에서 처리).
- 번역서/개정판/시리즈/부제처럼 텍스트 규칙 판단이 필요한 케이스(3단계에서 처리).
- 플랫폼별 식별자 매핑 보정(`canonical_id` 백필)은 2단계 작업.

실행 안전 게이트:
1) DB 백업 확보 전에는 삭제/병합 실행 금지.
2) dry-run 리포트(중복 그룹/행 수) 확인 전에는 삭제/병합 실행 금지.
3) 위험 그룹(`review`)은 자동 삭제 대상에서 제외.
4) 파괴적 변경 전 사용자 승인 후 실행.

1단계 성공 기준:
- `books`에서 동일 3키 중복 0건(또는 review 제외 잔여만 존재).
- `holdings` 이관 후 유실 0건, orphan 0건.
- 복합 UNIQUE 적용 후 동일 3키 재삽입 차단.

### H. 2026-02-11 정규화 규칙 동결(v1)
목표: 중복 정리 1단계 동안 `norm` 기준이 흔들리지 않도록 단일 규칙 파일로 고정한다.

정규화 기준(데이터 레이어):
- 버전: `db_norm_v1_2026-02-11`
- 단일 소스: `scripts/norm_rules.py`
- 적용 대상: `books.title_norm`, `books.author_norm`, `books.publisher_norm`
- 적용 스크립트:
  - `scripts/load_csv_to_postgres.py`
  - `scripts/recompute_norms.py`

운영 원칙:
1) v1 규칙은 in-place 수정 금지.
2) 규칙 변경이 필요하면 v2를 신규로 만들고, 재계산/검증/롤백 계획을 함께 수립.
3) 검색어 처리 규칙(`web/utils/normalize.py`)과 데이터 적재 규칙(`scripts/norm_rules.py`)은 목적이 다를 수 있으므로 분리 관리.

### I. 2026-02-11 Stage1 dry-run 후보 추출
목표: 삭제 실행 전에 exact-duplicate 그룹을 `safe/review`로 분류한다.

실행 스크립트:
- `scripts/stage1_dryrun_report.py`
- 예시:
  - `python scripts/stage1_dryrun_report.py`
  - `python scripts/stage1_dryrun_report.py --out docs/reports/stage1_dryrun_2026-02-11.json`

분류 기준(현재):
- `safe`: `book_isbn_cnt<=1 AND holdings_isbn_cnt<=1 AND brcd_cnt<=1 AND goods_cnt<=1 AND content_cnt<=1`
- `review`: 위 기준을 하나라도 초과하는 그룹

2026-02-11 dry-run 결과:
- total_dup_groups: `12,315`
- safe_groups: `6,700` (`safe_book_rows=13,474`)
- review_groups: `5,615` (`review_book_rows=11,879`)

### J. 2026-02-11 Stage1 실행 결과(완료)
실행:
- `python scripts/stage1_apply_exact_dedupe.py --apply --scope all --dedupe-holdings --add-unique`

결과:
- `books` exact 중복 그룹: `12,315 -> 0`
- `holdings(book_id, library_code)` 중복 그룹: `162,695 -> 0`
- `holdings` 재매핑: `16,700`건
- `books` 중복 행 삭제: `13,038`건
- `holdings` 내부 중복 정리 삭제: `200,330`건
- `books` 복합 UNIQUE 잠금 생성:
  - `uq_books_norm UNIQUE(title_norm, author_norm, publisher_norm)`

검증/리포트:
- `docs/reports/stage1_apply_2026-02-11.md`
- `docs/reports/stage1_baseline_2026-02-11.md`
- `docs/reports/stage1_dryrun_2026-02-11.json`
- `docs/reports/stage1_backup_2026-02-11.md`

### K. 2026-02-11 Stage2 실행 결과(식별자 기반 canonical 병합)
목표: `goods_id / brcd / content_id`로 `canonical_id`를 채우고, canonical 기준으로 `book_id`를 재정렬한다.

실행 스크립트:
- dry-run: `python scripts/stage2_apply_identifier_merge.py`
- apply: `python scripts/stage2_apply_identifier_merge.py --apply --dedupe-holdings`

식별자 규칙(요약):
1) `goods_id` -> `yes24:<goods_id>`
2) `brcd` -> `kyobo:<brcd>`
3) `content_id`:
   - crosswalk 가능하면 `yes24:`/`kyobo:`로 승격
   - 그 외는 플랫폼/도서관 namespace(`bookcube:`, `seoul:`, `sen:`, `gangnam:`, `eunpyeong:` 등)

결과:
- `holdings_canonical_filled`: `1,221,608`
- `holdings_reassigned_by_canonical`: `10,386`
- `books_single_canonical_set`: `439,661`
- `orphan_books_deleted`: `28,240`
- `holdings_deleted_by_book_library_dedupe`: `6,335`

사후 상태:
- `holdings`의 식별자 보유 행(`brcd/goods/content`) canonical 누락: `0`
- `holdings(book_id, library_code)` 중복 그룹: `0`
- canonical이 여러 book에 걸친 그룹: `0`

리포트:
- `docs/reports/stage2_dryrun_preapply_2026-02-11.md`
- `docs/reports/stage2_apply_2026-02-11.md`
- `docs/reports/stage2_backup_2026-02-11.md`

### L. 2026-02-11 Stage3 v1 (보수형 + 관리자 승인 필수)
목표: 자동 병합을 하지 않고, 프로그램이 만든 후보를 관리자 승인 후에만 반영한다.

운영 원칙:
1) 후보 생성은 프로그램(`rule_auto`)만 수행.
2) 최종 병합은 관리자 승인(`approved`)이 있어야만 실행.
3) 사용자 신고 기반 후보는 추후 단계에서 추가(현재 제외).
4) 의심 케이스는 병합하지 않고 `hold/rejected`로 유지.

구성:
- 후보 생성 스크립트:
  - `python scripts/stage3_build_review_queue.py`
- 승인건 적용 스크립트:
  - dry-run: `python scripts/stage3_apply_approved.py`
  - apply: `python scripts/stage3_apply_approved.py --apply --dedupe-holdings`
- 리뷰 큐 테이블:
  - `merge_review_queue`
  - `merge_review_log`

관리자 화면:
- 데이터 품질 관리자: `/admin/data-quality`
  - Stage3 후보 생성/적용 버튼 포함
- 리뷰 큐 화면: `/admin/data-quality/review`
  - 상태 필터(`new/hold/approved/rejected/applied`)
  - 후보별 승인/거절/보류/초기화

적용 흐름:
1) Stage3 후보 생성 실행
2) 리뷰 큐에서 관리자 판단(승인/거절/보류)
3) 승인건 적용 실행
4) postcheck(중복/orphan) 확인 및 리포트 기록

## 7) 큐레이션 관리 (현재)
### 데이터/렌더 구조
- 큐레이션 원본: `data/curations.json`
- 상세 본문 템플릿: `web/templates/curations/<slug>.html`
- 홈 화면 렌더: `web/templates/index.html` + `web/static/js/home.js`
- 상세 화면 렌더: `web/templates/curation_detail.html` + `web/static/js/curations.js`

### 관리자 저장 흐름
- 관리 URL: `/admin/curations`
- 저장 API: `/admin/curations/save`
- 로컬에서만 수정 허용:
  - `ENABLE_CURATION_ADMIN=1`
  - 요청 IP가 localhost(127.0.0.1 / ::1)
- 현재 `CURATION_ADMIN_TOKEN`은 사용하지 않음(환경변수+localhost로 제한).

### 로컬 반영 절차(권장)
1) `run_curation_admin.bat` 실행
2) `/admin/curations`에서 JSON 붙여넣기/수정 후 저장
3) `/curation/<slug>` 화면 확인
4) 결과물만 커밋/푸시
   - `data/curations.json`
   - `web/templates/curations/<slug>.html`

### 홈 카드 스타일
- `hero`, `ranked`, `basic`, `tilt`, `editorial`, `compact`, `news`
- 스타일 목록/설명은 `web/curations.py`의 `HOME_STYLE_OPTIONS` 단일 소스에서 관리.

### 저장 시 book_id 자동 확정
- 입력이 `books`(제목/저자)만 있어도 저장 시 DB 매칭으로 `book_ids` 자동 생성.
- 매칭 기준: 제목 우선 + 저자 보정(저신뢰 매칭은 제외).
- 저장 후 관리자 메시지로 확정 결과 표시
  - 예: `book_id 자동확정: 8/10 (미매칭 2권)`
- 결과적으로 발행 데이터는 `book_ids` 기반 렌더가 우선이며, 속도/정확도 모두 안정적.

## 8) 운영 원칙
- admin은 CSV 기준으로만 동작(DB와 분리)
- search는 PostgreSQL 기준으로만 동작
- 데이터 변경은 로컬 검증 후 서버 반영

## 9) 자주 보는 파일
- 관리자: web/app.py
- 검색: web/app_search.py
- 큐레이션 라우트: web/curation_routes.py
- 큐레이션 정의: web/curations.py
- CSV → DB 적재: scripts/load_csv_to_postgres.py
- 홈 큐레이션 JS: web/static/js/home.js
- 상세 큐레이션 JS: web/static/js/curations.js

## 10) 바뀌면 안되는 검색 조건
- 검색 결과의 총 도서 수는 필터/검색어 기준으로 항상 정확히 표시될 것
- 결과 정렬은 보유 도서 수(holdings 합계) 내림차순을 유지할 것
- 동일 검색 조건에서는 항상 같은 순서가 유지될 것(안정적 정렬)
- “더 보기”는 기존 결과를 변경하지 않고 뒤에 이어붙일 것
- “더 보기”를 눌러도 검색 조건이 바뀌지 않을 것
- 필터/결과 내 재검색을 해제하면 원래 결과로 복원될 것

## 11) 체크리스트
- CSV 생성 완료 여부
- 로컬 PostgreSQL 적재 완료
- 로컬 검색 정상
- 서버 덤프/복원 완료
- Cloudtype DB_NAME 확인 후 재배포

## 12) 플랫폼별 고유 ID/상태 조회 기준
- 교보(신버전): `brcd`
- YES24: `goods_id`
- 그 외(북큐브/서울/교육청/은평/강남 등): `content_id`
- 구독형(일부 플랫폼)은 상태 조회 제한 있음(필요 시 UI에서 조회 시도 차단).

### 제목 표기 vs 검색의 차이(주의)
- 상세/목록 표시는 원본 `books.title` 사용.
- 검색은 `title_norm`(정규화 제목) 기준 사용.
- 예: 제목에 `[구독형전자책]` 같은 태그가 붙어 있어도 검색 인덱스에서는 제거될 수 있음.

## 13) 진행 상황 업데이트 (2026-02-10)
- 큐레이션 홈 스타일 3종 추가: `tilt`, `editorial`, `compact`.
- 뉴스형 배너 스타일 추가: `news`(좌우 버튼 캐러셀).
- 홈 스타일 옵션/검증 기준을 `web/curations.py`로 단일화(`HOME_STYLE_OPTIONS`, `HOME_STYLE_VALUES`).
- 관리자 페이지에 스타일 가이드(유지보수용 설명) 추가.
- 큐레이션 저장 시 `books(제목/저자)` 입력만 있어도 `book_ids` 자동 확정 로직 반영.
- 저장 결과에 자동확정 요약 메시지 표시(확정/미매칭 권수).

## 14) 진행 상황 업데이트 (2026-01-29)
- 버그 수정: status_parsers/normalize/providers 한글 정규식 깨짐 복구(대출/예약/보유 파싱 정상화).
- 상태 조회: YES24/Bookcube/Gangnam detail-first로 우선 조회, Bookcube/Gangnam 페이지 탐색 상한 축소(속도 개선).
- UI/UX: 상세 페이지 도서관 배지 2줄(도서관명/상태), 색상·테두리·정렬 개선, 4열/6열 그리드 적용.
- UI/UX: 플랫폼 아이콘 제거 → “교보/YES24/기타 도서관” 텍스트 그룹 타이틀로 변경.
- UI/UX: 상태 로딩 시 스피너 표시 후 정렬 완료된 상태로 노출(중간 리플로우/정렬 보이는 문제 완화).
- 표시 규칙: 예약이 있으면 예약만 표기(대출가능 표기 숨김), 구독형은 “대출가능(구독)” 표기.

## 15) 진행 상황 업데이트 (2026-01-27)
- 교보/YES24: 크롤링 + 대출현황 조회 완료.
- 비(교보/YES24) 8개: 도봉/금천/성동/강남/은평/서울/서울교육청 구독/소장 크롤링 완료.
- 서울/교육청/은평: content_id 기반 상세 링크/상태 조회 API 추가.
- 도봉: 모바일 상세 URL로 전환, barcode 문자/숫자 혼합 대응.
- 적재: 8개 CSV 적재 실행(완료 여부/중복 여부 확인 필요).
- 이슈: 상세 페이지에서 동일 도서관 중복 표시 발생 → holdings 중복 여부 확인 필요.
- 이슈: 북큐브(성동/금천) 상세 페이지 상태 파싱이 0/0/0으로 나옴 → 상세 HTML 구조 재분석 필요.
- 과제: 기타 8개 도서관 상세 페이지/상태 현황 코드 전반 점검 필요.
- 과제: DB 적재/중복 병합 로직 대규모 수정 필요.

## 16) 진행 상황 업데이트 (2026-01-26)
- 서울도서관: elib API 전환(content_id=contentsKey) 완료, 체커는 카테고리 합산 방식으로 총권수 확인.
- 서울시교육청: 소장/구독 content_id 수집 완료(소장은 실시간 조회 가능, 구독은 무조건 대출가능 처리).
- 은평구립: content_id=ContentKey 수집 및 상세 링크/상태 조회 API 추가.
- 도봉: 상세 링크 모바일 버전으로 전환, brcd 문자 혼합/DRMContent 보정 완료.
- 적재: 8개 도서관 CSV만 로컬 PostgreSQL 적재 실행(진행 확인 필요).
- 남은 작업: 적재 완료 확인 후 상세/상태 샘플 테스트, 도봉 대출현황 API 여부 추가 확인.

## Cloudtype 외부 접속(운영)
HOST=svc.sel3.cloudtype.app
PORT=31659
DB_NAME=soulib_test
DB_USER=root
DB_PASSWORD=mkfleo93fe570fad

복원 명령:
docker exec -e PGPASSWORD=mkfleo93fe570fad soulib-postgres pg_restore -h svc.sel3.cloudtype.app -p 31659 -U root -d soulib_test --clean --if-exists /tmp/soulib_test.dump

## UX/UI 디자인 가이드
- 모바일 중심 Apple style UI 원칙은 `docs/UX_UI_Guide.md`를 기준으로 유지한다.
- 검색 결과 공급사 분류는 `교보`, `YES24`, `기타` 3개만 사용한다.
- 랜딩 페이지에는 검색과 직접 관련 없는 플랫폼 뱃지, 예시 결과, 장식 카드를 추가하지 않는다.
- 오류 신고는 `/reports`에서 접수하며, GitHub Issues를 단일 저장소로 사용한다.
- 배포 변경 내역은 `docs/RELEASE_NOTES.md`에 기록한다.

## Cloudtype 자동 배포
- GitHub Actions workflow: `.github/workflows/cloudtype-deploy.yml`
- `main` 브랜치에 push되면 Cloudtype GitHub webhook endpoint를 호출한다.
- GitHub 저장소 secret `CLOUDTYPE_API_KEY`가 필요하다. API 키는 저장소 파일에 직접 쓰지 않는다.
- Secret 등록 위치: GitHub repository `Settings > Secrets and variables > Actions > New repository secret`.
- 선택 사항: GitHub repository variables `CLOUDTYPE_PROJECT`, `CLOUDTYPE_APP`, `CLOUDTYPE_STAGE`를 설정하면 Cloudtype direct deploy endpoint(`/webhooks/deploy`)를 사용한다.
- `CLOUDTYPE_PROJECT`/`CLOUDTYPE_APP`이 없으면 GitHub push payload를 서명해서 `/webhooks/github`로 보낸다.

