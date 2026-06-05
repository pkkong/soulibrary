# Apps in Toss WebView

Soulib Apps in Toss 전용 WebView 프론트엔드입니다.

- `appName`: `soulib`
- `displayName`: `서울 전자책 찾기`
- 기본 API base: `https://www.soulib.kr`
- 기본 icon URL: `https://www.soulib.kr/static/img/app-icon-1024.png`

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
