# 서비스 관측성과 검수

이 문서는 다면 서비스 검토, 사용량 분석, 피드백과 레거시 삭제의 검수 계약이다. 팀 역할과 위임은 [AGENTS.md](../AGENTS.md), 운영 경로는 [production_operations.md](production_operations.md)를 따른다. 실제 사용자 수와 운영 원시 지표는 이 공개 문서에 넣지 않는다.

## 측정 범위

- 현재 사용자 승인 범위에 따라 검색어, 방문자, 서비스 이용 데이터를 수집한다.
- 연락처, 공유 서재 slug, 원문 전체 URL 등 분석에 불필요한 값은 보내지 않는다. 페이지 분류와 정제된 경로를 사용하고 referrer와 동적 페이지 제목도 검수한다.
- production canonical domain에서 수집하고 로컬·preview·admin·ops 방문과 검수 트래픽의 혼입을 확인한다. 분석 전송 실패가 제품 기능을 막으면 안 된다.
- 구현은 `web/static/js/analytics.js`의 `SoulibAnalytics`를 사용한다. 정제된 수동 `page_view`와 허용된 이용 이벤트를 보내고 GA 기본 세션·참여 지표를 유지한다. 웹 stream의 enhanced measurement는 OFF로 유지하여 자동 search/outbound/form 이벤트의 중복·원문 전송을 방지한다.
- 공유 서재 방문은 `page_type=shared_shelf`, page URL과 내부 referrer의 경로 `/shelf/shared`로 집계한다. 실제 slug는 보내지 않는다. 공개 블로그와 SEO landing 경로는 보존하고 query string·fragment는 제거한다.
- 수집 승인과 공개는 별개다. 실제 traffic 숫자, 개별 query, 페이지별 성과, account/property 식별자, 자세한 감사 보고서는 ignored 로컬 artifact 또는 승인된 분석 저장소에서만 다룬다.
- 공개 JSON·Markdown·`--public-summary` 표준 출력은 같은 명시적 allowlist를 사용하고 private 원본은 보존한다. 검색어에서 파생한 id·title, unknown fields, encoded query와 traffic metric bucket의 간접 누출도 fixture 회귀로 검사한다.

## 사용량을 확인하는 절차

1. 태그/측정 ID 설치와 현재 production 응답을 확인한다. 설치만으로 수집 성공을 보고하지 않는다.
2. 승인된 대시보드에서 실제 속성·기간·수집 상태를 확인한다. 접근 권한이 없으면 설치 여부와 데이터 접근 불가를 구분한다.
3. 웹 GA4 활성 사용자는 참여 세션이 있거나 `first_visit` 또는 `engagement_time_msec` 신호가 수집된 사용자다. 정확한 실제 사람 수나 회원 수로 부르지 않는다. 기간, 시간대, 이전 동기간 비교, 내부 방문·QA·bot 혼입 가능성을 적는다. [Google 공식 사용자 지표 정의](https://support.google.com/analytics/answer/12253918?hl=en).
4. 방문/세션/조회수와 검색 성공·도서관 이동·서재 저장을 함께 확인한다. 주요 이벤트 0은 측정 설정 미비인지 실제 이용 없음인지 확인한다.
5. 내부 트래픽 필터의 Testing은 실제 제외가 아니다. enhanced measurement의 자동 search/outbound/form 이벤트와 query redaction은 manual 이벤트 검수와 별도로 확인한다.
6. 확인일과 최근 정상 수집일, 접근 불가·미검증 항목을 남긴다. 코드 검증과 외부 GA 설정 변경 여부를 분리한다.
7. 실제 이벤트 이름과 횟수 확인, 맞춤 정의 등록, 맞춤항목 값의 처리 완료를 구분한다. 신규 배포·등록 후 미완성 기간의 0관측을 전송 실패로 단정하지 않고, 조회 기간·보고 시간대·집계 시각을 기록한다. 원문과 수집 숫자는 ignored 보고서에만 남긴다.

주간 검토에서는 총 유입, 검색을 수행한 방문자, 완전/부분/실패 검색, 상세 진입, 도서관 이동, 서재 저장, 재방문 추세를 본다. 작은 표본은 비율만 강조하지 않고 사건 수와 기간을 함께 기록한다.

## 이용 이벤트 계약

아래는 `SoulibAnalytics.track(name, params)`의 구현 계약이다. 검색어는 승인된 검색 이벤트의 `search_term`으로 수집하며 앞뒤 공백 제거 후 최대 200자로 제한한다. 전송 여부는 production 조건과 opt-out을 함께 확인한다.

| 이벤트 | 측정 시점 | 확인할 데이터 |
|---|---|---|
| `search_start` | 실제 검색 요청 시작 | `search_term`, `field`, `provider_count`, `library_count` |
| `search_result` | 검색 응답 처리 완료 | 위 필드와 `result_count`, `duration_ms`, `partial`, `failed_library_count` |
| `search_error` | 검색 요청 실패 | 검색 필드와 `duration_ms`, 허용된 `error_type` |
| `detail_open` | 실제 상세 진입 | 정제된 페이지 필드 |
| `library_outbound` | 도서관 이용 링크 선택 | `provider`: 교보/YES24/기타 |
| `shelf_save` | 실제 서재 저장 성공 | `list_count` |
| `report_success` | 실제 신고 저장 성공 | `success=true` |

- 새 검색/재시도/상세 이동의 이벤트 중복을 확인한다. API 호출 수와 실제 사용자 행동 수를 구분한다.
- `report_success`는 실제 생성된 신고를 기준으로 한다. `?saved=1`, honeypot 또는 실패 응답은 성공 이벤트로 세지 않는다.
- 검색어 외 신고 본문·연락처·공유 URL은 이벤트 매개변수에 추가하지 않는다. 임의의 DOM text/전체 URL을 자동 전송하지 않는다.
- GA 주요 이벤트 등록과 내부 필터 활성화는 외부 설정이다. 코드 구현 완료를 외부 설정 완료로 보고하지 않는다.
- GA 주요 이벤트는 `library_outbound`, `shelf_save`를 사용한다. `search_term`은 event-scoped 맞춤 측정기준이다. 추가 `partial` 측정기준과 `result_count`/`duration_ms` 측정항목은 관리자 등록 완료 여부와 배포 후 실제 수집을 별도로 검증한다.

### 검수용 opt-out

브라우저 콘솔에서 `SoulibAnalytics.setOptOut(true)`를 실행하면 현재 브라우저의 수집을 중단한다. localStorage 키는 `soulib.analytics.optOut`, 값은 `1`이다. 저장소 접근이 차단된 경우에도 현재 페이지에서는 메모리 opt-out을 적용한다. 다시 수집하려면 `SoulibAnalytics.setOptOut(false)`를 실행한다. `SoulibAnalytics.isEnabled()`로 현재 조건을 확인한다.

검수 때 opt-out 상태와 production 조건을 기록하고, `node scripts/frontend_regression_test.cjs`로 검색어 허용·URL/referrer 정제·공유 서재 slug 제외·opt-out의 이벤트 미전송을 확인한다. fake gtag 검증 통과와 production GA의 실수집 확인을 구분한다.

## Search Console 측정 상태

- GSC는 Google 검색 노출과 클릭이며 전체 방문자 지표가 아니다. GA4와 GSC 값을 서로 바꿔 쓰지 않는다.
- query dimension 보고서에는 익명 query가 빠질 수 있으므로 site/landing 총계와 query 합계를 구분한다. [Google 공식 설명](https://developers.google.com/search/blog/2022/10/performance-data-deep-dive).
- OAuth refresh 실패 또는 서비스 계정 권한 부족은 측정 장애다. API 인증 복구와 GA에 연결된 GSC 대시보드 조회는 별도 경로로 확인한다.
- `dry_run`/`dry_run_source`와 warning/step summary를 확인한다. exit 0, workflow 성공, 빈 opportunities만으로 정상 측정이나 개선 기회 없음을 보고하지 않는다.
- 인증 장애 동안 원시 지표 기반 queue/초안은 건너뛴다. 엄격한 복구 검증은 `--auth-failure-mode fail`로 실행한다.
- 재인증은 사용자의 Google 계정 동의 또는 서비스 계정 property 권한이 필요하다. credential 원문은 출력하지 않는다.

## 실시간 검색과 화면 검수

- `vercel.json -> index.py -> web/app_search.py`와 DB 없는 실시간 검색을 기준으로 한다. 공유 서재의 Postgres 필요성과 검색의 DB 의존성을 혼동하지 않는다.
- cache miss와 hit, 같은 검색 동시 요청, connector 예외·total timeout·library timeout, 결과 item/detail cache 수명과 크기 제한을 점검한다.
- 필터·넓은 검색의 scope 제한, 상세 추가 조회 중, 실제 timeout/provider error를 원인별로 구분한다. 불완전한 응답을 완전한 보유 현황으로 표시하지 않되 범위 제한을 도서관 실패로 설명하지 않는다. 부분 0건과 전체 조회 실패는 완전한 검색 완료 0건과 구분한다.
- 로딩 경과 시간이나 `partial`/`counts_partial` 하나만으로 실패 문구를 만들지 않는다. 실제 응답에서 확인한 실패 범위·개수만 안내하고 정상 scope 제한·조회 중·실제 실패의 표시 조건을 회귀로 검증한다.
- 응답 시간은 endpoint, 조건, cache 상태, 측정 환경·표본 수를 기록한다. 단일 샘플을 SLA나 p95로 일반화하지 않는다.
- `python scripts/smoke_test.py`, `git diff --check`, 실제 `/api/live_search` live smoke를 수행한다. mock 응답 검증과 외부 도서관 연결 검증 결과를 구분한다.
- [UX_UI_Guide.md](UX_UI_Guide.md)에 따라 초기·완료 0건·부분 결과·전체 실패·재시도와 360px/430px/desktop 화면, dialog 이름·Tab 순환·Escape·포커스 복귀를 확인한다.
- 문구 회귀는 정상 검색·필터·넓은 검색·상세 추가 조회 전후에 실패 안내가 잘못 나오지 않는지와 실제 실패가 빠지지 않는지를 함께 확인한다. 실패 안내는 검색 한곳·상세 소장 도서관 한곳에 두고 banner/타이머 중복과 내부 구현 용어를 검수한다.

### 상세·상태 조회의 시간 예산과 cache 계약

- 내부 `live_search(..., deadline=...)`는 절대 monotonic 마감 시각을 받는다. `deadline=None`의 일반 검색은 기존 `LIVE_SEARCH_TOTAL_TIMEOUT`·query cache·single-flight를 유지한다. 짧은 예산 호출자의 대기 종료가 일반 검색 flight를 취소하거나 일반 요청에 짧은 예산을 물려주면 안 된다.
- `/api/live_book_detail`과 `/api/live_book_summary`의 제목 후보들은 `LIVE_DETAIL_TOTAL_TIMEOUT`(기본 8초)의 deadline을 공유한다. 예산이 끝나면 다음 후보를 시작하지 않고, 제목/저자가 호환되며 보유처가 있는 기존 fallback은 `counts_partial=true`로 보존한다. 제목이 같아도 다른 저자의 fallback은 거절한다.
- 조회 실패·예산 소진으로 usable 후보/fallback이 없으면 502, 정상적으로 끝난 조회에서 책이 없으면 404를 반환한다. 실패한 빈 조회를 정상 0건으로 표시하지 않는다.
- deadline 자체로 제한된 partial 검색 결과는 일반 query cache에 쓰지 않는다. 일반 검색의 결과 있는 partial cache는 짧은 TTL을 유지한다. 완전한 결과의 cache 재사용과 일반 flight의 독립성을 회귀로 확인한다.
- 상태 API 8개는 `STATUS_CACHE_SIZE`(기본 1024)와 기존 `KYOBO_STATUS_TTL`(기본 120초)을 사용하는 TTLMemoryCache를 공유한다. 만료·상한 eviction·deep copy·`clear()`와 성공 응답 재사용을 확인하고, 실패 상태는 cache하지 않는다.
- 도봉 상태 fallback은 `DOBONG_STATUS_TOTAL_TIMEOUT`(기본 12초)의 monotonic 예산을 공유한다. 각 HTTP 시도의 timeout은 남은 예산과 `DOBONG_STATUS_ATTEMPT_TIMEOUT`(기본 4.5초) 중 작은 값이다. 기존 후보 순서·product/category 매개변수와 status schema를 유지한다.
- Requests timeout은 socket에 데이터가 오지 않는 시간을 제한하므로 HTTP 다운로드 전체의 hard wall이 아니다. 이미 실행 중인 thread/HTTP 작업은 마감 뒤에도 남을 수 있다. 동작 보장과 남은 한계를 구분하고 실제 경과 시간을 별도로 측정한다. [Requests 공식 timeout 설명](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts).

관련 smoke 회귀는 일반/예산 검색 분리, 공유 flight follower timeout, partial cache 비오염, 상세 후보 공통 deadline·동일 제목 다른 저자 거절·usable partial fallback·502/404 구분, 도봉 남은 timeout 감소·후보 순서·실패 재시도, 상태 cache TTL/상한/복사/clear를 포함한다. mock clock 검증 통과와 실제 공급사 HTTP 경과 시간 검증을 구분한다.

### 선택적 relay의 연결·상태 검수

- 배포·활성화·rollback 조건은 [production_operations.md](production_operations.md)의 선택적 국내 연결 경로를 따른다. relay는 고정 기관의 공개 HTML을 운반하고 메인 앱이 기존 parser/cache를 사용한다. 메인 `iad1`과 relay `icn1`의 실제 지역, 코드별 사용 경로와 cache hit/miss를 증거에 남긴다.
- 기본 OFF에서 시작하고 네 기관 allowlist 안에서도 실제 검색과 같은 책의 상태 조회가 모두 통과한 코드만 활성화한다. HTTP 200·문서 비어 있지 않음만으로 검색/상태 성공을 판정하지 않는다. 성북·영등포의 통과와 송파 소장·강서의 미복구를 따로 기록한다.
- HMAC 누락·불일치·만료, relay 자기 호출, 임의 URL/기관/operation/매개변수, redirect, 비정상 content type·초과 body, 외부 실패·예산 소진을 거절하는지 검증한다. 전용 secret과 요청 원문·검색어·인증 header를 로그나 공개 artifact에 남기지 않는다. preview에는 승인된 정상적인 자동화 인증을 사용하고 인증을 생략하거나 보호 설정을 임의로 해제하지 않는다. 보호된 preview 접근 성공과 relay HMAC 검증 성공을 구분한다.
- relay를 거치는 기관 작업의 최대 4.5초는 검색의 다중 필드 조회 또는 상태의 detail·list fallback이 공유하며, 전송·본문 수신도 남은 시간을 사용한다. 직접 조회의 기존 timeout은 변경하지 않고 기존 fanout 5.8초도 늘리지 않는지 확인한다. relay 실패는 기존 실패/partial 계약으로 전달하고 성공 cache를 실패 응답으로 덮거나 실패를 정상 0건으로 cache하지 않는다. mock deadline 검증과 실제 두 서버 간 경과 시간을 구분한다.
- YES24 상태는 요청한 `goods_id`의 책 블록에서만 읽는지 검증한다. 목록 첫 책의 상태가 다른 책에 붙는 경우, detail 실패 뒤 목록 fallback에서 해당 책이 없는 경우, 여러 책의 상태가 다른 경우를 포함한다. relay용 보완만으로 기존 직접 조회 parser 전체를 검수했다고 보고하지 않으며, 직접 조회 경로의 같은 문제는 별도 잔여 점검으로 남긴다.
- 출시 후 전체 34개 기관과 기존 성공한 관악·동작·도봉의 검색·상태, 공유 서재 create/read, sitemap XML, 기존 CI/live smoke를 확인한다. OFF 재배포로 직접 조회에 복귀하는지도 확인한다. 코드 검증·preview 실연결·production 활성화·기관별 복구·남은 실패를 각각 보고한다.

## 공개 피드백

- 신고는 GitHub Issues에 저장한다. 폼에서 사이트/GitHub 공개 사실을 알리고 연락처를 받거나 저장하지 않는다.
- 이번 코드 수정으로 과거 공개 issue의 개인정보가 자동 제거되는 것은 아니다. 이전 신고는 별도 범위와 권한으로 확인한다.
- 최근 목록은 일반 issue/PR가 늘어도 실제 신고를 찾을 수 있어야 한다. pagination과 필터 범위를 검증한다.
- issue closed만으로 문제가 수정됐다고 단정하지 않는다. `state_reason`, 실제 해결 근거와 고객용 상태 문구를 확인한다.
- production에 시험 신고를 만들어 검증하지 않는다. 접수/실패/목록/해결 상태는 mock으로 확인하고, 실제 읽기 조회와 구분해 보고한다.

## 레거시 삭제 게이트

1. `rg` 참조, import, route map, template/static load와 배포 포함 경로를 확인한다.
2. 삭제 파일과 유지/보류 파일, production 영향, 파일 소유권을 먼저 정한다. production helper 일부의 dead function 때문에 파일 전체를 삭제하지 않는다.
3. 삭제 후 참조 잔존을 확인하고 유지 route 응답, sitemap XML, DB 없는 검색과 관련 회귀를 실행한다.
4. [public_repository_inventory.md](public_repository_inventory.md)에 근거를 기록한다. 사용자가 만든 변경·ignored 데이터·local secret은 정리 대상으로 섞지 않는다.

## 감사 보고 완료 기준

보고는 발견 사항, 반영 변경, 검증 통과, 미검증/권한 필요, 배포 상태, 남은 우선순위를 분리한다. 코드 또는 문서 초안을 최종 통합 QA 완료로 표시하지 않는다. 상세 운영 지표가 있는 감사 보고서는 공개 커밋에서 제외하고, 공개 문서에는 반복 가능한 규칙과 공개용 요약만 남긴다.
