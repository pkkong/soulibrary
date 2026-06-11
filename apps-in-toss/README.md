# Soulib Apps in Toss

Soulib의 Apps in Toss WebView 클라이언트입니다. 기존 production API `https://www.soulib.kr`을 그대로 사용하고, Toss 앱 안에서는 검색, 상세, 내 서재 중심의 가벼운 모바일 경험만 제공합니다.

## App Metadata

- `appName`: `soulib`
- `displayName`: `전자도서관 통합검색`
- API base: `https://www.soulib.kr`
- Icon URL: `https://www.soulib.kr/static/img/app-icon-1024.png`
- Build output: `dist/`

## Commands

```sh
npm install
npm run dev
npm run typecheck
npm run build
```

로컬 API나 프록시를 사용할 때는 `VITE_SOULIB_API_BASE`를 지정합니다.

```sh
VITE_SOULIB_API_BASE=http://localhost:5001 npm run dev
```

## UX Scope

Apps in Toss 전환의 목표는 별도 서비스를 새로 만드는 것이 아니라 기존 Soulib 웹앱의 핵심 흐름을 Toss WebView 안에서 안정적으로 제공하는 것입니다.

- 검색, 상세, 내 서재의 정보 구조와 사용자 흐름은 기존 웹앱을 우선합니다.
- Toss WebView 제약 때문에 필요한 안전영역, 터치 타깃, 화면 높이만 최소 조정합니다.
- 검색 결과 카드에는 책 정보만 보여주고, 제공처 수와 도서관별 상태는 상세 화면에서 보여줍니다.
- 블로그 전체와 오류 신고 메뉴는 앱인토스 하단 메뉴에 넣지 않습니다.
- 서비스 설명은 `이용안내` 단일 화면으로 유지합니다.
- 기존 웹앱과 다른 UX를 만들 때는 변경 사유를 문서에 남깁니다.

## Verification

Codex 환경에는 `npm`/`npx`가 없을 수 있습니다. 그 경우 `node_modules/.bin`의 `tsc`와 `vite`로 typecheck/build를 확인합니다.

일반 Node/npm 환경에서는 아래가 기준입니다.

```sh
npm run typecheck
npm run build
```

기능 확인 범위:

- 홈 화면 렌더링
- 한국어 검색 결과 렌더링
- 상세 화면과 도서관별 상태 표시
- 서재 선택 모달
- 내 서재 저장/조회
