# 작업 메모

현재 기준 작업 메모입니다. 오래된 PostgreSQL/큐레이션/전수 크롤링 운영 메모는 기본 운영 기준이 아니므로 이 문서에서 제거했습니다.

## 현재 목표

- 모든 작업은 GitHub `pkkong/library_crawler`를 기준으로 이어갑니다.
- 집 PC, 회사 PC, 모바일은 GitHub/Codex/Codespaces에 접속하는 단말로 사용합니다.
- 로컬 PC에 프로젝트 원본이나 대용량 데이터 산출물을 계속 보관하지 않습니다.

## 현재 운영 구조

- 기본 검색: DB 없는 실시간 검색
- 운영 앱: `web/app_cloudtype.py -> web/app_search.py`
- 신고 접수: GitHub Issues
- 배포: GitHub Actions smoke test 통과 후 Cloudtype deploy action
- 데이터 산출물: Git 미포함, 필요 시 별도 백업/작업 환경에서 생성

## 표준 작업 흐름

```text
작업 분류: Direct / Explorer-required / Worker-required / QA-required
-> 역할 배정: Explorer / Worker / UX/UI Designer / Editor / QA
-> 파일 소유권 지정
-> 조사 또는 구현
-> 메인 리뷰
-> python scripts/smoke_test.py
-> git diff --check
-> commit/push
-> PR
-> main merge
-> GitHub Actions 성공 확인
-> Cloudtype 반영 확인
```

## 작업 유형별 운영 메모

- 블로그 글은 Writer가 초안을 쓰고 Editor/Fact Checker가 반려 권한을 가진다. 추천글은 `scripts/blog_live_search_audit.py`를 통과해야 한다.
- UI/UX 변경은 UX/UI Designer가 방향을 잡고 Frontend Worker가 구현한다. 심미 리스크가 있으면 모바일/데스크톱 스크린샷을 남긴다.
- 원인 불명 버그는 Explorer가 먼저 재현과 영향 범위를 찾고, 구현 Worker는 별도로 둔다.
- 배포 감시는 성공하면 자동화를 멈추고, 평시 Ops Watcher는 과도하게 자주 돌리지 않는다.
- 메인 채팅방은 최종 판단과 커밋/배포를 맡되, 혼자 구현부터 검수까지 끝내지 않는다.

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
4. 레거시 DB/큐레이션 코드는 실제 운영 필요성이 생길 때만 별도 정리
