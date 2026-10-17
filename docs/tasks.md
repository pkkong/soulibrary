# 작업 메모

현재 기준 작업 메모입니다. 오래된 PostgreSQL/큐레이션/전수 크롤링 운영 메모는 기본 운영 기준이 아니므로 이 문서에서 제거했습니다.

## 현재 목표

- 모든 작업은 GitHub `pkkong/soulibrary`를 기준으로 이어갑니다.
- 집 PC, 회사 PC, 모바일은 GitHub/Codex/Codespaces에 접속하는 단말로 사용합니다.
- 로컬 PC에 프로젝트 원본이나 대용량 데이터 산출물을 계속 보관하지 않습니다.

## 현재 운영 구조

- 기본 검색: DB 없는 실시간 검색
- 운영 entrypoint: `vercel.json -> index.py -> web/app_search.py`
- 신고 접수: GitHub Issues
- 배포: GitHub Actions smoke test 통과 후 Vercel production deploy, 이후 `https://www.soulib.kr` live smoke test
- 데이터 산출물: Git 미포함, 필요 시 별도 백업/작업 환경에서 생성
- Phase 0 운영 경로 정리: 문서와 inventory만 갱신한 이전 단계. 현재 production은 Vercel + Supabase 기준
- 운영 inventory: `docs/phase0_operating_inventory.md`

## PostgreSQL/DB 코드 분류

- 현재 운영 필요: 공유 서재 영속 저장처럼 production 기능을 지원하는 코드. 검색 자체는 DB 없는 실시간 검색을 유지한다.
- 선택적 필요: 관리자, 데이터 품질, 로컬 DB 점검, CSV/PostgreSQL 적재 작업.
- 완전 레거시/삭제 후보: 미사용 entrypoint, 과거 SQLite 검색, 과거 DB rebuild 또는 SQLite -> PostgreSQL 마이그레이션 흐름.

## 표준 작업 흐름

```text
작업 분류: Direct / Explorer-required / Worker-required / Instruction Steward Worker-required / QA-required
-> 역할 배정: Explorer / Worker / UX/UI Designer / Editor / QA / Instruction Steward Worker
-> 파일 소유권 지정
-> 조사 또는 구현
-> 메인 리뷰
-> 반복 지적이면 사용자 지적과 반영 문서 규칙 매핑 확인
-> python scripts/smoke_test.py
-> git diff --check
-> commit/push
-> PR
-> main merge
-> GitHub Actions 성공 확인
-> Vercel production 배포와 `https://www.soulib.kr` live smoke test 확인
```

## 작업 유형별 운영 메모

- 블로그 글은 Writer가 초안을 쓰고 Editor/Fact Checker가 반려 권한을 가진다. 추천글은 `scripts/blog_live_search_audit.py`를 통과해야 한다.
- UI/UX 변경은 UX/UI Designer가 방향을 잡고 Frontend Worker가 구현한다. 심미 리스크가 있으면 모바일/데스크톱 스크린샷을 남긴다.
- 개발자스럽거나 AI스러운 상태 문구 지적은 [UX_UI_Guide.md](UX_UI_Guide.md)의 문구·표시 조건 검수로 돌아간다. 필터·넓은 검색·상세 조회 중과 실제 실패를 구분하고, 정상/실패/0건의 모바일·데스크톱 회귀를 확인한다. 단어 교체나 경고 일괄 삭제만으로 완료하지 않는다.
- 원인 불명 버그는 Explorer가 먼저 재현과 영향 범위를 찾고, 구현 Worker는 별도로 둔다.
- 배포 감시는 성공하면 자동화를 멈추고, 평시 Ops Watcher는 과도하게 자주 돌리지 않는다.
- 로그인 요청 전 기존 connector·CLI·CI의 승인된 접근 경로를 확인하고 가능한 작업을 계속한다. 브라우저 세션 만료나 새 인프라의 추가 권한 요건을 기존 배포 전체의 차단으로 단정하지 않는다. 실제 접근 불가 판단과 최소 사용자 조치 기준은 [AGENTS.md](../AGENTS.md#배포와-운영-감시)를 따른다.
- SEO 자동 개선은 `측정 -> 진단 -> 저위험 자동 수정 후보 -> 콘텐츠/UX 개선안 -> QA -> 배포 검증` 루프로 운영한다.
- SEO 자동화의 기본 권한은 GitHub issue, Growth Queue, 자동 점검 결과와 사람 검토용 초안까지이며 글/랜딩 문구/이미지/UI 자동 발행은 금지한다.
- SEO 작업은 Growth Analyst, Technical SEO Worker, Content Writer, Editor/Fact Checker, QA/Release Worker 역할을 분리한다.
- Search Console credential과 token은 `.secrets/`, GitHub Actions secrets, 운영 secret에만 두고 로그/문서/issue/PR에 원문을 출력하지 않는다.
- Search Console API 인증 만료/권한 실패는 기본 `--auth-failure-mode dry-run`으로 처리해 SEO Growth workflow가 빨간 실패로 쌓이지 않게 한다. 실제 지표 자동화 복구는 `GSC_SERVICE_ACCOUNT_JSON`을 우선하고, 강제로 실패를 드러내야 하는 점검에만 `--auth-failure-mode fail`을 쓴다.
- 메인 채팅방은 최종 판단과 커밋/배포를 맡되, 혼자 구현부터 검수까지 끝내지 않는다.
- `AGENTS.md`, `README_DEV.md`, `docs/tasks.md` 같은 지시서/MD 운영 규칙 변경은 기본적으로 Instruction Steward Worker가 맡는다.
- 반복 지적이 나오면 Instruction Update Loop로 지적 내용을 관련 문서 규칙에 반영하고, 최종 보고에 `사용자 지적 -> 반영 문서/규칙` 매핑을 남긴다.
- 블로그, 디자인, 버그, 운영 자동화에서 새 문제가 나오면 해당 가이드 문서 갱신 필요성도 함께 검토한다.
- 서비스 검토·관측성·검색 신뢰·레거시 삭제의 근거와 게이트는 [service_observability.md](service_observability.md)를 따른다. 현재 승인된 검색어·방문자·이용 데이터를 측정하되 실제 traffic/개별 query/account 식별자는 공개 문서에 넣지 않는다.
- GSC workflow 성공과 실제 수집 여부를 별도로 표시한다. `dry-run` fallback은 측정 장애이며, 내부 트래픽 필터가 Testing 상태이면 실제 제외된 것으로 보고하지 않는다.

## SEO/Growth 운영 큐

- 매일 audit: Search Console 성과, 색인/크롤링 이상, 주요 landing page 상태, production smoke 신호를 확인한다.
- 주간 Growth Queue issue: 기회와 위험을 우선순위, 예상 영향, 담당 역할, QA 필요 여부로 정리한다.
- 주간 저위험 수정 후보: technical SEO 수정이나 문서성 개선안을 queue로 정리하되 자동 PR/merge는 하지 않는다.

## 커밋 금지

- `data/*.csv`
- `data/*.json`
- `data/*.db`
- `data/*.sqlite*`
- `.env`
- 토큰/비밀번호
- 로컬 백업 파일
- 캐시/로그

## 다음 우선순위

1. Codespaces/Codex Cloud에서 새 작업이 바로 가능한지 확인
2. 모바일에서 브랜치/PR/배포 상태를 확인하는 운영 흐름 고정
3. 검색 상세 오류 신고가 들어오면 GitHub Issue 기준으로 재현, 수정, 고객용 처리 로그 작성
4. 남은 레거시 DB·data/admin 코드는 실제 필요성과 참조/route 근거를 확인한 뒤 별도 정리. 미등록 큐레이션 묶음의 삭제 기록은 [public_repository_inventory.md](public_repository_inventory.md) 참고
5. Cloudtype은 해지 대상이므로 rollback 경로가 아니라 과거 운영 기록으로만 취급

## 서비스 감사 후속 큐

1. GSC 인증 유지·재만료·실수집 검증, GA 내부 방문/QA 실제 제외, 맞춤항목 처리와 미완성 기간 이후 집계 확인. 이벤트 실수집은 원시 수치를 공개하지 않고 ignored 보고서에 근거를 남긴다
2. 검색 cache/동시 요청/partial 신뢰는 앞선 QA·배포를 확인했다. 후속 deadline/cache 변경도 회귀를 통과했다. 릴리즈는 CI·배포·live smoke까지 확인한다.
3. 상세 후보 공통 deadline, 도봉 fallback 협력형 시간 예산, 상태 TTL cache 상한은 구현·QA 완료. 실행 중 HTTP 강제 중단/전체 hard wall과 공급사별 TLS 예외 범위는 남은 한계이며 별도 조사한다
4. 신고 목록 pagination·해결 상태의 사실성 검토. 공개 연락처 저장 제거 후에도 과거 신고의 개인정보는 별도 점검
5. 기능별 회귀가 확보된 뒤 `app_search.py`와 공통 CSS를 점진적으로 분리. 대규모 구조 변경과 디자인 변경을 한 번에 섞지 않는다
