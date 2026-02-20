# Stage1 Backup (2026-02-11)

- Scope: rollback point before Stage1 destructive dedupe
- DB: `soulib_test`
- Container: `soulib-postgres`

## Backup Artifact
- Path (in container): `/tmp/soulib_test_stage1_20260211.dump`
- Size: `62MB`

## Commands
- Backup:
  - `docker exec -e PGPASSWORD=localpass soulib-postgres pg_dump -U root -d soulib_test -Fc -f /tmp/soulib_test_stage1_20260211.dump`
- Verify:
  - `docker exec soulib-postgres ls -lh /tmp | findstr soulib_test_stage1_20260211.dump`
- Rollback (restore):
  - `docker exec -e PGPASSWORD=localpass soulib-postgres pg_restore -U root -d soulib_test --clean --if-exists /tmp/soulib_test_stage1_20260211.dump`

## Note
- `pg_restore --clean --if-exists` is destructive to current DB state.
- Use only after explicit approval.
