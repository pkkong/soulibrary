# Stage2 Dry-run (Pre-Apply, 2026-02-11)

- Measured at: `2026-02-11 13:51:38`
- DB: `soulib_test`
- Command:
  - `python scripts/stage2_apply_identifier_merge.py`

## Precheck Summary
- total_holdings: `1,474,705`
- canonical_missing_before: `1,227,086`
- fillable_rows: `1,221,608`
- canonical_multi_book_groups (effective): `7,664`
- book_map_rows: `8,151`
- holdings_to_reassign_effective: `10,386`

## Rule Breakdown
- `from_brcd`: `907,982`
- `from_goods_id`: `3,944`
- `content_to_goods_crosswalk`: `6,870`
- `content_to_brcd_crosswalk`: `3,109`
- `content_bookcube_namespace`: `70,504`
- `content_seoul_namespace`: `26,259`
- `content_sen_namespace`: `169,696`
- `content_gangnam_namespace`: `24,383`
- `content_eunpyeong_namespace`: `8,861`
- `keep_existing`: `247,619`
- `no_identifier`: `5,478`

## Interpretation
- Stage2 적용 시 canonical 공백 대부분을 식별자 기준으로 채울 수 있는 상태.
- `no_identifier` 5,478건은 식별자가 없어 Stage2로도 canonical 채움 불가.
