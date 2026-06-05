# Apps in Toss Deployment

Last updated: 2026-06-05

This app is ready to upload once an Apps in Toss deployment API key is available.

Official references:

- App registration checklist: https://developers-apps-in-toss.toss.im/prepare/checklist.html
- Console registration flow: https://developers-apps-in-toss.toss.im/prepare/console-workspace.html
- Toss app bundle upload and CLI deploy: https://developers-apps-in-toss.toss.im/development/test/toss.html

## Current Artifacts

- AIT bundle: `apps-in-toss/soulib.ait`
- Console submission checklist: `apps-in-toss/CONSOLE_SUBMISSION.md`
- App logo: `web/static/img/app-icon-600.png`
- Thumbnail: `apps-in-toss/assets/thumbnail-1932x828.png`
- Customer support email: `kongncompany@naver.com`

## Console Entry Summary

- App name: `서울 전자책 찾기`
- appName: `soulib`
- App type: `비게임`
- Subtitle: `서울 공공 전자책을 한 번에 검색`
- Primary category choice: `교육/학습 > 도서/독서`
- Fallback category: `생활 > 문화/도서`
- Search keywords: `전자책`, `도서관`, `서울도서관`, `이북`, `책검색`, `공공도서관`, `교보전자도서관`, `YES24전자도서관`, `무료전자책`, `서울전자책`
- Customer support email: `kongncompany@naver.com`

## Verify Before Upload

```sh
cd /Users/pkkong/Projects/library_crawler

PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH npm --prefix apps-in-toss run typecheck
PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH npm --prefix apps-in-toss run build
.venv/bin/python scripts/smoke_test.py
git diff --check
```

## Upload With API Key

The Apps in Toss CLI requires a deployment API key issued from the Apps in Toss console.

Register the key once:

```sh
cd /Users/pkkong/Projects/library_crawler/apps-in-toss
PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH ./node_modules/.bin/ait token add --api-key 'APPS_IN_TOSS_API_KEY'
```

Upload the current `.ait` bundle:

```sh
cd /Users/pkkong/Projects/library_crawler/apps-in-toss
PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH ./node_modules/.bin/ait deploy --scheme-only -m "웹앱 UI 반영, 필터/검색 UX 개선, 고객문의 이메일 반영"
```

Or pass the API key directly without saving a profile:

```sh
cd /Users/pkkong/Projects/library_crawler/apps-in-toss
PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH ./node_modules/.bin/ait deploy --api-key 'APPS_IN_TOSS_API_KEY' --scheme-only -m "웹앱 UI 반영, 필터/검색 UX 개선, 고객문의 이메일 반영"
```

## Current Blocker

`~/.ait` is empty on this machine, so there is no saved Apps in Toss CLI profile. Running `ait deploy` currently stops at:

```text
앱인토스 배포 API 키를 입력해주세요
```

After the API key is available, no code change is required before upload.
