---
id: F005
query_id: Q012
type: wiki_page
intent: LedgerStore(SQLiteWikiStore) + LedgerService.from_root are the plane-in-its-own-dir template
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — LedgerStore(SQLiteWikiStore) + LedgerService.from_root are the plane-in-its-own-dir template

## Summary

LedgerStore subclasses SQLiteWikiStore, forwards db_path/wiki_name/read_only/sqlite_policy/persistent_writer, and adds ledger_transaction() on top of FEAT-557's _write(). LedgerService.from_root resolves find_shared_root(root), loads config via load_effective_config (call-site guard forbids raw load_project_config), mkdirs config.ledger_path, opens LedgerStore(ledger_dir/'ledger.db', wiki_name='ledger', sqlite_policy=sqlite_policy_from_config(config)). A SchemaStore/SchemaPlaneService is the same ~40 lines with `schema_path`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py`
  lines: 24-123
  symbol: `LedgerStore`
  excerpt: |
    class LedgerStore(SQLiteWikiStore): … super().__init__(db_path=…, wiki_name=…, read_only=…, sqlite_policy=…, persistent_writer=…)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
  lines: 116-143
  symbol: `LedgerService.from_root`
  excerpt: |
    shared_root = find_shared_root(root) or (root or Path.cwd()).resolve(); config = load_effective_config(shared_root).config; ledger_dir = config.ledger_path(shared_root); store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)

## Notes

TASK-3354 (FEAT-569) is adding LedgerService.from_dir() for a rootless deployment — the schema plane needs the same constructor from day one (see F023).
