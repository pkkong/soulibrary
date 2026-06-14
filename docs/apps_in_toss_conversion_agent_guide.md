# Soulib Apps in Toss 작업 가이드

이 문서는 Soulib의 Apps in Toss 클라이언트를 이어서 작업할 때 확인할 기준 문서입니다.

## 현재 구조

- 기존 웹서비스: `https://www.soulib.kr`
- Apps in Toss client: `apps-in-toss/`
- API base: `https://www.soulib.kr`
- appName: `soulib`
- displayName: `전자도서관 통합검색`
- 기능 범위: 홈, 검색, 상세, 내 서재

Apps in Toss는 기존 웹서비스를 대체하지 않습니다. Toss 앱 안에서 쓰는 별도 WebView 클라이언트이며, 같은 production API를 사용합니다.

## 이번 미커밋 원인

앱인토스 변경분이 오래 남아 있던 근본 원인은 아래입니다.

1. 변경 범위가 컸습니다.
   - 홈/검색/상세/서재 UI가 크게 바뀌었습니다.
   - 단일 서재에서 여러 서재 관리 구조로 바뀌었습니다.
   - 상세 화면에서 도서관별 상태 조회를 더 직접적으로 호출합니다.
2. 공개 GitHub 정리와 Vercel 이전 커밋에 섞으면 위험했습니다.
   - production 웹서비스 배포와 앱인토스 미니앱 변경은 배포 표면이 다릅니다.
   - 그래서 public repo 정리 커밋에서는 의도적으로 제외했습니다.
3. 로컬 Codex 환경의 Node 도구가 불완전했습니다.
   - Codex bundled Node에는 `node`만 있고 `npm`/`npx`가 없습니다.
   - `/tmp/node-v22.22.3-darwin-arm64/bin/npm` symlink는 있으나 target이 없어 실행되지 않습니다.
   - `ait build`는 내부에서 `npx vite build`를 호출하므로 그대로는 실패합니다.

결론: 작업을 버린 것이 아니라, 충분히 검증하지 못한 큰 변경을 다른 운영 커밋에 섞지 않으려고 보류한 상태였습니다.

## 현재 검증 결과

2026-06-14 기준 아래 검증을 통과했습니다.

```bash
/Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/.bin/tsc -b tsconfig.json --pretty false
/Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/.bin/vite build
```

`ait build`는 임시 `npx` shim을 사용해 통과했습니다.

```text
deploymentId: 019ec39d-efa6-7959-a3b4-7b49cab568ce
bundle: apps-in-toss/soulib.ait
sha256: 32005be0d1e584a8bee63e2f91bb460d1993e0e62c8aa6929d578c827901f90c
```

브라우저 검증:

- 모바일 390x844 기준 홈 화면 렌더링 확인
- `파이썬` 검색 결과 확인
- 첫 검색 결과 상세 화면 확인
- 서재 선택 sheet 확인
- 내 서재 저장/조회 확인

## 검증 명령

일반 Node/npm 환경:

```bash
cd apps-in-toss
npm run typecheck
npm run build:web
npm run build
```

현재 Codex 로컬 환경:

```bash
cd apps-in-toss
NODE=/Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node
$NODE node_modules/.bin/tsc -b tsconfig.json --pretty false
$NODE node_modules/.bin/vite build
```

`ait build`까지 확인해야 하는데 `npx`가 없으면 임시 shim을 사용합니다.

```bash
tmpbin=/tmp/soulib-npx-shim
mkdir -p "$tmpbin"
cat > "$tmpbin/npx" <<'SH'
#!/bin/sh
cmd="$1"
shift
case "$cmd" in
  vite)
    exec /Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node ./node_modules/.bin/vite "$@"
    ;;
  *)
    echo "npx shim only supports vite, got: $cmd" >&2
    exit 127
    ;;
esac
SH
chmod +x "$tmpbin/npx"
PATH="$tmpbin:/Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH" \
  /Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node ./node_modules/.bin/ait build
```

## 업로드 기준

소스 커밋 후 Apps in Toss 콘솔 업로드는 별도 단계입니다.

업로드 전 확인:

- `apps-in-toss/CONSOLE_SUBMISSION.md`
- `apps-in-toss/DEPLOYMENT.md`
- `apps-in-toss/assets/thumbnail-1932x828.png`
- `web/static/img/app-icon-600.png`
- `apps-in-toss/soulib.ait`

API key가 있을 때:

```bash
cd apps-in-toss
./node_modules/.bin/ait deploy --api-key 'APPS_IN_TOSS_API_KEY' -m "전자도서관 통합검색 앱 UX 정리"
```

API key 값은 문서, 로그, Git에 남기지 않습니다.

## 유지할 UX 원칙

- 기존 Soulib 웹서비스의 검색, 상세, 내 서재 흐름을 보존합니다.
- Apps in Toss에는 블로그와 오류 신고를 하단 메뉴로 넣지 않습니다.
- 검색 결과 카드에는 책 정보 중심으로 보여주고, 도서관별 상태는 상세 화면에서 확인합니다.
- 내 서재는 Toss 앱 안 로컬 저장소 기반입니다.
- Toss Login, 결제, 개인정보 수집은 사용하지 않습니다.
