---
id: F007
query_id: Q008
type: read
intent: ai-parrot-tools graphindex toolkit import + its pyproject deps
executed_at: 2026-08-28T20:16:00Z
depth: 1
parent_id: F003
---
# F007 — ai-parrot-tools imports rustworkx unguarded but declares no dependency on it

## Summary
`parrot_tools/graphindex/toolkit.py` does `import rustworkx` at module level (line 52) alongside numpy and faiss. `packages/ai-parrot-tools/pyproject.toml` contains no `rustworkx`, `networkx`, or `graphindex` reference at all — the satellite silently relies on core's `graphindex` extra being installed.

## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 50-56
  excerpt: |
    import numpy as np
    import rustworkx

    from parrot.tools.toolkit import AbstractToolkit
    from parrot.utils.faiss_logging import quiet_faiss_loader
- path: `packages/ai-parrot-tools/pyproject.toml`
  symbol: dependencies
  excerpt: |
    (no match for rustworkx|networkx|graphindex)
