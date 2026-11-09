---
id: F010
query_id: Q017
type: grep
intent: "Find existing storage migration patterns (migrate_from / migration= flags) to reuse."
executed_at: 2026-11-09T17:34:00Z
duration_ms: 1300
parent_id: null
depth: 0
merged_from: [FC-012]
---

# F010 — No `migration=True` flag exists anywhere; nearest precedents are `recipes/migrate.py::migrate_store` (idempotent sweep + dry_run + MigrationReport) and Studio's ledgered `apply_studio_migrations` (never at startup)

## Summary

`grep "migrat(e|ion)\s*[:=]\s*(bool|True|False)|def migrate_from|..."` over `packages/*/src` finds no
constructor/config flag named `migration` (only `o365_oauth.migrate_legacy_device_grant`). A broader grep for
`def (_)?(migrate|backfill|import_from|copy_from)*` lists in-place schema migrators (wiki store, graphindex,
sqlite) and two reusable *data-sweep* shapes: (a) `parrot.outputs.a2ui.recipes.migrate.migrate_store(store, *,
dry_run=False) -> MigrationReport` — iterates `store.list()`, per-item try/except recorded in
`report.errors[name]`, idempotent (skips items already migrated), one atomic save per item, `dry_run` never
writes; (b) `handlers/studio/storage/migrate.py::apply_studio_migrations(pool, *, dry_run=False)` — SQL schema
migrations with an advisory lock, ledger re-read, and an explicit "Never called at startup" contract.
Cross-backend "copy from store A into store B" has no precedent; `meeting_registry.backfill_from_vault`
(616) is the only other backfill-style method.

## Citations

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/migrate.py`
  lines: 11-13
  symbol: `module docstring`
  excerpt: |
    :func:`migrate_store` sweeps an :class:`~parrot.outputs.a2ui.recipes.store.AbstractRecipeStore`,
    re-saving every recipe still at ``schema_version < SUPPORTED_SCHEMA_VERSION``
    (idempotent — a v2 recipe is a no-op) and reporting a :class:`MigrationReport`.

- path: `packages/ai-parrot/src/parrot/outputs/a2ui/recipes/migrate.py`
  lines: 101-135
  symbol: `migrate_store`
  excerpt: |
    async def migrate_store(store: AbstractRecipeStore, *, dry_run: bool = False) -> MigrationReport:
        """... Each recipe is read, migrated, and re-saved with its own get()/save() call —
        ... so one recipe's failure never partially-writes another.
        report = MigrationReport(dry_run=dry_run)
        summaries = await store.list(owner=None)
        for summary in summaries:
            try: raw_version = await store._raw_schema_version(name, owner=owner)
            except Exception as exc:  # noqa: BLE001 - report, never abort the sweep
                report.errors[name] = str(exc); continue

- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrate.py`
  lines: 179-195
  symbol: `read_ledger / apply_studio_migrations`
  excerpt: |
    async def read_ledger(conn: Any) -> LedgerState:
        reg = ... "SELECT to_regclass('navigator.ai_studio_migrations')"
    async def apply_studio_migrations(pool: Any, *, dry_run: bool = False) -> list[int]:
        """Per pending file: studio_transaction → body (advisory lock first) → re-read ledger →
        skip if recorded → trailer → commit. ... Never called at startup."""

- path: `packages/ai-parrot/src/parrot/agents/meeting_registry.py`
  lines: 616
  symbol: `backfill_from_vault`
  excerpt: |
    async def backfill_from_vault(

- path: `packages/ai-parrot/src/parrot/auth/o365_oauth.py`
  lines: 273
  symbol: `migrate_legacy_device_grant`
  excerpt: |
    async def migrate_legacy_device_grant(

## Notes

- Design implications for `migration=True`: idempotency (re-running must not duplicate — natural with an
  `ON CONFLICT (tenant, name)` upsert), per-crew error isolation + a report, an optional `dry_run`, and a
  decision on whether "mover" deletes from Redis after a verified copy (the source says "mover").
- Multi-worker gunicorn: if migration runs inside `on_startup`, every worker would run it concurrently —
  the Studio runner avoids startup and uses an advisory lock; a crew migration at startup needs the same
  (e.g. `pg_advisory_lock`) or must be idempotent + safe under races.
- `[cross-lane: type=git_log, intent=check whether recipes/migrate.py or studio migrate.py history shows how operators trigger migrations (CLI vs startup flag)]`
