import re
from pathlib import Path

path = Path('docs/Guide.md')
text = path.read_text(encoding='utf-8')

marker = "3) 덤프/복원으로 서버 PostgreSQL 반영\n"
insert = marker + "\n### C. 상세/상태 조회\n- 상세 페이지는 플랫폼별 고유 ID로 외부 상세 URL을 생성.\n- 대출/예약 현황은 **실시간 API 호출**로 조회(크롤링 시점 데이터는 사용하지 않음).\n"
if insert not in text:
    text = text.replace(marker, insert)

old = re.compile(r"## 12\) 현재 진행 상황 \(2026-01-25\)[\s\S]*?\n(?=## 13\))")
new_section = (
"## 12) 플랫폼별 고유 ID/상태 조회 기준\n"
"- 교보(신버전): `brcd`\n"
"- YES24: `goods_id`\n"
"- 그 외(북큐브/서울/교육청/은평/강남 등): `content_id`\n"
"- 구독형(일부 플랫폼)은 상태 조회 제한 있음(필요 시 UI에서 조회 시도 차단).\n\n"
"## 13) 현재 진행 상황 (2026-01-27)\n"
"- 교보/YES24: 크롤링 + 대출현황 조회 완료.\n"
"- 비(교보/YES24) 8개: 도봉/금천/성동/강남/은평/서울/서울교육청 구독/소장 크롤링 완료.\n"
"- 서울/교육청/은평: content_id 기반 상세 링크/상태 조회 API 추가.\n"
"- 도봉: 모바일 상세 URL로 전환, barcode 문자/숫자 혼합 대응.\n"
"- 적재: 8개 CSV 적재 실행(완료 여부/중복 여부 확인 필요).\n"
"- 이슈: 상세 페이지에서 동일 도서관 중복 표시 발생 → holdings 중복 여부 확인 필요.\n\n"
)
text = old.sub(new_section, text)

text = text.replace("## 13) 진행 상황 업데이트 (2026-01-26)", "## 14) 진행 상황 업데이트 (2026-01-26)")

path.write_text(text, encoding='utf-8')
print('Guide.md updated')
