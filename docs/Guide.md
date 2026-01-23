# Guide.md

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
