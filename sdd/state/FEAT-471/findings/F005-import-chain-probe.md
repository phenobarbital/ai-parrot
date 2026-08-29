---
id: F005
query_id: Q006
type: read
intent: Runtime probe — does wikitoolkit's entrypoint import without rustworkx?
executed_at: 2026-08-28T20:15:00Z
depth: 1
parent_id: F003
---
# F005 — `wikitoolkit` entrypoint hard-fails without rustworkx via graphindex/__init__ → signals

## Summary
Blocking `rustworkx` in `sys.modules` and importing `parrot.knowledge.wiki.cli` raises `ModuleNotFoundError`. Chain: `wiki/cli.py:49` → `wiki/documents.py:31` (imports `parrot.knowledge.graphindex.extractors.loader`) → `graphindex/__init__.py:31` (eagerly imports `signals`) → `signals.py:30 import rustworkx`. So EVERY `wikitoolkit` subcommand (query/page/related/mcp/status), not just `build`, needs rustworkx even though the CLI ships in core.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 49
  excerpt: |
    from parrot.knowledge.wiki.documents import ...
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/documents.py`
  lines: 31
  excerpt: |
    from parrot.knowledge.graphindex.extractors.loader import PLAIN_TEXT_EXTENSIONS
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py`
  lines: 31
  excerpt: |
    (package __init__ imports signals eagerly)
- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py`
  lines: 30
  excerpt: |
    import rustworkx
