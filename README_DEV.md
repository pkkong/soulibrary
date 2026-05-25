# Library Crawler Development Guide

이 저장소의 기준 원본은 GitHub `pkkong/library_crawler`입니다. 기본 개발환경은 GitHub Codespaces입니다. 로컬 PC는 프로젝트 파일을 보관하는 장소가 아니라, GitHub/Codex/Codespaces에 접속하는 단말로 봅니다.

## 기본 원칙

- 작업은 GitHub Codespaces에서 합니다.
- 회사 컴퓨터, 집 컴퓨터, 핸드폰에는 프로젝트 파일을 둘 필요가 없습니다.
- 로컬 clone은 긴급 복구나 특수 테스트가 필요할 때만 사용합니다.
- 코드, 템플릿, 설정, 문서는 GitHub에 커밋합니다.
- 로컬 DB, 크롤링 산출 CSV, 캐시, 로그, 개인 토큰은 GitHub에 올리지 않습니다.
- DB 없는 실시간 검색을 기본 개발 모드로 봅니다.
- DB/PostgreSQL은 과거 데이터 관리나 관리자 작업이 필요할 때만 붙입니다.

## 에이전트 운영 방식

Codex 메인 채팅방은 기획, 계획, 감시, 리뷰, 검증, 운영 지침 관리를 맡고, 실제 구현은 가능한 한 역할별 서브에이전트에게 위임합니다.

자세한 팀 구조와 위임 규칙은 [AGENTS.md](AGENTS.md)를 기준으로 합니다.

## Codespaces에서 시작

GitHub 저장소에서 아래 순서로 엽니다.

```text
Code > Codespaces > Create codespace
```

Codespaces가 열리면 `.devcontainer` 설정으로 Python 환경을 만들고 `requirements.txt`를 설치합니다.

서버 실행:

```bash
python web/app_search.py
```

기본 URL:

```text
http://127.0.0.1:5001/
http://127.0.0.1:5001/search
```

Codespaces에서는 포트 `5001`이 자동 포워딩됩니다. 모바일이나 다른 컴퓨터에서는 포워딩된 브라우저 URL로 확인합니다.

## 작업 완료 기준

작업 완료는 파일 수정만을 뜻하지 않습니다. 아래까지 끝나야 완료입니다.

```text
코드 수정
→ Codespaces에서 실행 확인
→ python scripts/smoke_test.py 통과
→ commit/push
→ main 반영
→ GitHub Actions smoke test 통과
→ Cloudtype 배포 트리거 확인
```

## 환경변수

필요한 값은 `.env.example`을 참고합니다. 기본 실시간 검색은 별도 DB 없이 실행됩니다.

주요 값:

```text
LIBRARY_SEARCH_PORT=5001
LIVE_SEARCH_TOTAL_TIMEOUT=5.8
LIVE_SEARCH_LIBRARY_TIMEOUT=4.5
LIVE_SEARCH_MAX_WORKERS=40
```

PostgreSQL이 필요한 작업에서만 아래를 설정합니다.

```text
DATABASE_URL=
DB_HOST=
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=
```

공유 서재는 운영에서 `SHARED_SHELVES_STORAGE=auto`를 사용합니다. `DATABASE_URL` 또는 `DB_HOST` 계열 env가 실제로 주입되면 Cloudtype PostgreSQL에 저장하고, 연결값이 없으면 JSON 저장으로 fallback해 공유 링크 생성 자체는 막지 않습니다. 로컬 smoke test나 DB 없는 개발에서는 `SHARED_SHELVES_STORAGE=json`과 `SHARED_SHELVES_FILE`을 사용할 수 있습니다.

Search Console 분석 자동화는 서비스 계정 또는 OAuth desktop client로 실행할 수 있습니다. credential과 token JSON은 `.secrets/` 또는 GitHub/운영 secret에만 보관하고 Git에는 올리지 않습니다.

서비스 계정을 쓸 때는 먼저 서비스 계정에 `soulib.kr` Search Console 속성 접근 권한을 부여합니다.

```text
GSC_SITE_URL=sc-domain:soulib.kr
GSC_SERVICE_ACCOUNT_FILE=.secrets/search-console-service-account.json
GSC_SERVICE_ACCOUNT_JSON=
```

Google Cloud org policy로 서비스 계정 키 생성이 막힌 환경에서는 OAuth desktop client JSON을 내려받은 뒤 최초 1회 브라우저 인증으로 token 파일을 만듭니다. token 내용은 출력하지 않습니다.

```text
GSC_OAUTH_CLIENT_FILE=.secrets/search-console-oauth-client.json
GSC_OAUTH_TOKEN_FILE=.secrets/search-console-oauth-token.json
```

```bash
python scripts/search_console_report.py --authorize
python scripts/search_console_report.py
```

## 배포

`main`에 push 또는 merge되면 GitHub Actions가 먼저 smoke test를 실행합니다. smoke test가 통과하면 공식 Cloudtype deploy action이 `.cloudtype/app.yaml` 설정으로 운영 서비스를 갱신합니다.

자동배포에는 GitHub Actions secret 하나가 필요합니다.

```text
CLOUDTYPE_API_KEY
```

이 키는 Cloudtype API 호출에 사용합니다. Cloudtype 서비스는 Git 저장소 `https://github.com/pkkong/library_crawler.git`의 `main` 브랜치를 바라봐야 합니다.

오류 신고는 GitHub Issues를 단일 저장소로 사용합니다. Cloudtype에는 아래 런타임 secret/env가 유지되어야 합니다.

```text
GITHUB_ISSUE_TOKEN = Cloudtype secret soulib-report-issues
GITHUB_ISSUE_REPO = pkkong/library_crawler
```

Docker 기본 실행은 DB 없는 검색 앱입니다.

```bash
docker build -t library-crawler .
docker run --rm -p 5000:5000 library-crawler
```

클라우드 플랫폼이 `PORT`만 주는 경우에도 `app_search.py`가 `PORT`를 읽습니다. `LIBRARY_SEARCH_PORT`가 있으면 그 값을 우선합니다.

## 커밋 기준

커밋 대상:

- `web/`, `scripts/`, `crawler/`, `pipeline/` 코드
- `templates`, `static` UI 파일
- `requirements.txt`, `Dockerfile`, `.devcontainer`, 문서

일반적으로 커밋하지 않을 것:

- `data/*.csv`, `data/*.json`
- `data/*.db`, `data/*.sqlite*`
- 로컬 캐시/상태 파일
- 크롤링 결과 CSV 변경분
- `.env`, 토큰, 개인 설정
- 로컬 백업 ZIP

`data/`에는 `README.md`만 Git에 남깁니다. 크롤링 결과, 과거 CSV DB, 임시 JSON, 로컬 SQLite/PostgreSQL 덤프는 필요할 때 각 작업 환경에서 생성하거나 별도 백업 위치에서 내려받습니다.

작업 전후 확인:

```bash
git status -sb
python scripts/smoke_test.py
```

## 로컬 clone이 필요한 예외 상황

아래 상황이 아니면 로컬 clone을 기본으로 쓰지 않습니다.

- 대용량 데이터 파일을 직접 검사해야 하는 경우
- 로컬 브라우저/OS 의존 버그를 재현해야 하는 경우
- Codespaces 네트워크에서 접근이 막힌 외부 서비스를 테스트해야 하는 경우

그 외에는 Codespaces에서 작업합니다.

## Mac mini로 이전

개인 Mac mini에서 이어서 작업하려면 회사 노트북의 프로젝트 폴더를 복사하지 말고 GitHub에서 새로 clone합니다.

자세한 절차는 [docs/MAC_MINI_MIGRATION.md](docs/MAC_MINI_MIGRATION.md)를 봅니다.

Mac mini에서 프로젝트를 내려받은 뒤 아래를 실행하면 기본 개발환경을 자동으로 만듭니다.

```bash
bash scripts/setup_mac.sh
```
