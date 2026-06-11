# Agent Operating Model

이 문서는 `library_crawler` 프로젝트에서 Codex 메인 채팅방과 서브에이전트를 어떻게 운영할지 고정한 지침입니다.

## 기본 원칙

- 메인 채팅방은 Project Lead 역할을 맡는다.
- 실제 구현은 기본적으로 서브에이전트에게 위임한다.
- 메인 채팅방은 기획, 범위 정의, 작업 분해, 리뷰, 검증, 배포 판단을 우선한다.
- 지시서와 운영 문서 수정도 기본적으로 `Instruction Steward Worker`에게 위임한다.
- 명백한 오타 또는 깨진 링크 1줄 수정과 최종 통합 조정은 메인에서 직접 처리할 수 있다.
- 서브에이전트 작업은 항상 명확한 책임 범위와 파일 소유권을 지정한 뒤 시작한다.
- 여러 에이전트가 같은 파일을 동시에 수정하지 않도록 작업을 분리한다.
- 사용자 또는 다른 에이전트가 만든 변경을 되돌리지 않는다.
- 반복 지적이 발생한 영역은 구현을 계속하기 전에 운영 규칙과 검수 게이트를 먼저 보강한다.

## 채팅방 운영 기준

기본 구조는 `메인 채팅방 1개 + 역할별 서브에이전트 + 필요한 자동화`로 유지한다.

여러 메인 채팅방을 동시에 열면 결정, 배경 맥락, 커밋 상태, 배포 판단이 흩어진다. 따라서 메인 채팅방은 하나의 관제실로 유지하고, 작업 단위만 서브에이전트에게 분리한다.

메인 채팅방은 다음을 반드시 사용자에게 보이게 한다.

- 어떤 역할의 서브에이전트를 붙였는가
- 그 에이전트의 책임 범위와 수정 가능 파일은 무엇인가
- 메인이 직접 처리하는 일은 무엇인가
- 최종 검수에서 무엇을 확인했는가

메인이 조용히 혼자 구현하고 검수까지 끝내는 방식은 기본 운영 방식이 아니다.

## 작업 시작 게이트

메인 채팅방은 구현이나 파일 수정 전에 작업을 아래 중 하나로 분류한다.

- `Direct`: 메인이 직접 처리한다.
- `Explorer-required`: 원인, 영향 범위, 파일 위치를 먼저 조사한다.
- `Worker-required`: 역할별 Worker가 구현한다.
- `Instruction Steward Worker-required`: 지시서와 운영 문서 규칙 변경을 Instruction Steward Worker가 구현한다.
- `QA-required`: 구현 전후 검증 또는 배포 판단이 핵심이다.

`Direct`를 선택할 때는 직접 처리 사유를 한 줄로 남긴다. 예: `직접 처리 사유: 문서의 오타 1줄 수정`.

기본값은 다음과 같다.

- 코드, 템플릿, CSS, JS 변경: `Worker-required`
- 원인 불명 버그: `Explorer-required` 후 `Worker-required`
- 사용자-facing UI/UX 변경: `UX/UI Designer` 후 `Frontend Worker`
- 블로그 신규 작성/대폭 수정: `Content Writer` 후 `Editor/Fact Checker`
- 배포, CI, 자동화 변경: `QA-required`
- `AGENTS.md`, `README_DEV.md`, `docs/tasks.md` 같은 지시서/MD 운영 규칙 변경: `Instruction Steward Worker-required`
- 사용자가 반복 지적한 영역: `Explorer-required` 또는 `UX/UI Designer` 먼저
- 반복 지적이 운영 방식, 역할 분리, 검수 누락과 관련되면 구현 전 `Instruction Steward Worker-required`를 먼저 적용한다.

## 직접 처리 예외

메인 채팅방이 직접 처리할 수 있는 일은 아래로 제한한다.

- 지시서/MD의 명백한 오타 또는 깨진 링크 1줄 수정
- 지시서/MD 운영 규칙 변경이 아닌 버전 쿼리, 설정값 같은 단일 지점 수정
- 서브에이전트 결과를 통합하기 위한 작은 충돌 해결
- 테스트 실행, diff 확인, 커밋, 푸시, 배포 확인
- 사용자에게 바로 설명해야 하는 운영 판단

아래 작업은 원칙적으로 서브에이전트를 최소 1명 이상 붙인다.

- 사용자-facing UI, 레이아웃, CSS 수정
- 블로그 글 신규 작성 또는 대폭 수정
- 검색 결과, 상세, 내 서재, 오류 신고 같은 핵심 UX 변경
- 버그 신고 재현과 원인 분석
- 배포, GitHub Actions, Cloudtype, Search Console 자동화 변경
- 지시서/MD 운영 규칙 추가, 삭제, 재구성
- 사용자가 반복적으로 지적한 품질 문제 재발 방지 작업

메인이 직접 처리한 예외 작업도 최종 보고에는 `직접 처리 사유`, `검증`, `남은 위험`을 포함한다.

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
- 운영 지침 변경 필요성 기록, Instruction Steward Worker 위임, 결과 리뷰

메인 채팅방은 구현을 직접 시작하기 전에 먼저 아래를 결정한다.

- 이 작업이 직접 처리할 만큼 작은가
- 서브에이전트에 맡길 수 있을 만큼 범위가 명확한가
- 작업 파일이 다른 진행 중인 작업과 충돌하지 않는가
- 결과 검증 방법이 명확한가
- 지시서 변경이라면 단순 오타/링크 1줄 Direct 예외인지, 아니면 Instruction Steward Worker에게 맡길 일인지

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

### UX/UI Designer

용도: 사용자-facing 화면의 방향성, 정보 구조, 시각 밀도, 불필요한 장식 제거.

주요 담당 범위:

- `docs/UX_UI_Guide.md`
- `docs/mockups/`
- `web/templates/`
- `web/static/css/`
- `web/static/js/`

대표 작업:

- 구현 전 레이아웃 대안 제안
- 비포/애프터 스크린샷 기준 디자인 리뷰
- 불필요한 선, 색, 그림자, 텍스트 버튼, AI스러운 장식 제거
- 모바일 360-430px 기준 가독성, 터치 영역, 정보 밀도 점검
- Figma 또는 브라우저 스크린샷 기반 mockup 검토

규칙:

- UX/UI Designer는 직접 대규모 구현을 맡기보다 방향과 검수 기준을 먼저 잡는다.
- Frontend Worker는 UX/UI Designer가 정한 방향을 구현한다.
- 심미 리스크가 큰 변경은 구현 전 mockup 또는 스크린샷 비교를 남긴다.

### Content Writer

용도: 블로그 초안 작성과 주제 후보 정리.

주요 담당 범위:

- `content/blog/*.md`

대표 작업:

- 주제 후보 3개 이상 제안
- 독자 상황, 글의 목적, 추천 도서 후보 정리
- 선택된 주제의 초안 작성

규칙:

- Content Writer는 자기 글을 직접 발행 승인하지 않는다.
- 검색 카드, 표지 이미지, reference 링크를 임의로 끼워 넣지 않는다.
- 본문에 없는 책, Soulib에서 잡히지 않는 책, 관련 없는 이미지를 쓰면 실패로 본다.
- 초안 단계에서 커밋하지 않는다.

### Editor/Fact Checker

용도: 블로그 품질, 사실관계, 문체, 검색 연결 검수.

주요 담당 범위:

- `content/blog/_README.md`
- `content/blog/*.md`
- `scripts/blog_quality_check.py`
- `scripts/blog_live_search_audit.py`
- `web/static/img/blog/`

대표 작업:

- AI스러운 문장, 반복 라벨, 부자연스러운 유도문 제거
- 추천 도서가 실제 Soulib 검색 결과와 맞는지 확인
- 책 카드와 본문 책 설명이 1:1로 붙어 있는지 확인
- 대표 이미지가 글 주제의 실제 책 표지 세트인지 확인
- 참조한 외부 기사/공식 안내가 본문 인라인 링크로 연결됐는지 확인

규칙:

- Editor/Fact Checker는 발행 거부 권한을 가진다.
- deterministic check를 통과해도 글이 부자연스럽거나 서비스 신뢰를 떨어뜨리면 반려한다.
- Content Writer와 같은 에이전트가 Editor/Fact Checker 역할까지 겸하지 않는다.

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
- `vercel.json`
- `Dockerfile`
- `.cloudtype/`
- 배포 체크리스트 문서

대표 작업:

- smoke test 보강
- 재현 시나리오 작성
- GitHub Actions 실패 분석
- Vercel 배포와 live smoke test 점검
- 로컬 실행 검증 절차 정리

### Instruction Steward Worker

용도: `AGENTS.md`, `README_DEV.md`, `docs/tasks.md` 같은 지시서와 운영 문서의 규칙을 반복 가능하게 관리한다.

주요 담당 범위:

- `AGENTS.md`
- `README_DEV.md`
- `docs/tasks.md`
- 작업 유형별 가이드 문서. 단, 메인이 소유 파일로 명시한 경우에만 수정한다.

대표 작업:

- 사용자가 지적한 운영 실패나 반복 지적을 문서 규칙으로 반영
- Direct 예외, Worker 위임 기준, 검수 게이트 문구 정리
- 블로그, 디자인, 버그, 운영 자동화에서 새 문제가 나온 경우 관련 가이드 갱신 여부 확인
- 최종 보고에 `사용자 지적 -> 반영 문서/규칙` 매핑 작성

규칙:

- 지시서/MD 운영 규칙 변경은 기본적으로 이 Worker가 맡는다.
- 메인 채팅방은 직접 문서를 고치지 않고 변경 필요성 기록, 위임, 리뷰, 커밋/푸시만 맡는다.
- 단순 오타 또는 깨진 링크 1줄 수정만 Direct 예외로 허용한다.
- 구현 파일, 콘텐츠 파일, 자동화 파일은 소유 파일로 지정되지 않는 한 수정하지 않는다.
- 기존 사용자/다른 에이전트 변경을 되돌리지 않는다.

### Ops Watcher

용도: 신고 이슈, 배포 상태, 운영 이상 징후 감시.

대표 작업:

- GitHub Issues의 실제 오류 신고 확인
- GitHub Actions와 Vercel 배포/도메인 상태 점검
- Search Console 분석 가능 여부 확인
- 자동 수정 가능한 저위험 이슈와 사람 판단이 필요한 이슈 구분

규칙:

- 평시에는 과도하게 자주 돌리지 않는다.
- 새 대화창을 계속 만드는 방식은 피하고, 필요한 경우 현재 메인 채팅방에 요약 보고한다.
- 치명 이슈나 배포 지연 중일 때만 임시로 주기를 좁힌다.
- 감시 에이전트가 구현까지 수행할 때는 별도 Worker/QA 게이트를 거친다.

## 위임 절차

작업을 위임할 때 메인 채팅방은 서브에이전트에게 다음 정보를 명시한다.

- 역할: Explorer, Backend Worker, Frontend Worker, Crawler/Data Worker, QA/Release Worker, Instruction Steward Worker
- 목표: 한 문장으로 끝나는 구체적인 결과
- 소유 파일: 수정 가능한 파일 또는 디렉터리
- 금지 범위: 건드리면 안 되는 파일 또는 기능
- 완료 기준: 테스트, 응답 코드, 화면 상태, 문서 갱신 여부 등
- 보고 형식: 변경 파일, 핵심 변경, 실행한 검증, 남은 위험
- 메인은 병렬로 무엇을 할지: 겹치지 않는 조사, 문서화, 테스트 준비, 최종 리뷰 등

예시:

```text
Backend Worker로 진행.
목표: /api/live_search의 외부 타임아웃 처리 로그를 더 명확히 정리한다.
소유 파일: web/live_search/service.py, web/live_search/connectors/
금지 범위: templates, static, crawler는 수정하지 않는다.
완료 기준: python scripts/smoke_test.py 통과.
보고: 변경 파일, 변경 요약, 테스트 결과, 남은 위험.
```

## 작업 유형별 필수 게이트

### 블로그 글

블로그 글은 다음 순서를 통과해야 한다.

1. Content Writer가 주제 후보와 초안을 만든다.
2. Editor/Fact Checker가 문체, 사실관계, 책/카드/이미지 연결을 검수한다.
3. 책 추천 글은 `PYTHONPATH=web python scripts/blog_live_search_audit.py content/blog/<slug>.md`를 통과한다.
4. `python scripts/blog_quality_check.py --strict content/blog/<slug>.md`를 통과한다.
5. `python scripts/smoke_test.py`와 `git diff --check`를 통과한다.
6. 메인 채팅방이 diff를 검토한 뒤 커밋, 푸시, 배포 확인을 수행한다.

Content Writer 단독 발행은 금지한다. 자동화도 동일하다.

블로그 품질 문제나 발행 게이트 누락이 새로 드러나면 Content Writer 또는 Editor/Fact Checker 작업과 별도로 Instruction Steward Worker가 `content/blog/_README.md`, `AGENTS.md`, `README_DEV.md`, `docs/tasks.md` 등 관련 가이드 갱신 필요성을 검토한다.

### UI/UX 변경

UI/UX 변경은 다음 순서를 통과해야 한다.

1. UX/UI Designer가 문제 정의와 레이아웃 방향을 먼저 잡는다.
2. 심미 리스크가 있으면 mockup, Figma, 또는 브라우저 스크린샷으로 비포/애프터를 만든다.
3. Frontend Worker가 승인된 방향만 구현한다.
4. QA/Release Worker 또는 메인이 모바일/데스크톱 스크린샷을 확인한다.
5. 텍스트 겹침, 과한 굵기, 불필요한 선/그림자/색, 카드 안 카드, 깨진 이미지를 확인한다.

디자인 불만이 한 번 이상 나온 화면은 바로 구현을 반복하지 말고 UX/UI Designer 게이트로 되돌린다.

새 디자인 문제가 반복되거나 검수 기준 누락이 확인되면 UX/UI Designer 작업과 별도로 Instruction Steward Worker가 `docs/UX_UI_Guide.md`, `AGENTS.md`, `README_DEV.md`, `docs/tasks.md` 등 관련 가이드 갱신 필요성을 검토한다.

### 버그 신고

버그 신고는 다음 순서를 통과해야 한다.

1. Explorer가 재현 경로와 영향 범위를 찾는다.
2. Backend Worker 또는 Frontend Worker가 소유 파일을 제한해 수정한다.
3. QA/Release Worker가 재현 시나리오와 smoke test를 확인한다.
4. 메인 채팅방이 커밋, 푸시, 배포, 이슈 업데이트를 처리한다.

치명적 신뢰 오류는 비슷한 패턴을 전수 검색하고 회귀 테스트 또는 감사 스크립트를 추가한다.

버그 재발 원인이 역할 분리, 재현 절차, 검수 누락이면 Explorer 또는 구현 Worker와 별도로 Instruction Steward Worker가 관련 지시서 갱신을 맡는다.

### 배포와 운영 감시

배포/운영 감시는 다음 기준을 따른다.

- 배포 지연 확인 자동화는 성공하면 즉시 PAUSED로 바꾼다.
- 평시 Ops Watcher는 6시간 이상 간격 또는 주 1회 분석을 기본으로 한다.
- 신규 오류 신고가 들어온 직후, 배포 지연 중, 인증/검색 장애 의심 상황에서는 임시로 주기를 좁힐 수 있다.
- 자동화는 새 글/새 코드 발행보다 “감지, 요약, 게이트 통과 여부 확인”을 우선한다.
- 운영 자동화에서 새 문제가 나오면 QA/Release Worker와 별도로 Instruction Steward Worker가 해당 가이드 문서 갱신 필요성을 검토한다.

### Instruction Update Loop

사용자가 운영 방식, 역할 분리, 품질 게이트, 반복 지적 반영 누락을 지적하면 아래 순서를 따른다.

1. 메인 채팅방은 지적 내용, 발생 영역, 재발 위험을 기록한다.
2. 단순 오타 또는 깨진 링크 1줄이 아니면 `Instruction Steward Worker-required`로 분류한다.
3. Instruction Steward Worker에게 소유 파일, 금지 범위, 완료 기준, 보고 형식을 명시해 위임한다.
4. Worker는 지적 내용을 `AGENTS.md` 중심 규칙으로 반영하고, `README_DEV.md`와 `docs/tasks.md`에는 요약 또는 참조를 남긴다.
5. 블로그, 디자인, 버그, 운영 자동화에서 새 문제가 나온 경우 해당 작업 가이드도 함께 갱신할지 검토한다.
6. 메인 채팅방은 diff, 파일 소유권, `git diff --check`, 지적-규칙 매핑을 리뷰한 뒤 커밋/푸시 여부를 판단한다.
7. 최종 보고에는 어떤 지적이 어떤 문서 규칙으로 반영됐는지 매핑한다.

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
- 블로그 글은 Content Writer와 Editor/Fact Checker 역할이 분리됐는가
- UI 변경은 UX/UI Designer의 방향 검토 또는 스크린샷 비교가 있었는가
- 자동화가 발행/커밋 권한을 갖는 경우 QA 게이트가 별도로 있었는가
- 지시서 변경은 Instruction Steward Worker에게 위임됐는가
- 반복 지적은 Instruction Update Loop를 거쳐 문서 규칙으로 반영됐는가

최종 보고는 최소한 아래 항목을 포함한다.

- 작업 분류: Direct, Explorer-required, Worker-required, Instruction Steward Worker-required, QA-required 중 무엇이었는가
- 참여 역할: main, Explorer, Worker, Instruction Steward Worker, UX/UI Designer, Editor/Fact Checker, QA/Release 중 실제 참여자
- 변경 파일
- 사용자 지적 -> 반영 문서/규칙 매핑
- 검증 명령과 결과
- 미검증 항목이 있다면 사유
- 배포 또는 자동화 상태
- 남은 위험

## 서브에이전트 수명 관리

- 작업이 끝난 서브에이전트는 메인이 닫는다.
- agent thread limit에 걸리면 오래된 조사/작업 에이전트를 먼저 종료한다.
- 전담 인력처럼 쓰고 싶은 역할은 문서와 프롬프트로 유지하되, 실제 에이전트 스레드를 무기한 열어두지는 않는다.
- 장기 감시는 cron automation으로, 구현은 해당 시점의 Worker로 분리한다.

## 현재 프로젝트 기준

이 프로젝트의 현재 기본 운영 기준은 다음과 같다.

- 기준 저장소: GitHub `pkkong/library_crawler`
- 기본 개발환경: GitHub Codespaces
- 로컬 Mac mini: 예외적 개발/검증 환경
- 기본 앱: `web/app_search.py`
- 운영 entrypoint: `vercel.json -> index.py -> web/app_search.py`
- 기본 검색: DB 없는 실시간 검색
- 기본 검증: `python scripts/smoke_test.py`
- 배포 흐름: `main` push 또는 merge 후 GitHub Actions smoke test 통과, 이후 Vercel production 배포와 `https://www.soulib.kr` live smoke test
- Phase 0 운영 경로 정리는 문서와 inventory 정리만 수행했다. 현재는 Vercel + Supabase 운영 경로가 production 기준이다.
- 운영 경로와 레거시/보류 항목의 기준 inventory는 `docs/phase0_operating_inventory.md`를 우선 확인한다.

PostgreSQL 관련 코드는 아래 세 그룹으로 구분한다.

- 현재 운영 필요: 공유 서재 영속 저장처럼 production 기능을 지원하는 코드. 단, 검색 자체를 PostgreSQL에 의존시키지 않는다.
- 선택적 필요: 관리자, 데이터 품질, 로컬 DB 점검, CSV/PostgreSQL 적재처럼 별도 작업에서만 쓰는 코드.
- 완전 레거시/삭제 후보: 미사용 entrypoint, 과거 SQLite 검색, 과거 DB rebuild 또는 SQLite -> PostgreSQL 마이그레이션 흐름.

아래 항목은 현재 기본 운영 경로가 아니다.

- 레거시 SQLite/PostgreSQL 기반 검색
- `web/app_cloudtype.py` 같은 미사용 entrypoint
- 전수 크롤링 운영
- 큐레이션 운영
- 로컬 DB/CSV 산출물 보관
- 과거 DB rebuild 또는 dump/restore 운영 흐름

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
