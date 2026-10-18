# Soulib Production Operations

이 문서는 현재 production 운영 기준입니다. Phase 0 inventory는 Cloudtype 시절 경로와 레거시 분류를 남긴 과거 기준 문서이며, 현재 배포와 운영 판단은 이 문서를 우선합니다.

## 현재 Production

- 운영 URL: `https://www.soulib.kr`
- 기본 Vercel URL: `https://soulib.vercel.app`
- 기준 저장소: GitHub `pkkong/soulibrary`
- production branch: `main`
- 운영 entrypoint: `vercel.json -> index.py -> web/app_search.py`
- 기본 검색: DB 없는 실시간 검색
- 공유 서재 영속 저장: Supabase Postgres `shared_shelves`
- 신고 접수: GitHub Issues

Dockerfile은 로컬/컨테이너 실행 참고용으로 남아 있지만, 현재 자동배포 경로가 아닙니다. Cloudtype 서비스는 해지 대상이므로 rollback 경로로 보지 않습니다.

## 배포 흐름

`main`에 push 또는 merge되면 `.github/workflows/vercel-deploy.yml`이 실행됩니다.

```text
push/merge to main
-> GitHub Actions smoke-test job
-> Vercel production deploy
-> vercel inspect
-> python scripts/live_smoke.py https://www.soulib.kr
```

Vercel 함수 지역은 `vercel.json`의 `regions: ["iad1"]`(미국)로 명시한다. 공유 서재의 Supabase 지역은 아래의 `ap-northeast-2`(서울)를 기준으로 한다.

지역 설정을 바꾼 뒤에는 배포 후 `vercel inspect`에서 실제 function region을 확인한다. 같은 고정 검색어·필터와 비교 가능한 cache 조건으로 변경 전후를 비교하고 표본 수를 기록한다. 전체 성공 수뿐 아니라 기관별 기존 성공의 새 실패와 실패 종류를 확인하며, 공유 서재 create/read도 live smoke로 검증한다. 단일 비교를 p95나 일반적인 성능 개선으로 보고하지 않고 자세한 비교 결과는 ignored artifact에 보존한다. 설정 변경과 실제 배포·지역 검증 완료를 구분한다.

### 선택적 국내 연결 경로의 출시 조건

메인 앱은 `iad1`을 유지한다. 국내 연결이 필요한 기관만 기존 Vercel 프로젝트의 별도 `icn1` preview를 통해 조회하는 relay를 시험한다. 새 프로젝트·유료 서비스·Supabase Edge Function을 만들거나 검색에 DB 의존성을 추가하지 않는다. 아래는 출시 게이트이며, 코드 작성·preview 배포·production 활성화·기관별 복구 확인을 각각 구분한다.

| 설정 | 역할과 기본값 |
|---|---|
| `LIBRARY_RELAY_MODE` | `index.py -> web/app_entrypoint.py`에서 분기한다. `1`인 배포만 `web/library_relay_app.py`를 사용하며, 메인 production에는 설정하지 않아 기본 `web/app_search.py`를 사용한다. |
| `LIBRARY_RELAY_ENABLED` | 메인 앱의 relay 사용 스위치. 기본 OFF이며 `1`일 때만 후보 기관을 선택한다. |
| `LIBRARY_RELAY_CODES` | 실제 검색·상태 조회 검증을 통과한 기관 코드만 지정한다. 코드상 허용 범위는 `seongbuk`, `yeongdeungpo`, `songpa_owned`, `gangseo`다. |
| `LIBRARY_RELAY_URL` | 검증한 고정 HTTPS preview의 base URL. production 도메인 alias를 이 배포로 옮기지 않는다. |
| `LIBRARY_RELAY_SECRET` | 메인과 relay 서버만 공유하는 전용 HMAC secret. 다른 API/DB/deploy credential을 재사용하지 않는다. |

secret은 서버 runtime env로만 주입하고 소스·파일·로그·브라우저·공개 artifact에 남기지 않는다. preview 보호가 있으면 승인된 정상적인 자동화 인증으로 호출할 수 있는지 먼저 확인하며, 인증을 생략하거나 보호 설정을 임의로 해제하지 않는다. HMAC 인증은 preview 접근 인증과 별도로 검증한다.

출시 전에 다음을 확인한다.

1. relay 배포의 mode·실제 `icn1` 지역·고정 URL을 확인하고, 메인 앱과 production 도메인이 기존 `iad1`에 남아 있는지 확인한다.
2. 기관별 실제 검색과 같은 책의 상태 조회를 모두 검증한다. 기존 `icn1` 검색 성공이나 local/mock 통과를 새 relay 검증으로 대신하지 않는다. 성북·영등포가 복구되어도 송파 소장·강서의 실패를 별도로 보고한다.
3. 기존 parser/cache와 기관 식별자를 유지한다. relay를 거치는 기관 작업의 최대 4.5초는 검색의 다중 필드 조회 또는 상태의 detail·list fallback이 공유하며, 기존 검색 fanout 5.8초 예산도 늘리지 않는다. 직접 조회의 기존 timeout은 변경하지 않는다. 실패·시간 초과를 정상 0건으로 바꾸지 않는다. 상세한 인증·응답·cache 검수는 [service_observability.md](service_observability.md)를 따른다.
4. 활성화할 코드만 선택한 뒤 전체 34개 기관의 새 실패를 비교한다. 관악·동작·도봉의 검색과 상태, 공유 서재 create/read, sitemap XML, 기존 CI와 production live smoke를 확인한다.
5. `LIBRARY_RELAY_ENABLED`를 OFF로 바꾸고 재배포하면 기존 직접 조회로 돌아오는지 확인한다. 되돌린 뒤 메인 mode·`iad1`·기존 성공 기관과 공유 서재를 다시 확인한다. 필요하면 이전 메인 deployment로 rollback한다.

브라우저 로그인 만료 시에는 기존 connector·CLI 인증·CI 배포 권한부터 확인한다. 새 relay를 선택하면서 생긴 접근 요건과 기존 운영 배포 장애를 구분하고, 기존 권한으로 가능한 구현·검증은 계속한다. 모든 승인된 경로가 막힌 작업만 부족한 권한과 필요한 사용자 조치를 구체적으로 보고한다.

### 기존 자동배포 인증

자동배포에 필요한 GitHub Actions secrets:

```text
VERCEL_TOKEN
VERCEL_ORG_ID
VERCEL_PROJECT_ID
```

`VERCEL_TOKEN`은 Vercel access token이며, 현재 운영 기준 이름은 `soulib-github-actions-deploy`입니다. 토큰 값은 GitHub Actions secrets에만 두고 문서, 로그, `.env`, `.secrets/`에 남기지 않습니다.

브라우저 콘솔을 열지 않고 GitHub 쪽 설정 상태를 확인할 때는 `gh` CLI를 사용합니다. 아래 명령은 secret 값을 보여주지 않고 이름과 갱신 시각만 보여줍니다.

```bash
gh secret list --repo pkkong/soulibrary
gh variable list --repo pkkong/soulibrary
gh run list --repo pkkong/soulibrary --limit 5
```

secret 값을 교체할 때도 채팅이나 shell history에 값을 남기지 않습니다. `gh secret set <NAME> --repo pkkong/soulibrary`를 실행한 뒤 표준입력으로 넣거나 GitHub UI에서 직접 넣습니다.

## Vercel Runtime Env

Vercel production에는 아래 값이 필요합니다.

```text
PUBLIC_BASE_URL=https://www.soulib.kr
GITHUB_ISSUE_TOKEN=<Issues read/write token>
GITHUB_ISSUE_REPO=pkkong/soulibrary
DATABASE_URL=<Supabase Postgres pooler connection URL>
SHARED_SHELVES_STORAGE=auto
```

주의:

- `DATABASE_URL`은 Supabase transaction pooler URL을 사용합니다.
- Vercel에서는 JSON 파일 fallback으로 공유 서재를 운영하지 않습니다.
- `GITHUB_ISSUE_TOKEN`은 신고 접수와 최근 신고 목록 조회에 필요합니다.
- secret 값은 Vercel/GitHub UI나 CLI에서만 관리하고 Git에 남기지 않습니다.

## DNS와 인증서

Gabia DNS에서 `www.soulib.kr`은 Vercel로 연결합니다.

```text
Type: A
Name: www
Value: 76.76.21.21
```

Vercel 인증서는 자동 갱신됩니다. 인증서가 아직 붙지 않은 경우 아래 순서로 확인합니다.

```bash
dig +short www.soulib.kr
curl -I https://www.soulib.kr
vercel domains inspect www.soulib.kr --scope <scope> --token <token>
vercel certs ls --scope <scope> --token <token>
```

정상 기준:

```text
dig -> 76.76.21.21
curl -> HTTP/2 200
server -> Vercel
```

## Supabase

Supabase는 공유 서재 링크 저장소입니다.

- project name: `soulib`
- region: `ap-northeast-2`
- table: `public.shared_shelves`
- migration: `supabase/migrations/20260610144500_create_shared_shelves.sql`

DB 연결값은 Vercel `DATABASE_URL`에만 둡니다. 로컬에는 필요할 때만 `.env` 또는 `.secrets/`에 두고 커밋하지 않습니다.

## 검증 명령

로컬 변경 검증:

```bash
python scripts/smoke_test.py
git diff --check
```

production 검증:

```bash
python scripts/live_smoke.py https://www.soulib.kr
```

live smoke는 아래를 확인합니다.

- `/`
- `/search`
- `/my-shelf`
- `/robots.txt`
- `/static/css/search.css`
- `/static/js/search.js`
- `/api/live_search`: 실제 도서관 검색 여부, 응답 schema, 전체 실패/부분 응답
- 공유 서재 생성/조회

production을 읽기만 점검할 때는 `python scripts/live_smoke.py https://www.soulib.kr --skip-shared --check-supporting`을 사용한다. 공유 서재 생성은 건너뛰고 신고 페이지와 sitemap XML을 추가 확인한다. 일부 외부 도서관 실패는 degraded warning으로 표시하며, 모든 도서관 실패 후 빈 결과는 실패로 판정한다. 읽기 점검 통과와 새 코드 배포 검증을 구분한다.

검색 변경은 cache hit/miss를 구분하고 운영 검색이 DB 없이 동작하는지 확인한다. 자세한 검수 계약은 [service_observability.md](service_observability.md)를 참고한다.

## 서비스 사용량과 피드백

- GA4 태그 설치, 데이터 수집, 대시보드 접근, 실제 이용 이벤트를 각각 확인한다. 실제 traffic/검색어/페이지 성과 원본은 공개 문서에 기록하지 않는다.
- 현재 검색어·방문자·이용 데이터 수집은 사용자 승인 범위다. 연락처·공유 서재 slug·원문 전체 URL은 제외하며, analytics 오류가 검색/서재/신고 기능을 중단시키지 않게 검증한다.
- GA 내부 트래픽 필터는 상태까지 확인한다. Testing은 실제 제외가 아니다. enhanced measurement와 query redaction 설정을 코드 이벤트 정제와 별도로 검수한다.
- enhanced measurement는 OFF, 정제된 수동 page view와 custom 이벤트를 기준으로 한다. `library_outbound`와 `shelf_save`는 주요 이벤트, `search_term`은 event-scoped 맞춤 측정기준으로 관리하며 배포 후 실제 수집을 확인한다.
- 공유 서재 방문은 `/shelf/shared`의 공통 경로로 측정하고 slug를 제외한다. 공개 블로그·SEO landing 경로는 유지한다. 검수 중 수집 제외는 `SoulibAnalytics.setOptOut(true)`를 사용하며 상세 API와 저장 키는 [service_observability.md](service_observability.md)를 따른다.
- 공개 GitHub 신고는 공개 사실을 폼에 알리고 연락처 필드를 받거나 저장하지 않는다. 성공 이벤트는 실제 접수 성공을 기준으로 한다.
- GSC API 인증과 GA에 연결된 GSC 대시보드 조회는 별도 경로다. OAuth refresh 실패는 사용자 재인증 또는 서비스 계정 권한 복구가 필요하다.

## SEO 자동 개선 운영

SEO 자동화는 자동 발행 장치가 아니라 측정과 개선 후보를 안정적으로 만드는 운영 루프입니다.

기본 루프:

```text
Search Console/production 측정
-> 진단
-> 저위험 자동 수정 후보
-> 콘텐츠/UX 개선안
-> QA
-> PR 또는 초안
-> 배포 후 production 검증
```

권한 경계:

- 기본 권한은 GitHub issue, queue, 자동 점검 결과와 사람 검토용 초안 생성까지입니다.
- 글 본문, 랜딩 문구, 이미지, 사용자-facing UI는 자동 발행하지 않습니다.
- 저위험 자동 수정 후보는 queue로 정리하고, 실제 PR은 QA/Release Worker 검증과 메인 리뷰가 가능한 경우에만 별도로 만듭니다.
- technical metadata나 문서 정리처럼 영향이 작은 변경도 `python scripts/smoke_test.py`, `git diff --check`, production live smoke를 통과해야 합니다.

역할 분리:

- Growth Analyst: Search Console과 production 지표를 읽고 하락/기회/우선순위를 진단합니다.
- Technical SEO Worker: robots, sitemap, metadata, canonical, structured data 같은 기술 SEO 후보를 PR로 만듭니다.
- Content Writer: 신규 글이나 랜딩 문구 초안을 작성하되 직접 발행하지 않습니다.
- Editor/Fact Checker: 콘텐츠 사실관계, Soulib 검색 연결, 표현 품질, 이미지 적합성을 검수하고 반려할 수 있습니다.
- QA/Release Worker: smoke test, live smoke, Search Console 설정 영향, 배포 후 검증을 확인합니다.

Search Console secret 관리:

- credential과 token JSON은 `.secrets/`, GitHub Actions secrets, 운영 secret에만 보관합니다.
- 서비스 계정 key, OAuth client JSON, OAuth token 내용은 로그, 문서, PR 본문, issue 댓글에 출력하지 않습니다.
- 인증 문제를 보고할 때는 파일 경로, secret 이름, 권한 상태만 남기고 토큰 원문이나 JSON 본문은 남기지 않습니다.
- GitHub Actions에서는 repository variable `GSC_SITE_URL`, `PRODUCTION_BASE_URL`과 repository secret `GSC_SERVICE_ACCOUNT_JSON` 또는 `GSC_OAUTH_TOKEN_JSON`을 사용합니다.
- Search Console 검색어와 페이지 성과는 운영 데이터입니다. GitHub issue, PR 본문, Actions artifact에는 원시 query/page/CTR/position을 그대로 올리지 않고 요약된 공개용 문구만 남깁니다. 원본 JSON은 job 내부 또는 로컬 파일로만 확인합니다.
- Search Console 스크립트는 `--auth-failure-mode dry-run|fail`을 사용합니다. 기본값은 `dry-run`이며, 인증 만료나 권한 실패 시 빈 지표 JSON을 출력하고 exit 0으로 끝내서 `SEO Growth`가 빨간 실패로 쌓이지 않게 합니다.
- `dry-run` fallback은 측정 장애로 표시하고 warning/step summary를 확인합니다. workflow 성공과 실지표 수집 성공을 구분하며, 빈 fallback을 이용자 0명 또는 개선 후보 없음으로 해석하지 않습니다.
- 실제 지표 자동화를 복구하려면 `GSC_SERVICE_ACCOUNT_JSON`을 우선 권장합니다. `GSC_OAUTH_TOKEN_JSON`은 refresh가 다시 실패할 수 있으므로 서비스 계정 전환이 어려울 때의 보조 경로로 봅니다.
- 엄격한 복구 검증이나 인증 상태 감시에서 실패를 바로 드러내야 할 때만 `--auth-failure-mode fail`을 명시합니다.

OAuth token을 갱신할 때:

```bash
python scripts/search_console_report.py --authorize
gh secret set GSC_OAUTH_TOKEN_JSON --repo pkkong/soulibrary < .secrets/search-console-oauth-token.json
```

운영 주기:

- 매일 audit: Search Console 지표, 색인/크롤링 이상, 주요 landing page 상태, production smoke 신호를 확인합니다.
- 주간 Growth Queue issue: 발견한 기회와 위험을 우선순위, 예상 영향, 필요한 역할로 묶어 정리합니다.
- 주간 저위험 수정 후보: technical SEO 수정이나 문서화 가능한 개선안을 queue로 정리합니다. 자동화가 직접 PR을 만들지는 않고, 메인 리뷰 후 필요한 경우 별도 PR로 진행합니다.

## Secret Rotation

Secret hygiene check:

```bash
.venv/bin/python scripts/check_secret_hygiene.py --inventory
```

이 명령은 로컬 `.env`, `.secrets`, Vercel/Supabase link metadata의 키 이름과 파일명만 보여주고 값은 출력하지 않습니다. CI에서는 `python scripts/check_secret_hygiene.py`가 tracked 파일에 private key, GitHub token, JWT, literal DB URL, 공공 API key 기본값이 들어갔는지 확인합니다.

2026-06-21 점검에서 과거 `web/config.py`에 공공 API key 기본값이 tracked code와 Git history에 남아 있던 것을 제거했습니다. 현재 tracked 파일에는 같은 값이 남아 있지 않지만, 해당 키는 발급처에서 재발급 또는 폐기하고 새 값은 로컬 `.env`나 운영 secret에만 둡니다.

Vercel deploy token을 교체할 때:

1. Vercel에서 새 access token을 만든다.
2. GitHub Actions secret `VERCEL_TOKEN`을 새 값으로 교체한다.
3. `main`에 빈 커밋이나 문서 커밋을 push해 자동배포를 확인한다.
4. 새 배포가 성공하면 기존 token을 revoke한다.

GitHub Issues token을 교체할 때:

1. 새 token을 만든다.
2. Vercel production env `GITHUB_ISSUE_TOKEN`을 교체한다.
3. Vercel production deploy를 실행한다.
4. `/reports` 또는 smoke 범위에서 신고 기능을 확인한다.
5. 기존 token을 revoke한다.

Supabase DB password를 교체할 때:

1. Supabase에서 DB password를 reset한다.
2. 새 pooler connection URL을 Vercel `DATABASE_URL`에 반영한다.
3. Vercel production deploy를 실행한다.
4. `python scripts/live_smoke.py https://www.soulib.kr`로 공유 서재 create/read를 확인한다.

## Rollback

Cloudtype은 해지 대상이며 현재 rollback 경로가 아닙니다. 장애 대응은 Vercel 안에서 처리하는 것을 기본으로 합니다.

- Vercel 이전 deployment로 rollback할지
- Vercel env 수정 후 재배포할지
- 공유 서재 저장소를 Supabase에 유지할지

대부분의 장애는 DNS 변경보다 Vercel 이전 deployment rollback 또는 env 수정 후 재배포가 더 작고 빠릅니다. Cloudtype으로 되돌리는 계획은 기본 운영 절차가 아닙니다.
