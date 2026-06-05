# Apps in Toss Console Submission

Last updated: 2026-06-05

## App Identity

- App name: 서울 전자책 찾기
- appName: soulib
- App type: 비게임
- Brand display name: 서울 전자책 찾기
- Brand primary color: `#3182F6`
- Existing service operation: keep `https://www.soulib.kr` running as-is. Apps in Toss is a separate WebView client that uses the same live search/report APIs.

## Basic Info

- Subtitle: 서울 공공 전자책을 한 번에 검색
- Detail description:

```text
서울 전자책 찾기는 책 제목이나 저자명으로 서울 공공 전자도서관의 전자책 제공 현황을 빠르게 확인하는 서비스입니다.
사용자는 앱을 열고 검색어를 입력한 뒤, 교보문고 전자도서관, YES24 전자도서관, 공공 전자책 서비스 등에서 제공되는 도서와 도서관 수를 한 화면에서 확인할 수 있습니다.
관심 있는 책은 내 서재에 담아 다시 볼 수 있고, 검색 결과나 화면에 문제가 있으면 앱 안에서 바로 신고할 수 있습니다.
```

- Usage age: 만 19세 이상
- Login/payment: 없음
- Customer support email: TODO - 실제 수신 가능한 고객문의 이메일 입력 필요
- Customer support phone: 없음
- Customer support chat URL: 없음

## Category And Exposure

- Primary category choice: 교육/학습 > 도서/독서
- Fallback if the exact category does not exist: 생활 > 문화/도서
- Search keywords:
  - 전자책
  - 도서관
  - 서울도서관
  - 이북
  - 책검색
  - 공공도서관
  - 교보전자도서관
  - YES24전자도서관
  - 무료전자책
  - 서울전자책

## Assets

- App logo upload file: `web/static/img/app-icon-600.png`
- App logo local copy for thumbnail/source work: `apps-in-toss/assets/app-logo-600.png`
- App logo public URL for `granite.config.ts`: `https://www.soulib.kr/static/img/app-icon-600.png`
- Thumbnail upload file: `apps-in-toss/assets/thumbnail-1932x828.png`
- Thumbnail source file: `apps-in-toss/assets/thumbnail-1932x828.html`
- Optional screenshot recommendation:
  - Search screen: 636 x 1048 PNG
  - Result screen: 636 x 1048 PNG
  - Detail screen: 636 x 1048 PNG

## In-App Function

- Korean name: 전자책 찾기
- English name: Find ebooks
- Feature path: `/search`
- Feature URL: `intoss://soulib/search`

If the console rejects `/search` because the current WebView app is single-screen, use `/` and keep the function name as `전자책 찾기`.

## Release Bundle

- AIT bundle: `apps-in-toss/soulib.ait`
- Build command:

```sh
PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH npm run build
```

## Privacy Notes

- No Toss Login.
- No payment.
- No user profile collection in the Apps in Toss client.
- The report form sends category, message, and current page URL to the existing Soulib report API.

## Remaining Required Input

Only one value cannot be decided safely in code: the customer support email. Use a real monitored address before submission.
