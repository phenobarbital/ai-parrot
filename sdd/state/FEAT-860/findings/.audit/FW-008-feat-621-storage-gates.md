---
id: FW-008
query_id: Q004
type: wiki_page
intent: "Read the FEAT-621 storage release gates (no startup DDL / no migration at startup / ai_bots frozen)."
executed_at: 2026-11-09T17:13:20Z
duration_ms: 300
parent_id: FW-005
depth: 2
---

# FW-008 — FEAT-621 gates: no DDL outside migration files and no migration at startup (scoped to the Studio stack); creation.sql + _load_database_bots frozen

## Summary

`test_no_ddl_outside_migrations` scans only the Studio storage stack (`handlers/studio/**`, `studio_runtime.py`,
`toolkit_persistence.py`, `vault_utils.py`, `broker.py`) for CREATE/ALTER/DROP. `test_no_migration_call_at_startup`
scans ALL server+core source, but only for the names `apply_studio_migrations` / `stamp_migrations`, and lists
startup callables (`setup`, `setup_registry_only`, …) that must never call them. `test_load_database_bots_untouched`
(AC17) byte-compares `BotManager._load_database_bots` and `creation.sql` with the origin/dev merge-base. The crew
handler directory is outside the DDL gate, but the policy it encodes is "DDL in migration files, applied by an
explicit runner, never on startup".

## Citations

- path: `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
  lines: 33-45
  symbol: `MIGRATION_ENTRYPOINTS`
  excerpt: |
    MIGRATION_ENTRYPOINTS = ("apply_studio_migrations", "stamp_migrations")
    STARTUP_FUNCTIONS = {"setup", "setup_registry_only", "setup_studio_routes", "ensure_studio_storage", ...}
- path: `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
  lines: 55-71
  symbol: `test_no_ddl_outside_migrations`
  excerpt: |
    files = _studio_stack_files()
    offenders = [... if DDL.search(line)]
    assert not offenders, "DDL outside storage/migrations/*.sql:\n" + ...
- path: `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
  lines: 84-101
  symbol: `test_no_migration_call_at_startup`
  excerpt: |
    modules = sorted(p for root in (SERVER_SRC, CORE_SRC) for p in root.rglob("*.py"))
    assert not startup_hits, f"startup hooks apply migrations: {startup_hits}"
- path: `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py`
  lines: 268-283
  symbol: `test_load_database_bots_untouched`
  excerpt: |
    assert _method_source(new_manager, "BotManager", "_load_database_bots") == _method_source(old_manager, ...)
    assert (REPO / CREATION_SQL).read_text(...) == _with_sanctioned_deltas(old_sql)

## Notes

Tension with the request: "migration=True" moving data at initialization is a startup-time data migration. It
does not trip these gates (different names, crew dir out of scope), but it contradicts the FEAT-621 policy.
Options: (a) startup-time copy behind an explicit opt-in flag (request as written), (b) a one-shot CLI /
explicit method the host calls. Also: the request's "inicializan los dos" table creation would be runtime DDL —
allowed by the PostgresResultStorage precedent (FW-010), disallowed by the Studio precedent.
