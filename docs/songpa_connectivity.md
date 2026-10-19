# 송파 소장형 연결 인수인계

마지막 검증일: **2026-10-19(KST)**. 송파 소장형 검색은 **production 미복구**다. 이 문서는 다음 작업자가 확인된 사실과 아직 확인하지 못한 원인을 구분해 이어가기 위한 기준이다.

## 대상과 현재 운영

- 대상은 `songpa_owned`, [송파 전자도서관](https://ebook.splib.or.kr/)의 **YES24 소장형**이다. 송파책박물관 교보와 송파 구독형은 다른 서비스이므로 대체 검색 성공을 이 기관의 복구로 세지 않는다.
- 현재 main은 `iad1`, 선택적 국내 relay는 `icn1`이다. 성북·영등포·강서는 검색과 같은 책의 상태 조회를 검증해 복구했으며, `songpa_owned`는 relay 활성화에서 제외돼 있다. 운영 절차는 [production_operations.md](production_operations.md)를 따른다.
- 2026-10-19 production 송파 단독 cache miss 검색은 `ConnectTimeout`으로 실패했다. API envelope의 HTTP 200과 빈 결과는 정상 검색 0건이 아니다.

## 확인된 증거

| 검증일·경로 | 관찰 | 해석 범위 |
|---|---|---|
| 2026-10-18 일반 인터넷의 국내 로컬 | 공식 host에서 DNS·TCP·인증서 검증을 포함한 TLS·HTTP 200·기존 YES24 parser가 모두 정상 | 해당 로컬 표본에서 공식 주소와 parser가 작동했다. cloud 연결 성공을 입증하지 않는다. |
| 2026-10-19 같은 Vercel 프로젝트의 고립 `icn1` preview | DNS는 로컬과 같은 대상으로 성공. 진단 종료 15.015초까지 TCP connect가 완료되지 않아 TLS·HTTP에 진입하지 못함 | cloud의 이 표본은 HTTP/HTML 처리 이전에 멈췄다. 운영 timeout을 늘리거나 HTTP header·parser를 바꾸면 해결된다는 근거는 없다. |

실제 cloud 증거는 [진단 run 39179951430](https://github.com/pkkong/soulibrary/actions/runs/39179951430)에서 확인한다. 결과의 `ok: true`는 진단 실행 성공이며, `serviceRecoveryVerified: false`와 함께 읽어야 한다. 진단은 production 설정·도메인·환경변수·지역을 변경하지 않았다.

진단 구현은 `codex/songpa-connection-fix`의 [Draft PR #60](https://github.com/pkkong/soulibrary/pull/60)에 있으며, 이 기록 시점에는 미병합이다. PR 작성·진단 성공은 production 복구가 아니다. 로컬 보조 증거인 ignored `artifacts/qa/20261018-songpa-phases-local.json`, `artifacts/qa/20261019-songpa-cloud-phases.json`은 다른 작업 환경에 없을 수 있으므로 이 문서와 공개 run의 결과 요약을 우선한다.

## 아직 확정하지 못한 원인

같은 YES24 서비스여도 송파·영등포·강서의 접속 대상 IP는 서로 다르다. 기관별 접속 정책이나 네트워크 경로가 다를 가능성은 있지만, 현재 증거만으로 특정 방화벽이나 해외 IP 차단을 원인으로 확정할 수 없다. [송파 공식 전자도서관 안내](https://www.splib.or.kr/intro/menu/10019/contents/40002/contents.do)의 해외 IP 이용 불가 안내도 현재 국내 cloud 실패의 원인을 입증하지 않는다.

검증된 별도 공개 카탈로그 대체 경로는 아직 없다. 전체 main 지역을 바꾸는 방안도 송파 성공만으로 판단하지 않고 기존 정상 기관에 미치는 영향을 함께 검증해야 한다.

## 재개와 완료 기준

1. 검증 날짜와 실행 경로를 남기고, 위 증거와 새 표본의 DNS·TCP·TLS·HTTP 단계를 비교한다. 로컬 성공과 실제 cloud 경로 성공을 구분한다.
2. 공식 공개 카탈로그에서 허용하는 경로를 확인하거나, 실제 cloud 접속 조건·네트워크 원인을 좁힐 추가 증거를 확보한다. 관련 구현은 [설정](../web/config.py), [YES24 connector](../web/live_search/connectors/yes24.py), [relay](../web/live_search/relay.py)에서 확인한다.
3. 실제 production **cache miss 검색에서 책이 일치하는 결과**, **같은 책의 상태 조회**, **타기관 회귀**까지 확인한 뒤에만 복구 상태와 검증일을 갱신한다. 진단 완료·배포 완료와 기관 복구 완료는 별도로 기록한다.

기존 사용자 지시인 **“발송은 하지 말고”**를 유지한다. 외부 문의·메일·메시지를 보내지 않으며, 이번 인수인계 문서화는 발송 승인이 아니다. 임의 proxy·회원용 API·인증 우회·TLS 검증 해제도 현재 승인된 복구 방식에 포함되지 않는다.
