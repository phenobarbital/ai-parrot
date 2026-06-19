---
id: F007
query_id: Q010
type: grep
intent: Verify rustworkx, aiosqlite, orjson availability as dependencies
executed_at: 2026-06-16T00:00:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# F007 — All required dependencies already available

## Summary

All three dependencies needed by SQLiteGraphReader are already in the project:
- **rustworkx>=0.15**: Declared in `graphindex` extra (pyproject.toml:159). Used by
  assemble.py, signals.py, communities.py, analytics.py, retriever.py.
- **aiosqlite**: Transitive via `asyncdb>=2.11.6`. Used in storage/backends/sqlite.py.
  Should be added as explicit graphindex extra for clarity.
- **orjson**: Present transitively. Used in tools, outputs, security modules.
  Should also be explicit if relied upon directly.

## Citations

- path: `packages/ai-parrot/pyproject.toml`
  lines: 158-163
  symbol: `graphindex` extra
  excerpt: |
    graphindex = [
        "rustworkx>=0.15",
        "tree-sitter>=0.23",
        "tree-sitter-languages>=1.10",
        "pathspec>=0.12",
    ]

## Notes

aiosqlite and orjson should be added to the graphindex extra explicitly for
the SQLiteGraphReader to have a clean dependency declaration.
