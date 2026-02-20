# Stage2 Backup (2026-02-11)

- Scope: rollback point before Stage2 identifier-based merge
- DB: `soulib_test`
- Container: `soulib-postgres`

## Backup Artifact
- Path (in container): `/tmp/soulib_test_stage2_20260211_preapply.dump`
- Size: `59MB`

## Commands
- Backup:
  - `docker exec -e PGPASSWORD=localpass soulib-postgres pg_dump -U root -d soulib_test -Fc -f /tmp/soulib_test_stage2_20260211_preapply.dump`
- Verify:
  - `docker exec soulib-postgres ls -lh /tmp | findstr soulib_test_stage2_20260211_preapply.dump`
- Rollback (restore):
  - `docker exec -e PGPASSWORD=localpass soulib-postgres pg_restore -U root -d soulib_test --clean --if-exists /tmp/soulib_test_stage2_20260211_preapply.dump`

## Note
- Stage2 apply before this backup can still be restored via Stage1 backup:
  - `/tmp/soulib_test_stage1_20260211.dump`
