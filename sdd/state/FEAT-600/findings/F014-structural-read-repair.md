---
id: F014
query_id: Q014
type: wiki_page
intent: StructuralService._ensure_fresh is the read-repair shape: page_hashes vs disk hash, non-blocking lock, stale flag
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F014 — StructuralService._ensure_fresh is the read-repair shape: page_hashes vs disk hash, non-blocking lock, stale flag

## Summary

service.py L431-479: compare store.page_hashes(concept_ids) with _disk_hash; take wiki_write_lock(timeout=0) — if busy set _lock_busy so callers flag hits stale=True; rescan existing files via scan_repository + _ingest_files(force=True); remove deleted. For the schema plane the trigger is a proven-stale DB error instead of a file hash, but the lock/stale-flag/partial-repair shape is identical.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py`
  lines: 431-479
  symbol: `StructuralService._ensure_fresh`
  excerpt: |
    known = await self._store.page_hashes(concept_ids) … with wiki_write_lock(self._config.storage_path(self._root), timeout=0) as acquired: if not acquired: self._lock_busy = True

## Notes

TASK-3353 (FEAT-569) adds StructuralService(read_repair=False) for rootless mode — the schema lookup tools need the same switch.
