# 작업 메모 (공용)

## 인수인계 요약
- PostgreSQL 전환 완료(로컬/서버 모두 사용).
- 로컬 Docker PostgreSQL: `soulib-postgres` (port 5432, user root, db postgres, pw localpass).
- Cloudtype 환경변수: DB_HOST=postgresql / DB_PORT=5432 / DB_NAME=postgres / DB_USER=root / DB_PASSWORD=시크릿.
- 검색 로직: 서버에서 도서관 수 기준 정렬 + 페이지네이션.
- 최근 UI 변경: 검색결과 문구 따옴표/크기 조정, 결과 내 재검색(Enter/적용), 필터 텍스트 크기 맞춤.
- run_search.bat에 로컬 PostgreSQL 기본 환경변수 설정.
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