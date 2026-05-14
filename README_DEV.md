# Library Crawler Development Guide

이 저장소의 기준 원본은 GitHub `pkkong/library_crawler`입니다. 로컬 PC는 작업 사본으로만 사용하고, 모바일/다른 컴퓨터/Codespaces에서는 GitHub에서 이어서 작업합니다.

## 기본 원칙

- 코드, 템플릿, 설정, 문서는 GitHub에 커밋합니다.
- 로컬 DB, 크롤링 산출 CSV, 캐시, 로그, 개인 토큰은 GitHub에 올리지 않습니다.
- DB 없는 실시간 검색을 기본 개발 모드로 봅니다.
- DB/PostgreSQL은 과거 데이터 관리나 관리자 작업이 필요할 때만 붙입니다.

## 새 컴퓨터에서 시작

```bash
git clone https://github.com/pkkong/library_crawler.git
cd library_crawler
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/smoke_test.py
python web/app_search.py
```

macOS/Linux/Codespaces:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/smoke_test.py
python web/app_search.py
```

기본 URL:

```text
http://127.0.0.1:5001/
http://127.0.0.1:5001/search
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

## GitHub Codespaces

GitHub에서 `Code > Codespaces > Create codespace`로 열면 `.devcontainer` 설정으로 Python 환경을 만들고 `requirements.txt`를 설치합니다.

Codespaces에서 실행:

```bash
python scripts/smoke_test.py
python web/app_search.py
```

포트 `5001`이 자동 포워딩되면 브라우저나 모바일에서 열어 확인합니다.

## 배포

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

- `data/*.db`, `data/*.sqlite*`
- 로컬 캐시/상태 파일
- 크롤링 결과 CSV 변경분
- `.env`, 토큰, 개인 설정
- 로컬 백업 ZIP

작업 전 확인:

```bash
git status -sb
python scripts/smoke_test.py
```
