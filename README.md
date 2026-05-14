# Soulib Library Crawler

이 프로젝트의 기본 작업환경은 GitHub Codespaces입니다.

로컬 컴퓨터에 프로젝트를 내려받는 방식은 예외로 봅니다. 회사 컴퓨터, 집 컴퓨터, 핸드폰은 GitHub/Codex/Codespaces에 접속하는 단말로만 사용합니다.

## 기본 작업 흐름

1. GitHub 저장소에서 `Code > Codespaces > Create codespace`를 엽니다.
2. Codespaces 터미널에서 서버를 실행합니다.

```bash
python web/app_search.py
```

3. 포트 `5001`이 열리면 브라우저에서 화면을 확인합니다.
4. 변경이 끝나면 Codespaces에서 commit/push 합니다.
5. `main`에 반영되면 GitHub Actions가 smoke test를 실행한 뒤 Cloudtype 배포를 트리거합니다.

## 로컬 PC 원칙

- 로컬 PC는 필수 개발환경이 아닙니다.
- 로컬 clone은 긴급 복구나 특수 테스트가 필요할 때만 사용합니다.
- DB, 캐시, 크롤링 산출물, 개인 토큰은 GitHub에 올리지 않습니다.

## 빠른 확인

```bash
python scripts/smoke_test.py
python web/app_search.py
```

자세한 개발 가이드는 [README_DEV.md](README_DEV.md)를 봅니다.
