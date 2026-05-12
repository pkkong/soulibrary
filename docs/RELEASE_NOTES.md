# 릴리즈 노트

## 2026-05-12 - 모바일 앱 셸 UX 및 오류 신고

### 요약
- Soulib 사용자 화면을 모바일 앱 중심 레이아웃으로 재정리했다.
- 홈, 검색, 상세, 오류 신고 페이지의 최대 폭을 `--app-shell-w: 430px`로 통일했다.
- 하단 내비게이션을 `홈 / 검색 / 신고` 구조로 변경했다.
- 간단한 오류 신고 페이지(`/reports`)를 추가했다.

### UX/UI 변경
- 랜딩 페이지에서 플랫폼 뱃지와 하드코딩된 예시 검색 결과를 제거했다.
- 검색 결과 화면을 데스크톱에서도 단일 열 모바일 목록으로 유지하도록 변경했다.
- 검색 결과 공급사 요약을 `교보`, `YES24`, `기타` 3개로 통일했다.
- 상세 페이지의 도서관 상태 조회는 카드가 먼저 보이고 상태만 순차 갱신되도록 개선했다.
- 신고 페이지의 분류 select 화살표를 커스텀 chevron으로 정렬했다.

### 기능 추가
- `/reports`에서 오류 신고를 접수한다.
- 신고 항목: 분류, 내용, 문제가 있던 주소, 선택 연락처.
- 최근 접수 목록을 표시하되 연락처는 공개하지 않는다.
- 운영 DB에 `error_reports` 테이블을 자동 생성한다.
- DB 연결이 없을 때는 JSONL 파일 fallback으로 저장한다.

### 운영 영향
- Cloudtype 앱은 `app_cloudtype.py`가 `app_search.py`를 import하는 구조라 이번 변경이 운영 앱에 반영된다.
- `live_search` 커넥터에서 `lxml`을 사용하므로 `requirements.txt`에 `lxml`이 포함되어야 한다.
- Cloudtype PostgreSQL 계정에 `CREATE TABLE`, `INSERT`, `SELECT` 권한이 필요하다.

### 검증
- `python -m py_compile web/app.py web/app_search.py web/report_routes.py`
- `python -m py_compile web/live_search/service.py web/live_search/normalizer.py web/live_search_routes.py web/utils/providers.py`
- `node --check web/static/js/search.js`
- 로컬 `/`, `/search`, `/reports` HTTP 200 확인.
- CSS에서 `880px`, `640px`, 데스크톱 2열 검색 결과 규칙 제거 확인.
