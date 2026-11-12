---
id: FC-006
query_id: Q009
type: tree
intent: "Structure of the navigator-auth migrations package (versions, runner, ledger)."
executed_at: 2026-11-12T20:40:51Z
duration_ms: 200
parent_id: null
depth: 0
---

# FC-006 — navigator_auth/migrations layout: 7 modules + sql/<set>/NNN_*.sql

## Summary

The reference implementation is a self-contained package of 7 modules (~1,230 lines Python) plus 13 SQL files grouped
in five *sets* (`identity`, `mfa`, `oauth2`, `passkey`, `vault`), each numbered `NNN_description.sql` within its set.

## Citations

- path: `../navigator-auth/navigator_auth/migrations/`
  excerpt: |
    __init__.py(35) access.py(189) catalog.py(118) checks.py(234) cli.py(213) runner.py(341) startup.py(93)
    sql/identity/001_identity_credentials.sql ... 006_identity_drop_legacy_uid.sql
    sql/mfa/001_mfa_tables.sql 002_mfa_secrets.sql
    sql/oauth2/001_oauth2_schema.sql
    sql/passkey/001_passkey_credentials.sql
    sql/vault/001_create_vault_tables.sql 002_vault_crypto_hardening.sql

- path: `../navigator-auth/pyproject.toml`
  lines: 74-75
  excerpt: |
    [project.scripts]
    navauth = "navigator_auth.migrations.cli:console_entry"

## Notes

Module roles: catalog (discovery/checksum), runner (ledger/lock/apply), checks (pre/post conditions), access
(runtime-role GRANTs), startup (read-only pending warning), cli (argparse). See FC-007..FC-010.
