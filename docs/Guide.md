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
run_search.bat

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

## 7) 큐레이션 관리
- 홈 큐레이션은 book_id 하드코딩
- 파일: web/static/js/home.js
- 섹션: 카페 / 비트코인 / 찬호께이 / 정유정 / 정해연

## 8) 운영 원칙
- admin은 CSV 기준으로만 동작(DB와 분리)
- search는 PostgreSQL 기준으로만 동작
- 데이터 변경은 로컬 검증 후 서버 반영

## 9) 자주 보는 파일
- 관리자: web/app.py
- 검색: web/app_search.py
- CSV → DB 적재: scripts/load_csv_to_postgres.py
- 큐레이션: web/static/js/home.js

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

## 13) 진행 상황 업데이트 (2026-01-29)
- 버그 수정: status_parsers/normalize/providers 한글 정규식 깨짐 복구(대출/예약/보유 파싱 정상화).
- 상태 조회: YES24/Bookcube/Gangnam detail-first로 우선 조회, Bookcube/Gangnam 페이지 탐색 상한 축소(속도 개선).
- UI/UX: 상세 페이지 도서관 배지 2줄(도서관명/상태), 색상·테두리·정렬 개선, 4열/6열 그리드 적용.
- UI/UX: 플랫폼 아이콘 제거 → “교보/YES24/기타 도서관” 텍스트 그룹 타이틀로 변경.
- UI/UX: 상태 로딩 시 스피너 표시 후 정렬 완료된 상태로 노출(중간 리플로우/정렬 보이는 문제 완화).
- 표시 규칙: 예약이 있으면 예약만 표기(대출가능 표기 숨김), 구독형은 “대출가능(구독)” 표기.

## 14) 진행 상황 업데이트 (2026-01-27)
- 교보/YES24: 크롤링 + 대출현황 조회 완료.
- 비(교보/YES24) 8개: 도봉/금천/성동/강남/은평/서울/서울교육청 구독/소장 크롤링 완료.
- 서울/교육청/은평: content_id 기반 상세 링크/상태 조회 API 추가.
- 도봉: 모바일 상세 URL로 전환, barcode 문자/숫자 혼합 대응.
- 적재: 8개 CSV 적재 실행(완료 여부/중복 여부 확인 필요).
- 이슈: 상세 페이지에서 동일 도서관 중복 표시 발생 → holdings 중복 여부 확인 필요.
- 이슈: 북큐브(성동/금천) 상세 페이지 상태 파싱이 0/0/0으로 나옴 → 상세 HTML 구조 재분석 필요.
- 과제: 기타 8개 도서관 상세 페이지/상태 현황 코드 전반 점검 필요.
- 과제: DB 적재/중복 병합 로직 대규모 수정 필요.

## 15) 진행 상황 업데이트 (2026-01-26)
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

