# 작업 메모 (공용)

## 인수인계 요약
- PostgreSQL 전환 완료(로컬/서버 모두 사용).
- 로컬 Docker PostgreSQL: `soulib-postgres` (port 5432, user root, db postgres, pw localpass).
- Cloudtype 환경변수: DB_HOST=postgresql / DB_PORT=5432 / DB_NAME=postgres / DB_USER=root / DB_PASSWORD=시크릿.
- 검색 로직: 서버에서 도서관 수 기준 정렬 + 페이지네이션.
- 최근 UI 변경: 검색결과 문구 따옴표/크기 조정, 결과 내 재검색(Enter/적용), 필터 텍스트 크기 맞춤.
- `run_search.bat`는 검색/상세 테스트 전용(큐레이션 관리자 비활성).
- 큐레이션 갱신은 `run_curation_admin.bat`로 로컬에서만 수행.
- 남은 작업: commit/push → Cloudtype 재배포, SSL 인증서 발급 확인, `soulib.kr` 루트 → `www` 포워딩 확인.

## 사용 가이드 (Codex)
- 작업 시작 전 이 문서를 읽고 현재 상태/규칙을 확인한다.
- **필수: 모든 사용자 노출 문자열은 한글 + UTF-8로 유지한다.** (깨짐 발견 시 즉시 수정)
- 추측으로 구현하지 말고, 필요한 정보는 질문 후 진행한다.
- 변경 사항은 이 문서에 기록하고, 완료 항목은 날짜를 남긴다.
- 채팅방이 바뀌어도 **매일 마지막 작업 이후 변경점**을 아래 "일일 업데이트" 섹션에 추가한다.
- 일일 업데이트는 하루에 1회, 최신 날짜를 맨 위에 쌓는다.
- 배포/운영 영향이 있는 변경은 "운영/배포"에 반드시 기록한다.

## 표준 작업 흐름 (로컬 → 배포)
### A. 코드/UI 변경
1) 로컬에서 수정 및 테스트(로컬 PostgreSQL 사용).
2) 변경 내용 정리 후 GitHub commit/push.
3) Cloudtype 재배포.

### B. 데이터(정규화/중복 제거 등) 변경
1) 크롤링 → CSV 생성.
2) CSV → 로컬 PostgreSQL 적재(데이터 갱신).
3) 로컬에서 검색/화면 확인(문제 없으면 OK).
4) Cloudtype PostgreSQL에 동일 데이터 적재.
5) 서비스 정상 동작 확인(`/`, `/search`, `/book/<id>`).

#### Cloudtype 적재 절차(요약)
1) 로컬에서 CSV → PostgreSQL 적재 완료 후 검증.
2) Cloudtype PostgreSQL 접속 정보 확인(DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD).
3) 동일 CSV를 Cloudtype PostgreSQL로 적재.
4) 배포 재시작/재배포 후 `/api/search` 및 화면 정상 동작 확인.

### C. 운영 반영 원칙
- 코드 변경은 GitHub로, 데이터 변경은 PostgreSQL 적재로 반영한다.
- SQLite는 중간 검증용이었으나 현재는 PostgreSQL 중심으로 운영한다.

## 큐레이션 기능 정리 (기획/개발)
### 현재(운영 상태)
- 홈(`/`) 큐레이션은 `data/curations.json` 기반 동적 렌더링.
- 큐레이션 전용 목록/상세 페이지 운영:
  - `/curations`
  - `/curation/<slug>`
- 하단 메뉴 5개 운영(홈/가이드/검색/오늘의책/오류신고).
- 큐레이션 상세는 본문 템플릿(`web/templates/curations/<slug>.html`) + 관련 도서 카드 조합으로 노출.

### 한 일
- 큐레이션 관리자 페이지 구축:
  - `/admin/curations`
  - 저장/삭제 라우트 분리
- 홈 카드 스타일 확장:
  - 기존: `hero`, `ranked`, `basic`
  - 추가: `tilt`, `editorial`, `compact`, `news(좌우버튼 배너)`
- 스타일 옵션/검증 기준을 `web/curations.py` 단일 소스로 통합.
- 큐레이션 저장 시 `books(제목/저자)` 입력을 `book_ids`로 자동 확정(매칭 실패는 제외).
- 관리자 접근 제어 단순화:
  - `ENABLE_CURATION_ADMIN=1` + localhost 요청만 허용
  - `CURATION_ADMIN_TOKEN` 미사용

### 문제/한계
- 본문/책 목록 품질은 입력 원본(LLM output) 품질에 크게 의존.
- 자동 매칭에서 일부 책은 미매칭 또는 오매칭 가능성 존재(발행 전 점검 필요).
- 제목 원문 태그(`[구독형전자책]`)와 검색 인덱스(`title_norm`) 정책 차이로 사용자 혼선 가능.

### 계획(기획 관점)
- 반자동 제작 파이프라인 고정:
  1) LLM으로 큐레이션 JSON 생성
  2) 관리자 페이지에 JSON 붙여넣기
  3) 저장 시 `book_ids` 자동 확정
  4) 미매칭 도서 수동 보정 후 발행
- 발행 기준을 `book_ids 우선`으로 강제해 속도/정확도 안정화.
- 큐레이션 타입(오늘의책/오늘의작가 등) 확장 시 kicker 기반으로 통일 운영.

### 해야 할 일(개발)
- 자동확정 결과(미매칭 목록)를 관리자 화면에 상세 표시.
- 발행 모드에서 미매칭 1권 이상이면 저장 경고/차단 옵션 추가.
- 큐레이션 본문 템플릿 에디터 UX 개선(미리보기/검증).
- 검색 인덱스 정책과 원문 제목 태그 정책(예: `[구독형전자책]`) 정리.

### 확장(회원 기능 이후)
- 최근 댓글 달린 책/좋아요 많은 책 기반 큐레이션.
- 사용자 리스트(“XXX님이 만든 리스트”) 노출.
- 개인화 추천 큐레이션(내 서재/관심 작가 기반).

## DB 작업 모음
- 서울도서관/서울시교육청 크롤러 데이터 정리(풀네임 표기 이상 원인 추적 및 수정)
- 증분 적재 방식 설계/도입(풀 적재 대체)
- 표준화(정규화) 규칙 정비 및 문서화
- 중복 제거 기준 조정 및 영향(BOOK_ID 변동) 정리
- CSV → PostgreSQL 적재 성능 개선(배치/인덱스/병렬화)

## PostgreSQL 적재 설계 (CSV → DB)
### 배경
- SQLite 기반 빌드는 기존 중간 단계였지만, 운영/테스트를 PostgreSQL 중심으로 전환한다.
- books/holdings 분리와 중복 제거 로직은 그대로 유지하되 DB가 PostgreSQL로 바뀐다.

### 중복 제거 기준
- `title_norm + author_norm + publisher_norm` 조합으로 중복 판단.
- books는 1회만 저장, holdings는 도서관별 소장 데이터로 계속 저장.

### 정규화 기준
- `normalize_text()`로 공백/특수문자 정리 + 소문자화.
- CSV의 title/author/publisher에서 `_norm` 값을 생성해 사용.

### 적재 흐름(핵심)
1) 크롤링 → CSV 생성
2) title/author/publisher 정규화(`_norm` 생성)
3) books upsert
   - `books` UNIQUE(title_norm, author_norm, publisher_norm)
   - 충돌 시 기존 id 재사용
4) holdings insert
   - book_id와 함께 소장 정보 저장
5) 인덱스 생성
   - books(title_norm/author_norm/publisher_norm)
   - holdings(book_id)

### 로컬/서버 반영 흐름
- 로컬: CSV → 로컬 PostgreSQL 적재 → 로컬 서버로 확인
- 서버: 같은 CSV를 Cloudtype PostgreSQL에 적재 → 서비스 재시작/확인

### 스크립트/도구
- CSV → PostgreSQL: `scripts/load_csv_to_postgres.py`
- SQLite 레거시(보관용): `scripts/build_library_split.py`, `scripts/build_sqlite.py`,
  `scripts/migrate_sqlite_to_postgres.py`, `scripts/migrate_split_to_postgres.py`

## 일일 업데이트 (템플릿)
### YYYY-MM-DD
- 변경 요약:
- 기능 개선:
- 버그 수정:
- 운영/배포:
- 다음 계획:

### 2026-05-12
- 변경 요약: 사용자-facing 화면을 공통 앱 셸(`--app-shell-w: 860px`) 기준으로 통일하고, 모바일에서는 단일 열 UI를 유지.
- 기능 개선: 하단 내비게이션을 홈/검색/신고 구조로 정리하고, `/reports` 오류 신고 페이지 추가.
- 기능 개선: 검색 결과 공급사 요약을 교보/YES24/기타 3분류로 통일하고, 데스크톱 2열 검색 결과 레이아웃 제거.
- 기능 개선: 상세 페이지 도서관 상태 조회 시 카드 선노출 후 상태를 순차 갱신하도록 개선.
- 기능 개선: 검색 결과에서 상세 진입 시 실시간 검색을 반복하지 않도록 상세 캐시를 추가하고, 통합 검색의 중복 플랫폼 요청을 축소.
- 기능 개선: iOS 홈 화면 저장용 apple-touch-icon을 불투명 정사각형 아이콘으로 교체하고 manifest를 추가.
- 운영/배포: 릴리즈 노트 추가(`docs/RELEASE_NOTES.md`), Cloudtype 배포 대상은 `app_cloudtype.py -> app_search.py`.
- 다음 계획: Cloudtype 재배포 후 `/`, `/search`, `/reports`, 상세 페이지 동작 확인.


### 2026-02-11
- 변경 요약: 중복 정리 1단계 범위를 문서로 고정(`docs/Guide.md` 6-1.G).
- 변경 요약: 정규화 규칙 동결(v1) 단일 소스 추가(`scripts/norm_rules.py`).
- 기능 개선: 1단계 자동 처리 대상을 "완전 동일 3키(title_norm/author_norm/publisher_norm)"로 제한.
- 기능 개선: 1단계 제외 대상을 명시(식별자 동일·norm 상이 케이스는 2단계 canonical 백필로 이관).
- 기능 개선: `load_csv_to_postgres.py`/`recompute_norms.py`가 동일 norm 버전을 공통 사용하도록 정리.
- 기능 개선: 1-2 베이스라인 수치 리포트 추가(`docs/reports/stage1_baseline_2026-02-11.md`).
- 기능 개선: 1-4 dry-run 후보 추출 자동화 스크립트 추가(`scripts/stage1_dryrun_report.py`).
- 기능 개선: dry-run 결과 기록(`safe_groups=6,700`, `review_groups=5,615`).
- 운영/배포: 롤백용 백업 생성 완료(`/tmp/soulib_test_stage1_20260211.dump`, 약 62MB, 보고서: `docs/reports/stage1_backup_2026-02-11.md`).
- 운영/배포: Stage1 본 실행 완료(`scripts/stage1_apply_exact_dedupe.py --apply --scope all --dedupe-holdings --add-unique`).
- 기능 개선: exact 중복 그룹 제거 완료(`books`: 12,315→0, `holdings(book_id,library_code)`: 162,695→0).
- 기능 개선: 데이터 정리 반영(`holdings` 재매핑 16,700건, `books` 13,038행 삭제, `holdings` 중복 200,330행 삭제).
- 기능 개선: `books` 복합 UNIQUE 잠금 생성(`uq_books_norm`).
- 운영/배포: 적용 결과 리포트 추가(`docs/reports/stage1_apply_2026-02-11.md`).
- 운영/배포: 파괴적 변경 전 백업/dry-run/승인 게이트를 필수 조건으로 명문화.
- 변경 요약: Stage2 식별자 기반 canonical 병합 스크립트 추가(`scripts/stage2_apply_identifier_merge.py`).
- 운영/배포: Stage2 적용 전 백업 생성 완료(`/tmp/soulib_test_stage2_20260211_preapply.dump`, 약 59MB, 보고서: `docs/reports/stage2_backup_2026-02-11.md`).
- 기능 개선: Stage2 dry-run 결과 기록(`fillable_rows=1,221,608`, `book_map_rows=8,151`).
- 기능 개선: Stage2 본 실행 완료(`--apply --dedupe-holdings`).
- 기능 개선: Stage2 적용 결과(`holdings_canonical_filled=1,221,608`, `holdings_reassigned_by_canonical=10,386`, `orphan_books_deleted=28,240`).
- 기능 개선: 식별자 보유 holdings의 canonical 누락 제거(`brcd/goods/content 누락 0`), canonical 다중-book 그룹 0.
- 운영/배포: Stage2 결과 리포트 추가(`docs/reports/stage2_dryrun_preapply_2026-02-11.md`, `docs/reports/stage2_apply_2026-02-11.md`).
- 기능 개선: 데이터 품질 관리자 대시보드 추가(`/admin/data-quality`, `web/data_quality_admin.py`).
- 기능 개선: Stage1/Stage2 dry-run/apply를 관리자 화면 버튼으로 실행하는 반자동 운영 플로우 추가.
- 기능 개선: CSV 적재 버튼 추가(증분 `CSV_ONLY`, 전체 재구축 `MIGRATE_DROP=1`)로 데이터 적재도 data-admin에서 실행 가능.
- 기능 개선: Stage3 보수형 파이프라인 추가(후보 생성 스크립트 `scripts/stage3_build_review_queue.py`, 승인건 적용 스크립트 `scripts/stage3_apply_approved.py`).
- 기능 개선: 관리자 승인 필수 리뷰 큐 화면 추가(`/admin/data-quality/review`, 승인/거절/보류/초기화).
- 기능 개선: 리뷰 큐 DB 스키마/로그(`merge_review_queue`, `merge_review_log`)와 상태 지표 카드 연동.
- 운영/배포: Stage3 후보 생성 동작 검증(`--limit 200` 실행, `pairs_fetched=200`, `queue_total=225`, `status=new`).
- 기능 개선: 운영 배치 스크립트 추가(`run_data_admin.bat`), 큐레이션 관리자에서 데이터 품질 화면 이동 링크 추가.
- 다음 계획: 3단계 텍스트 병합(저자/출판사 alias + 번역/개정/시리즈 예외 규칙) 설계 및 적용.

### 2026-02-10
- 변경 요약: 큐레이션 로컬 운영 기준 정리(`run_search.bat`는 검색 전용, 큐레이션 수정은 `run_curation_admin.bat` 전용).
- 기능 개선: 홈 카드 스타일 추가/확장(`tilt`, `editorial`, `compact`, `news`), 스타일 가이드를 관리자 화면에 반영.
- 기능 개선: 큐레이션 저장 시 `books` 입력만으로 `book_ids` 자동확정(저장 결과에 확정/미매칭 수 표시).
- 기능 개선: 큐레이션 렌더를 `book_ids` 우선으로 고정해 속도/정확도 안정화.
- 운영/배포: 로컬에서 큐레이션 생성/수정 후 결과물(`data/curations.json`, `web/templates/curations/<slug>.html`)만 Git 반영.
- 다음 계획: 관리자에서 미매칭 도서 상세 목록/경고 정책 추가.

### 2026-01-28
- 변경 요약: app_search.py 역할 분리(상태/정규화/HTTP 유틸 분리) 진행.
- 변경 요약: 검색/상세 그룹핑 기준에 publisher_norm 포함(검색/상세 동일 기준 적용).
- 변경 요약: status/search/book 라우팅 오류 로그 출력 보강.
- 변경 요약: 검색/상세/상태 로직이 app_search.py에 과도하게 집중됨 → 역할 분리 계획 수립.
- 다음 계획: app_search.py 라우팅 중심으로 축소, 검색/상태/상세/파서/HTTP 유틸 모듈 분리.

### 2026-01-29
- 변경 요약: status_parsers/normalize/providers 한글 정규식 깨짐 복구 및 파서 안정화.
- 버그 수정: 교보/YES24/북큐브 정규식 예외(`nothing to repeat`) 이슈 해결.
- 변경 파일: `web/adapters/status_parsers.py`, `web/utils/normalize.py`, `web/utils/providers.py`.
- UI 개선: 도서관 배지 2줄(도서관/상태), 4열/6열 그리드, 색상/강조 정리.
- UI 개선: 플랫폼 아이콘 제거 후 `교보/YES24/기타 도서관` 텍스트 그룹 타이틀 적용.
- UX 개선: 상태 로딩 중 스피너 표시 후 정렬 완료 상태로 노출(중간 리플로우 완화).
- 표시 규칙: 예약이 있으면 예약 우선 표기, 구독형은 `대출가능(구독)` 표기.
- 조회 방식: YES24/Bookcube/Gangnam `detail-first` 우선 조회, 일부 탐색 상한 축소로 속도 보정.
- 이슈 메모: merge 그룹 내 holdings 중복으로 상세 중복 노출 사례 확인.

### 2026-01-25
- 변경 요약: 서울시교육청 소장 content_id=contentsKey, 구독 content_id=ucm_code 수집 추가.
- 변경 요약: 서울도서관 elib API 확인(`/api/contents/{contentsKey}`)로 대출/예약 현황 조회 가능 확인.
- 변경 요약: 서울도서관 목록 API는 catesearch 기반으로 전환 필요 확인(기존 응답 items=0).
- 진행 상태: 남은 수정 대상은 서울도서관/은평구립도서관. 나머지 도서관은 크롤링 완료.
- 진행 상태: 교보/YES24는 크롤링 및 대출 현황 조회까지 완료.
- 다음 계획: 서울/은평 수정 후 재크롤링 → DB 적재 → 동작 테스트.

### 2026-01-26
- 변경 요약: 서울도서관 크롤러를 elib API로 전환(content_id=contentsKey) 및 총권수 체크(카테고리 합산)로 체커 보정.
- 변경 요약: 서울시교육청(소장/구독) content_id 수집 추가 및 저장 경로(data/) 고정.
- 변경 요약: 은평구립 content_id=ContentKey 추가 및 상세 URL/실시간 상태 API 설계.
- 변경 요약: 성동/금천/강남/서울/교육청/은평 상태 조회 API 추가 및 상세 링크 보강.
- 변경 요약: 도봉 상세 링크를 모바일 URL로 전환.
- 버그 수정: 도봉 brcd 문자 혼합 패턴 수집/CSV 보정, load_csv_to_postgres ON CONFLICT 오류 회피 로직 추가.
- 진행 상태: 8개 도서관 CSV 크롤링 완료, 로컬 PostgreSQL에 8개만 적재 실행(진행 확인 필요).
- 남은 작업: 적재 완료 확인 후 앱에서 상태/상세 샘플 테스트, 도봉 대출현황 API 여부 추가 확인.
- 아이템: CSV/DB 컬럼 다이어트 검토(필수 컬럼만 유지, library/image_url/isbn 등 중복·규칙 필드 축소 및 동적 생성 고려).

### 2026-01-27
- 변경 요약: 도봉 brcd 누락 원인 수정(문자/숫자 혼합 barcode 지원) 및 CSV에서 DRMContent → 실제 brcd로 교정.
- 변경 요약: 도봉 상세 링크를 모바일 상세 URL로 전환(Barcode 기반).
- 변경 요약: 서울/교육청/은평 실시간 대출현황 API 추가(서울/교육청/은평은 content_id 기반).
- 변경 요약: 구독형 Kyobo(광진/강동/서대문/송파/양천) 상태 조회 호출 차단(구독형은 상태 조회 안 함).
- 변경 요약: 강남 크롤러 중복 제거(content_id 기준 dedupe) 추가.
- 변경 요약: load_csv_to_postgres.py에서 빈 문자열 → NULL 처리로 중복 holdings 방지.
- DB 작업: holdings 중복 제거(빈 문자열/NULL 정규화 후 dedupe) 실행.
- 크롤링 상태: 8개 도서관 CSV 수집 완료(도봉/금천/성동/강남/은평/서울/서울교육청 구독/소장).
- 적재 상태: 8개 도서관 CSV 적재 실행(완료 여부/중복 여부 확인 필요).
- 적재 후 검증: 상세 페이지 URL 샘플 확인(도봉 제외 7개 200 OK), 도봉은 모바일 URL 200 OK 확인.
- 문제/대응: 강남 CSV 중복 확인 후 정리된 파일 확보(24,734 rows, 중복 0).
- 다음 작업: 강남만 재적재 실행(명령: load_csv_to_postgres.py --csv-only gangnam).
- 이슈: 상세 페이지에서 동일 도서관 중복 표시 발생(holdings 중복 여부 재확인 필요).
- 메모: CSV/DB 컬럼 다이어트(불필요 필드 최소화) 검토 필요.
- 메모: 병합 규칙 재설계 필요(서로 다른 출판사/다른 brcd가 동일 merge_group_id로 묶이는 사례 발생). 후속 과제.
- 메모: 북큐브(성동/금천) 상세 페이지 상태 파싱이 0/0/0으로 나옴. 상세 HTML 구조 재분석 필요.
- 메모: 기타 8개 도서관의 상세 페이지 및 상태 현황 코드 수정 필요.
- 메모: DB 적재/중복 병합 로직 대규모 수정 필요.
### 2026-01-24
  - 변경 요약: 교보 신버전 크롤러에서 brcd/ctts_dvsn_code/ctgr_id/sntn_auth_code 수집 추가.
  - 기능 개선: 도서 상세에서 교보 실시간 대출/예약 상태 조회 API 및 표시 추가, 소장 도서관 리스트 UI 정돈/정렬 및 상세 보기 토글 추가(미확정).
  - 기능 개선: 검색 성능 개선을 위해 2자 이하 검색어는 prefix 매칭으로 제한.
  - 버그 수정: 없음.
  - 운영/배포: 없음.
  - 다음 계획: CSV 재생성 후 PostgreSQL 적재 및 상세 화면 상태 표시 확인.

### 2026-01-18
- 변경 요약: 홈/검색 UI 여백 및 정렬 정비, 하단 메뉴에 블로그 추가, 전체 타이포 스케일 정비.
- 기능 개선: 검색 오버레이 입력 포커스(iOS 대응 포함), 검색 페이지 상단 검색바 고정 + 경계선, 검색 페이지 상단 타이틀 제거, 홈 타이틀은 비고정으로 유지.
- 버그 수정: app_search.py 들여쓰기/한글 깨짐 복구(공급사 라벨/에러 문구/도서관 수).
- 운영/배포: 없음.
- 다음 계획: 결과 내 재검색 UX 재검토(토글/노출 방식 결정) 및 필요 시 재설계.

## 현재 구조 요약
- 크롤링/정제는 로컬 전용.
- 서버는 검색 전용 앱만 실행.
- DB는 split 구조(books/holdings) 사용.
- 운영은 PostgreSQL 전환 진행 중(로컬 SQLite는 이관/검증용).

폴더 구조(정리 기준)
- data/raw: 크롤러 출력 CSV/JSON
- data/build: 빌드된 DB (library.db, library_split.db)
- pipeline: DB 빌드/검증 스크립트
- web: 검색/관리자 웹 앱
- crawler: scrapy 및 커스텀 수집 스크립트

## 검색/관리자 분리
- 검색 전용: web/app_search.py
- 관리자/크롤러: web/app.py
- 로컬 실행 스크립트
  - run_search.bat → app_search.py
  - run_admin.bat → app.py
- Dockerfile CMD: app_search.py (Cloudtype에서는 app_cloudtype.py로 교체됨)

## 크롤러/체커 역할
- 크롤링이 언제 되어 있는지
- 크롤링이 잘 되어 있는지(에러 여부)
- 로컬 CSV 권수 vs 원격 권수 비교
- 그래서 지금 다시 크롤링할 필요가 있는지 판단

## DB 빌드 역할 (별도)
- 각 도서관 CSV를 통합해 검색용 DB 생성
- 중복 제거/정규화
- 관리자 화면에서 자동으로 빌드하지 않음 (필요 시 수동 실행)

## 최근 작업 기록
- 2026-01-13: split DB 재빌드 완료 (`data/library_split.db`, rows=1,541,683 / books=575,581 / holdings=1,541,683).
- 2026-01-13: 웹앱 자동 DB 재빌드 기본 OFF 설정 (`LIBRARY_AUTO_BUILD`, `LIBRARY_AUTO_REBUILD` 환경변수로만 실행).
- 2026-01-13: 관리자 화면 안내 추가(크롤→CSV, DB 빌드는 수동 스크립트).
- 2026-01-13: guro TLS 경고 숨김 처리 (`crawler_manager.py`에서 InsecureRequestWarning 비활성화).
- 2026-01-13: 검색 전용 앱 분리 및 포트 분리 (`web/app_search.py`, `run_search.bat`, 기본 포트 5001 / `LIBRARY_SEARCH_PORT` 지원).
- 2026-01-13: 검색 UI 정리(검색창 아래에 검색결과/필터 요약 배치, 컨테이너 폭/여백 조정).
- 2026-01-13: 검색 결과 카드의 도서관 표시를 요약 형태로 변경(교보/YES24/기타 개수 표시, 0개는 흐림 처리).
- 2026-01-13: 카드 내 공급사 요약을 우측 하단 정렬 및 아이콘/배지 스타일 개선(교보/YES24 아이콘, 기타 배지, 스쿼클 스타일 적용).
- 2026-01-13: 검색 결과 숫자 표시 개선(천단위 콤마).
- 2026-01-13: 검색 결과 0건/오류 메시지를 결과 카드 영역에 동일 스타일로 표시하도록 변경.
- 2026-01-13: 검색 결과 정렬을 “보유 도서관 수 많은 순”으로 변경(동점이면 제목 순).
- 2026-01-13: 검색 결과/에러 메시지 UI 정리(0건일 때는 “검색 결과 0권”만 표시, 나머지 에러/필터0건은 결과 카드 영역에서 표시).
- 2026-01-13: 검색 결과 상단(검색 결과/필터) 레이아웃 간격 변수 도입 및 여백 조정(일부 미세 조정은 추가 확인 필요).
- 2026-01-13: 검색 결과 카드 클릭 시 도서 상세 페이지(`/book/<book_id>`) 추가 및 카드 클릭 이동 연결.
- 2026-01-13: 도서 상세 UI 구성(커버 블러 배경, 닫기/찜 UI, 섹션 구성/타이포 조정, 저자 클릭 시 해당 저자 검색으로 이동).
- 2026-01-13: 도서 상세 소장 도서관 UI 개선(플랫폼별 그룹핑: 교보/YES24/기타 + 도서관 태그 표시, 안내 문구/구분선/폭 제한/태그 스타일 조정).
- 2026-01-14: 메인(`/`) 홈 페이지 분리(상단 1줄 고정 헤더 + 본문 비움) 및 검색 페이지를 `/search`로 분리.
- 2026-01-14: 모든 페이지 하단 고정 메뉴바 추가(홈/검색, 아이콘+텍스트; 추후 최대 5개 확장 예정).
- 2026-01-14: 검색 API 엔드포인트를 `/api/search`로 변경(페이지 `/search`와 분리).
- 2026-01-14: 하단 메뉴바의 검색 버튼을 페이지 이동이 아닌 “바텀 시트 검색창”으로 변경(입력 후 `/search?q=...`로 이동).
- 2026-01-14: 검색 페이지에서도 상단 검색창을 없애고, 검색은 바텀 시트로만 입력하도록 통일(`/search`에 `q` 없으면 시트 자동 오픈).
- 2026-01-14: iOS에서 스크롤 시 하단 메뉴바가 밀려 보이는 현상 완화(safe-area 반영, fixed 합성 레이어 처리, iOS에서 backdrop-filter 비활성화).
- 2026-01-14: 메인 홈 본문에 “북 큐레이션” 섹션(가로 스크롤) 3종 스타일 추가(표지 강조/순위 강조/기본) 및 렌더링 JS 추가(`web/static/js/home.js`).
- 2026-01-14: 큐레이션용 책 메타 조회 API 추가(`/api/books?ids=...`).
- 2026-01-14: 홈 큐레이션 섹션을 흰색 패널로 처리하고, 섹션 간 여백(배경색 노출)으로 자연스럽게 구분되도록 개선.
- 2026-01-14: 홈 큐레이션 커버강조형(히가시노) 캐러셀 적용(중앙 카드 강조 + 무한 스크롤), PC 드래그 스크롤 지원, 커버/배경 크기 조정.
- 2026-01-14: 홈 큐레이션 트랙 좌우 여백 미세 조정(모바일 기준 타이틀 정렬 + 스크롤 시작 위치 보정).
- 2026-01-14: 커버강조형(히가시노) 카드 동작 단순화(크기 고정, 무한 스크롤 유지, 스냅/강조 제거) 및 PC 클릭/드래그 개선.
- 2026-01-14: 커버강조형 배경 비율을 정사각형에 가깝게 조정하고, 전면 표지 크기/여백 재조정.
- 2026-01-14: 커버강조형 카드 그림자 제거 및 얇은 테두리로 정리(카드 사이 배경 톤 일치).
- 2026-01-14: 히가시노 섹션을 “디지털 e북 카페 추천 도서”로 변경하고 카페 링크 추가, book_id 기반 큐레이션으로 교체.
- 2026-01-14: 비트코인 섹션 타이틀/링크 추가, 찬호께이 섹션 타이틀/더보기 링크 추가.
- 2026-01-14: 검색 API 페이징 도입(`/api/search` total+items, limit/offset) 및 검색 UI 더보기 연동.
- 2026-01-14: 검색 화면 필터 옆 세모 중복 제거.
- 2026-01-15: Cloudtype용 스타터 추가(app_cloudtype.py, DB 빌드 완료 전 503 처리).
- 2026-01-15: PostgreSQL 전환 준비(`web/db.py` 추가, sqlite/postgres 자동 전환).
- 2026-01-15: PostgreSQL 이관 스크립트 추가(`scripts/migrate_sqlite_to_postgres.py`).
- 2026-01-15: PostgreSQL 드라이버 추가(`psycopg2-binary`).
- 2026-01-15: PostgreSQL 데이터 이관 완료(books=577,197 / holdings=1,531,278).
- 2026-01-16: Cloudtype soulib 환경변수에 PostgreSQL 접속 정보 설정(DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD).
- 2026-01-16: 도메인 `soulib.kr` DNS 설정(CNAME/TXT) 및 Cloudtype 도메인 인증 완료.
- 2026-01-16: 검색 결과 총권수 표시(total 파싱) 보정(`web/static/js/search.js`).
- 2026-01-16: 로컬 PostgreSQL 기반 실행 스크립트 추가(run_search.bat에 DB 환경변수 기본값 설정).
- 2026-01-16: 검색 결과 내 재검색 입력 추가(적용 버튼/Enter로 반영, 즉시 반영 제거).
- 2026-01-16: 검색 결과 문구 스타일 개선(따옴표 표시, 텍스트 크기 확대, 필터 텍스트 크기 맞춤).
- 2026-01-17: 로컬 PostgreSQL `soulib_test` 적재 완료(CSV → PostgreSQL).
- 2026-01-17: 로컬 PostgreSQL `postgres` vs `soulib_test` counts 일치 검증(books=577,197 / holdings=1,531,278).
- 2026-01-17: 샘플 검색(찬호께이) 결과 일치 검증(books=21).

## 서울도서관 OpenAPI (전자책 필터)
- 옵션 파라미터 순서: TITLE / AUTHOR / CTRLNO / ISBN / BIB_TYPE
- BIB_TYPE만 필터할 때는 빈 칸을 %20으로 채워야 함
  - 정상 예: `/%20/%20/%20/%20/ze`
  - 잘못된 예: `/BIB_TYPE/ze`, `////ze`, `/////ze` (필터 무시됨)
- 정상 확인값: list_total_count=29440, row.BIB_TYPE=ze

## Cloudtype 배포 이슈(요약)
- 컨테이너 파일은 영구 저장 불가(디스크 마운트 미지원).
- 임시 DB 빌드는 재시작 시 소실 → 운영용으로 부적합.
- 해결 방향: PostgreSQL로 전환하여 네트워크 DB 사용.

## 다음 할 일
- Cloudtype soulib 서비스에 PostgreSQL 환경변수 세팅 확인(DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD).
- 변경 코드 commit/push 후 재배포.
- 배포 후 `/`, `/search`, `/book/<id>` 정상 동작 확인.
- SSL 인증서 발급 완료 확인 및 보안 경고 해소.
- `soulib.kr` → `www.soulib.kr` 포워딩 설정 여부 확인.
- (큰 할일) 도서 상세 페이지 구성 고도화(섹션 추가/광고 배치/추천 등)
- (내일) 홈 화면 UI 미세 조정(모바일/PC: 큐레이션 트랙 시작/끝 여백, 스크롤 시 정렬/여백 체감)
- 큐레이션 기능 자동화 및 기능 정비
- 중복된 책 해결 방안 마련
- 소셜 계정 연동(로그인/계정 연동 플로우 설계)

- 2026-01-17: 검색/필터/재검색 수정.
- 2026-01-17: 상단 (beta) 표시, 도서관 수만 표기.
- 2026-01-17: 표준화 규칙 강화 및 CSV->PostgreSQL 적재 반영.
- 크롤러/크롤러체커 개선 + DB 증분 업데이트 정비
