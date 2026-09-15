---
id: F001
query_id: Q001
type: grep
intent: LanceDB is not registered or declared
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F001 — LanceDB is not registered or declared

## Summary

No LanceDB/lancedb matches were returned in the searched Python files and package manifests. Concrete stores ship in ai-parrot-embeddings; core dispatch imports the module matching the configured store key. Adding a backend requires an optional extra and a matching module/class dispatch entry.

## Citations

- path: `packages/ai-parrot-embeddings/pyproject.toml`
  lines: 28-30,62-99
  symbol: `project.optional-dependencies`
  excerpt: |
    dependencies = ["ai-parrot"]

- path: `packages/ai-parrot/src/parrot/stores/__init__.py`
  lines: 1-13
  symbol: `supported_stores`
  excerpt: |
    supported_stores = {

- path: `packages/ai-parrot/src/parrot/interfaces/vector.py`
  lines: 42-65
  symbol: `VectorInterface._get_database_store`
  excerpt: |
    cls_path = f"parrot.stores.{name}"

- path: `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py`
  lines: 131-158
  symbol: `supported_stores`
  excerpt: |
    store_cls_name = supported_stores.get(store_name)

## Notes

Proposed, not existing: packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py with LanceDBStore and a lancedb optional extra. No dependency was installed. Core manifest already declares pyarrow>=25.0 (packages/ai-parrot/pyproject.toml:157); dependency compatibility still needs resolution at implementation time.
