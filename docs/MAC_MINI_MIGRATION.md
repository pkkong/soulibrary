# Mac mini 이전 가이드

이 프로젝트의 기준 원본은 회사 노트북 폴더가 아니라 GitHub 저장소입니다.

```text
https://github.com/pkkong/soulibrary
```

회사 노트북에서 파일을 복사하지 말고, Mac mini에서 GitHub 저장소를 새로 내려받아 시작하세요.

## 1. 회사 노트북에서 확인할 것

현재 상태는 GitHub에서 확인합니다.

```text
branch: main
remote: https://github.com/pkkong/soulibrary.git
status: main == origin/main
```

즉, Mac mini는 GitHub에서 `main`을 받으면 됩니다.

## 2. Mac mini에 필요한 것

Mac mini에는 아래만 있으면 됩니다.

- Git
- Python 3.11 이상
- Codex 앱 또는 터미널
- GitHub 로그인

터미널에서 Git이 없다고 나오면 먼저 아래를 실행합니다.

```bash
xcode-select --install
```

Python은 아래처럼 확인합니다.

```bash
python3 --version
```

## 3. 프로젝트 내려받기

Mac mini 터미널에서 실행합니다.

```bash
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/pkkong/soulibrary.git
cd soulibrary
```

## 4. 자동 세팅

프로젝트 폴더에서 아래를 실행합니다.

```bash
bash scripts/setup_mac.sh
```

이 스크립트가 하는 일:

- Python 가상환경 `.venv` 생성
- `requirements.txt` 설치
- 로컬 개발용 `.env` 생성
- `python scripts/smoke_test.py` 실행

## 5. 로컬 서버 실행

세팅이 끝나면 아래를 실행합니다.

```bash
bash scripts/run_mac_local.sh
```

브라우저에서 엽니다.

```text
http://127.0.0.1:5001
```

## 6. 비밀값은 복사하지 않습니다

아래 값들은 회사 노트북 파일에서 복사하지 않습니다.

- GitHub 토큰
- Vercel token
- DB 비밀번호
- `.env`
- 로컬 DB, CSV, JSON 캐시

운영 배포에 필요한 값은 GitHub Actions secrets, Vercel production env, Supabase에 이미 있어야 합니다.
Mac mini 로컬 테스트는 DB 없이도 가능합니다.

로컬에서 오류 신고와 블로그 댓글까지 직접 테스트하려면 Mac mini의 `.env`에만 아래 값을 따로 넣습니다.

```text
GITHUB_ISSUE_TOKEN=
GITHUB_ISSUE_REPO=pkkong/soulibrary
```

## 7. 회사 노트북 정리 기준

Mac mini에서 아래 두 가지가 끝난 뒤 회사 노트북 폴더를 정리하세요.

```bash
python scripts/smoke_test.py
bash scripts/run_mac_local.sh
```

브라우저에서 `http://127.0.0.1:5001` 접속까지 확인되면 회사 노트북의 기존 프로젝트 폴더는 백업 후 삭제해도 됩니다.

삭제 전에 마지막으로 회사 노트북에서 확인합니다.

```bash
git status -sb
```

`main...origin/main`만 보이고 변경 파일이 없으면 GitHub와 동기화된 상태입니다.
