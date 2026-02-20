# Stage2 Apply Result (2026-02-11)

- Applied at: `2026-02-11 14:15:22`
- DB: `soulib_test`
- Command:
  - `python scripts/stage2_apply_identifier_merge.py --apply --dedupe-holdings`

## Applied
- holdings_canonical_filled: `1,221,608`
- holdings_reassigned_by_canonical: `10,386`
- books_single_canonical_set: `439,661`
- books_merge_group_refreshed: `439,661`
- orphan_books_deleted: `28,240`
- holdings_deleted_by_book_library_dedupe: `6,335`

## Postcheck (from apply output)
- books_total: `522,925`
- holdings_total: `1,468,370`
- holdings_no_canonical: `5,463`
- brcd_no_canonical: `0`
- goods_no_canonical: `0`
- content_no_canonical: `0`
- holdings_book_library_dup_groups: `0`
- canonical_multi_book_groups_after: `0`

## Idempotence Check
- Re-run dry-run after apply:
  - `fillable_rows=0`
  - `book_map_rows=0`
  - `holdings_to_reassign_effective=0`

## Search-side Aggregate Indicator
- `title_norm + author_norm` 기준 multi-group 비율: `4.39%`
  - 측정 쿼리 시점: post-stage2
  - 해석: 식별자 병합 이후에도 텍스트 분리 케이스가 남아 3단계(텍스트/예외 규칙)가 필요함.

## Sample Check
- `불편한 편의점`: `valid_book_rows=1`, `visible_groups=1`
- `어서 오세요, 휴남동 서점입니다`: `valid_book_rows=1`, `visible_groups=1`
- `프로젝트 헤일메리`: `valid_book_rows=6`, `visible_groups=6`

## Note
- 실행 명령은 장시간 실행으로 셸 타임아웃 코드(124)로 표기되었으나,
  출력 JSON과 후속 검증(dry-run 재실행/DB 수치)으로 적용 완료를 확인했다.
