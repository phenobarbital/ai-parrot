---
id: F004
query_id: Q008
type: read
intent: Confirm SQLiteWikiStore._connect runs _migrate on open; read-only ladder exists
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F004 — Opening a wiki.db is write-first (schema replay + _migrate); read-only is only a fallback

## Summary
`SQLiteWikiStore._connect` (store.py:514-578) opens read-write, replays schema when missing and
calls `self._migrate(conn)` (565). The read-only ladder `_connect_readonly` (580-655;
`mode=ro` → `immutable=1`) engages ONLY when the write attempt fails with a read-only
environment error (`_is_readonly_env_error`, 474; check at 573-576). There is no caller-facing
`read_only=True` switch. Consequence: a federated store opening a *sibling repo's* wiki.db with
the default path could migrate/alter it; the guarantee "query never mutates a foreign namespace"
needs an explicit read-only constructor flag that routes straight to the ladder.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 485-512
  symbol: `SQLiteWikiStore.__init__`
  excerpt: |
    def __init__(self, db_path: str | Path, wiki_name: str = "") -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 514-578
  symbol: `SQLiteWikiStore._connect`
  excerpt: |
    await self._migrate(conn)                       # 565
    ... or not self._is_readonly_env_error(exc)     # 573
    async with self._connect_readonly() as conn:    # 576
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 580-655
  symbol: `SQLiteWikiStore._connect_readonly`
  excerpt: |
    Plain mode=ro is tried first ... falls back to immutable=1, verified by a probe query.
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 474-483
  symbol: `_is_readonly_env_error`
