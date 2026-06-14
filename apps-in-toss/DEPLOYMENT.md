# Apps in Toss Deployment

Last updated: 2026-06-14

This document separates the repository's deployment records from the live Apps in Toss console state. It does not assert the current console launch state unless the user confirms it in the console.

Official references:

- App registration checklist: https://developers-apps-in-toss.toss.im/prepare/checklist.html
- Console registration flow: https://developers-apps-in-toss.toss.im/prepare/console-workspace.html
- Toss app bundle upload and CLI deploy: https://developers-apps-in-toss.toss.im/development/test/toss.html
- Release review and launch flow: https://developers-apps-in-toss.toss.im/development/deploy.html

## Current Artifacts

- AIT bundle: `apps-in-toss/soulib.ait`
- Console submission checklist: `apps-in-toss/CONSOLE_SUBMISSION.md`
- App logo: `web/static/img/app-icon-600.png`
- Thumbnail: `apps-in-toss/assets/thumbnail-1932x828.png`
- Customer support email: `kongncompany@naver.com`

## Deployment Records

Use these records as separate facts:

- `019eb19c-b150-7583-ba60-0b8f10c50745` is the last deploymentId recorded as uploaded from this workspace.
- `019ec39d-efa6-7959-a3b4-7b49cab568ce` is the latest deploymentId produced by a local `ait build`.
- A local build deploymentId does not mean the console is outdated by itself. The console launch state must be checked in the Apps in Toss console.

## Last Recorded Console Upload

- Uploaded at: 2026-06-10 21:58 KST
- deploymentId: `019eb19c-b150-7583-ba60-0b8f10c50745`
- Test scheme: `intoss-private://soulib?_deploymentId=019eb19c-b150-7583-ba60-0b8f10c50745`
- Upload command mode: one-time `ait deploy --api-key ...`
- Meaning: this is the deploymentId this repository can confirm was uploaded. If the Apps in Toss console shows this deployment as launched, no additional console launch step remains for this recorded upload.

## Prepared Local Build

- Built at: 2026-06-14 KST
- deploymentId from `ait build`: `019ec39d-efa6-7959-a3b4-7b49cab568ce`
- Bundle SHA-256: `32005be0d1e584a8bee63e2f91bb460d1993e0e62c8aa6929d578c827901f90c`
- Meaning: source verified locally. Upload to Apps in Toss console is a separate step because the deployment API key is not stored in the repository.
- Do not treat this local deploymentId as launched unless the console later shows it was uploaded and released.

## Source Control Note

The Apps in Toss changes were intentionally kept separate from the Vercel/public repository cleanup commits because they are a large client-side UX change. They must be verified and committed as their own Apps in Toss release-candidate change.

Root cause of the previous uncommitted state:

- the change touched home, search, detail, shelf storage, styling, metadata, and thumbnail assets;
- public GitHub cleanup and production Vercel migration were separate operational changes;
- the local Codex Node runtime had `node` but not a working `npm`/`npx`, while `ait build` internally calls `npx vite build`.

## Console Entry Summary

- App name: `전자도서관 통합검색`
- appName: `soulib`
- App type: `비게임`
- Subtitle: `서울 공공 전자책을 한 번에 검색`
- Primary category choice: `교육/학습 > 도서/독서`
- Fallback category: `생활 > 문화/도서`
- Search keywords: `전자책`, `도서관`, `서울도서관`, `이북`, `책검색`, `공공도서관`, `교보전자도서관`, `YES24전자도서관`, `무료전자책`, `서울전자책`
- Customer support email: `kongncompany@naver.com`

## Console Launch Status Check

There is no unconditional pending console action in this document. Use the console as the source of truth:

1. Open the Apps in Toss console.
2. Go to the app's release or launch status page.
3. Check whether the console status is already launched/released.
4. Check which deploymentId is selected for the launched release.
5. If the console shows `출시됨` or an equivalent launched state, record that as "user console confirmed launched" with the date. Do not request another review only because this document still contains a local build record.

Interpretation:

- If the console shows launched with deploymentId `019eb19c-b150-7583-ba60-0b8f10c50745`, the recorded upload is already the launched version.
- If the console shows launched with deploymentId `019ec39d-efa6-7959-a3b4-7b49cab568ce`, the locally built version was also uploaded and launched after the recorded upload.
- If the console shows review pending, rejected, draft, or not launched, follow the console's required action for that state.
- If the console does not expose the deploymentId on the status page, use the console's launched status as the user confirmation rule and avoid claiming a specific launched deploymentId.

## When A New Upload Is Needed

Upload a new `.ait` bundle only when one of these is true:

- source, UI, metadata, assets, or release requirements changed after the deployment currently selected in the console;
- the console is launched with an older deployment but the intended release target is the newer local build;
- Toss review requests a revised bundle;
- the uploaded bundle cannot be tested with the private scheme;
- the console has no uploaded deployment available for review or launch.

Do not upload a new bundle only because:

- this document lists a newer local `ait build` deploymentId;
- the console is already launched and there has been no intended source or metadata change since the launched deployment;
- the goal is only to clean up documentation wording.

## Verify Before Upload

```sh
cd /Users/pkkong/Projects/library_crawler

cd apps-in-toss
/Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/.bin/tsc -b tsconfig.json --pretty false
/Users/pkkong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node node_modules/.bin/vite build
cd ..
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
PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH ./node_modules/.bin/ait deploy -m "웹앱 UI 반영, 필터/검색 UX 개선, 고객문의 이메일 반영"
```

Or pass the API key directly without saving a profile:

```sh
cd /Users/pkkong/Projects/library_crawler/apps-in-toss
PATH=/tmp/node-v22.22.3-darwin-arm64/bin:$PATH ./node_modules/.bin/ait deploy --api-key 'APPS_IN_TOSS_API_KEY' -m "웹앱 UI 반영, 필터/검색 UX 개선, 고객문의 이메일 반영"
```

## CLI Profile Note

`~/.ait` is empty on this machine, so there is no saved Apps in Toss CLI profile. Running `ait deploy` currently stops at:

```text
앱인토스 배포 API 키를 입력해주세요
```

The upload was completed by passing the API key directly to `ait deploy`. No API key was saved to the local `~/.ait` profile.
