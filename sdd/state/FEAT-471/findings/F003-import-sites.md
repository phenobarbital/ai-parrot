---
id: F003
query_id: Q003
type: grep
intent: Which source modules import rustworkx and whether guarded
executed_at: 2026-08-28T20:13:00Z
depth: 0
---
# F003 — 9 unguarded top-level `import rustworkx` sites (8 in core graphindex, 1 in ai-parrot-tools)

## Summary
All imports are module-level and unguarded (no try/except), except `export_html.py:42` which is inside a function. Core sites: `graphindex/{communities,analytics,inter_community,assemble,sqlite_reader,signals,retriever}.py`. Satellite: `parrot_tools/graphindex/toolkit.py:52`. Also referenced by `parrot/knowledge/retrieval/symbols.py` and `retrieval/policies/base.py` (docstrings/typing).

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py`
  lines: 30
  symbol: module import
  excerpt: |
    import rustworkx
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py`
  lines: 23-25
  symbol: module import
  excerpt: |
    import aiosqlite
    import orjson
    import rustworkx as rx
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/assemble.py`
  lines: 17
  symbol: module import
  excerpt: |
    import rustworkx
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py`
  lines: 32
  excerpt: |
    import rustworkx
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/analytics.py`
  lines: 18
  excerpt: |
    import rustworkx
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/inter_community.py`
  lines: 19
  excerpt: |
    import rustworkx
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py`
  lines: 32
  excerpt: |
    import rustworkx
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/export_html.py`
  lines: 42
  excerpt: |
        import rustworkx   # function-local
- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 51-52
  excerpt: |
    import numpy as np
    import rustworkx
