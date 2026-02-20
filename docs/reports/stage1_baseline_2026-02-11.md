# Stage1 Baseline (2026-02-11)

- Measured at: `2026-02-11 11:23:01`
- DB: `soulib_test`
- Scope: Stage1 before destructive dedupe (`title_norm + author_norm + publisher_norm` exact match only)

## Core Counts
- `books_total`: `564,203`
- `holdings_total`: `1,675,035`
- `books_exact_norm_dup_groups`: `12,315`
- `books_exact_norm_dup_rows`: `25,353`
- `holdings_book_library_dup_groups`: `162,695`
- `holdings_book_library_dup_rows`: `346,847`

## Identifier Present But Missing Canonical
- `brcd`: `940,612`
- `goods_id`: `9,255`
- `content_id`: `324,417`

## Sample Titles (Visible Group Split)
- `project_hail_mary` (`title_norm=프로젝트헤일메리`): `valid_book_rows=6`, `visible_groups=6`
- `inconvenience_store` (`title_norm=불편한편의점`): `valid_book_rows=2`, `visible_groups=2`
- `humnamdong_bookstore` (`title_norm=어서오세요휴남동서점입니다`): `valid_book_rows=2`, `visible_groups=2`

## Note
- This baseline is the comparison point for Stage1 execution results (post-dedupe).
