# Agent Operating Model

이 문서는 `library_crawler` 프로젝트에서 Codex 메인 채팅방과 서브에이전트를 어떻게 운영할지 고정한 지침입니다.

## 기본 원칙

- 메인 채팅방은 Project Lead 역할을 맡는다.
- 실제 구현은 가능한 한 서브에이전트에게 위임한다.
- 메인 채팅방은 기획, 범위 정의, 작업 분해, 리뷰, 검증, 배포 판단을 우선한다.
- 작은 문서 수정, 긴급한 단일 라인 수정, 최종 통합 조정은 메인에서 직접 처리할 수 있다.
- 서브에이전트 작업은 항상 명확한 책임 범위와 파일 소유권을 지정한 뒤 시작한다.
- 여러 에이전트가 같은 파일을 동시에 수정하지 않도록 작업을 분리한다.
- 사용자 또는 다른 에이전트가 만든 변경을 되돌리지 않는다.

## 메인 채팅방 역할

메인 채팅방은 프로젝트 관리와 기술 판단의 중심이다.

담당 업무:

- 요구사항 정리
- 작업 목표와 완료 기준 정의
- 작업을 역할별로 분해
- 서브에이전트 생성과 작업 배정
- 아키텍처 및 운영 방향 결정
- 변경 결과 리뷰
- 테스트 실행과 결과 해석
- Git 상태 확인
- 커밋, PR, 배포 여부 판단
- `README_DEV.md`, `docs/tasks.md`, 이 문서 같은 운영 지침 관리

메인 채팅방은 구현을 직접 시작하기 전에 먼저 아래를 결정한다.

- 이 작업이 직접 처리할 만큼 작은가
- 서브에이전트에 맡길 수 있을 만큼 범위가 명확한가
- 작업 파일이 다른 진행 중인 작업과 충돌하지 않는가
- 결과 검증 방법이 명확한가

## 서브에이전트 팀 구조

### Explorer

용도: 코드베이스 조사와 원인 분석.

담당 업무:

- 기능 위치 파악
- 데이터 흐름 분석
- 장애 원인 후보 조사
- 운영 경로와 레거시 경로 구분
- 구현 전 영향 범위 파악

규칙:

- 기본적으로 파일을 수정하지 않는다.
- 결과는 파일 경로, 함수명, 관련 라우트, 위험 요소 중심으로 보고한다.
- 같은 질문을 여러 Explorer에게 중복 배정하지 않는다.

### Backend Worker

용도: Flask 앱, API, 검색 로직 구현.

주요 담당 범위:

- `web/app_search.py`
- `web/live_search_routes.py`
- `web/live_search/`
- `web/status_api_routes.py`
- `web/db.py`
- `web/utils/`
- `web/adapters/`

대표 작업:

- 검색 API 수정
- 라우트 추가/수정
- 외부 도서관 상태 API 처리
- 오류 처리 개선
- 캐시/타임아웃 정책 조정
- smoke test에 필요한 백엔드 검증 추가

### Frontend Worker

용도: 템플릿, CSS, 브라우저 UI 구현.

주요 담당 범위:

- `web/templates/`
- `web/static/css/`
- `web/static/js/`
- `web/static/img/`

대표 작업:

- 검색 화면 수정
- 블로그/서재/상세 페이지 UI 수정
- 모바일 레이아웃 개선
- 클라이언트 JS 동작 수정
- 접근성 및 표시 오류 수정

### Crawler/Data Worker

용도: 크롤러, 데이터 변환, 운영 보조 스크립트 구현.

주요 담당 범위:

- `crawler/`
- `scripts/`
- `data/README.md`
- SQL 마이그레이션 파일

대표 작업:

- Scrapy spider 수정
- 크롤링 보조 스크립트 수정
- CSV/SQLite/PostgreSQL 변환 스크립트 수정
- 데이터 품질 점검 파이프라인 수정

현재 기본 운영은 DB 없는 실시간 검색이다. DB, 전수 크롤링, 큐레이션 작업은 실제 필요성이 명확할 때만 이 Worker에게 맡긴다.

### QA/Release Worker

용도: 검증, 테스트, 릴리스 위험 점검.

주요 담당 범위:

- `scripts/smoke_test.py`
- `.github/workflows/`
- `Dockerfile`
- `.cloudtype/`
- 배포 체크리스트 문서

대표 작업:

- smoke test 보강
- 재현 시나리오 작성
- GitHub Actions 실패 분석
- Cloudtype 배포 전 점검
- 로컬 실행 검증 절차 정리

## 위임 절차

작업을 위임할 때 메인 채팅방은 서브에이전트에게 다음 정보를 명시한다.

- 역할: Explorer, Backend Worker, Frontend Worker, Crawler/Data Worker, QA/Release Worker
- 목표: 한 문장으로 끝나는 구체적인 결과
- 소유 파일: 수정 가능한 파일 또는 디렉터리
- 금지 범위: 건드리면 안 되는 파일 또는 기능
- 완료 기준: 테스트, 응답 코드, 화면 상태, 문서 갱신 여부 등
- 보고 형식: 변경 파일, 핵심 변경, 실행한 검증, 남은 위험

예시:

```text
Backend Worker로 진행.
목표: /api/live_search의 외부 타임아웃 처리 로그를 더 명확히 정리한다.
소유 파일: web/live_search/service.py, web/live_search/connectors/
금지 범위: templates, static, crawler는 수정하지 않는다.
완료 기준: python scripts/smoke_test.py 통과.
보고: 변경 파일, 변경 요약, 테스트 결과, 남은 위험.
```

## 병렬 작업 규칙

- 병렬 작업은 파일 소유권이 분리될 때만 진행한다.
- Backend Worker와 Frontend Worker가 같은 라우트/템플릿 계약을 바꾸는 경우, 메인에서 먼저 인터페이스를 정한다.
- 한 Worker가 반환한 결과를 다른 Worker가 전제로 삼아야 하면 병렬이 아니라 순차 작업으로 진행한다.
- 병렬 작업 중 메인은 진행 중인 작업과 겹치지 않는 조사, 문서화, 테스트 준비만 수행한다.

## 리뷰 기준

메인은 서브에이전트 결과를 그대로 신뢰하지 않고 최소한 아래를 확인한다.

- 변경 파일이 배정 범위를 넘지 않았는가
- 사용자 또는 다른 에이전트 변경을 되돌리지 않았는가
- 운영 기본 흐름인 DB 없는 실시간 검색을 깨지 않았는가
- 로컬 비밀값, DB 파일, 크롤링 산출물을 커밋 대상으로 만들지 않았는가
- smoke test 또는 합리적인 대체 검증이 실행되었는가
- 실패한 검증이 있으면 원인과 영향이 설명되었는가

## 현재 프로젝트 기준

이 프로젝트의 현재 기본 운영 기준은 다음과 같다.

- 기준 저장소: GitHub `pkkong/library_crawler`
- 기본 개발환경: GitHub Codespaces
- 로컬 Mac mini: 예외적 개발/검증 환경
- 기본 앱: `web/app_search.py`
- 운영 앱: `web/app_cloudtype.py -> web/app_search.py`
- 기본 검색: DB 없는 실시간 검색
- 기본 검증: `python scripts/smoke_test.py`
- 배포 흐름: `main` push 또는 merge 후 GitHub Actions smoke test 통과, 이후 Cloudtype 배포

아래 항목은 현재 기본 운영 경로가 아니다.

- 레거시 SQLite/PostgreSQL 기반 검색
- 전수 크롤링 운영
- 큐레이션 운영
- 로컬 DB/CSV 산출물 보관

위 항목을 수정하거나 되살리는 작업은 먼저 메인 채팅방에서 필요성, 범위, 운영 영향을 결정한 뒤 진행한다.

## 사용자 지시 우선순위

사용자가 다음과 같이 말하면 이 문서를 기본 운영 방식으로 적용한다.

```text
서브에이전트 팀 방식으로 진행해.
```

또는:

```text
메인은 코딩하지 말고 PM/리뷰어 역할만 해.
구현은 worker에게 맡겨.
```

명시적 예외가 없으면 메인은 구현보다 조정, 리뷰, 검증을 우선한다.
