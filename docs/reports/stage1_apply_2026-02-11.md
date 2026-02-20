# Stage1 Apply Result (2026-02-11)

- Applied at: `2026-02-11 13:18:33`
- DB: `soulib_test`
- Command:
  - `python scripts/stage1_apply_exact_dedupe.py --apply --scope all --dedupe-holdings --add-unique`

## Precheck (from apply run)
- total_groups: `12,315`
- total_group_rows: `25,353`
- safe_groups: `6,700` (`safe_rows=13,474`)
- review_groups: `5,615` (`review_rows=11,879`)
- books_to_merge: `13,038`
- holdings_to_reassign: `16,700`

## Applied
- holdings_reassigned: `16,700`
- books_deleted: `13,038`
- holdings_deleted_by_book_library_dedupe: `200,330`

## Postcheck
- books_exact_dup_groups_after: `0`
- holdings_book_library_dup_groups_after: `0`

## Current DB Snapshot (post-apply verify)
- books_total: `551,165`
- holdings_total: `1,474,705`
- unique constraint:
  - `books.uq_books_norm` (`UNIQUE (title_norm, author_norm, publisher_norm)`)

## Sample Check (post-apply)
- `프로젝트 헤일메리` (`title_norm=프로젝트헤일메리`): `valid_book_rows=6`, `visible_groups=6`
- `불편한 편의점` (`title_norm=불편한편의점`): `valid_book_rows=1`, `visible_groups=1`
- `어서 오세요, 휴남동 서점입니다` (`title_norm=어서오세요휴남동서점입니다`): `valid_book_rows=1`, `visible_groups=1`

해석:
- exact 중복은 제거됐지만, `프로젝트 헤일메리`처럼 norm 3키가 다른 분리는 2단계(canonical 백필/식별자 병합)에서 추가 정리 대상.

## Rollback
- Backup artifact: `/tmp/soulib_test_stage1_20260211.dump`
- Restore:
  - `docker exec -e PGPASSWORD=localpass soulib-postgres pg_restore -U root -d soulib_test --clean --if-exists /tmp/soulib_test_stage1_20260211.dump`
