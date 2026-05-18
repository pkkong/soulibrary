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
branch 생성
-> 수정
-> python scripts/smoke_test.py
-> commit/push
-> PR
-> main merge
-> GitHub Actions 성공 확인
-> Cloudtype 반영 확인
```

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
