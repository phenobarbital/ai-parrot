---
id: F002
query_id: Q002
type: grep
intent: Which lock entries depend on rustworkx
executed_at: 2026-08-28T20:12:30Z
depth: 0
---
# F002 — In uv.lock, only `ai-parrot` (extras graphindex/wiki) requires rustworkx

## Summary
`uv.lock` lists rustworkx 0.18.1 (requires numpy only). The only dependents are the `ai-parrot` package's `graphindex` and `wiki` optional-dependency groups (lines 634, 777) with marker `extra == 'graphindex'` (line 1006). No other package pulls it, so it is not a "transitive" dependency — it is an extra-only dependency. `uv pip show rustworkx` → Required-by: (empty).

## Citations
- path: `uv.lock`
  lines: 1006
  symbol: ai-parrot metadata.requires-dist
  excerpt: |
    { name = "rustworkx", marker = "extra == 'graphindex'", specifier = ">=0.15" },
- path: `uv.lock`
  lines: 770-780
  symbol: ai-parrot.optional-dependencies.wiki
  excerpt: |
    wiki = [
        { name = "aiosqlite" },
        { name = "leidenalg" },
        ...
        { name = "rustworkx" },
