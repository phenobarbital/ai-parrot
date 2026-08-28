---
id: F001
query_id: Q001
type: grep
intent: Where rustworkx is declared in pyproject files
executed_at: 2026-08-28T20:12:00Z
depth: 0
---
# F001 — rustworkx is declared ONLY in the `graphindex` extra of core

## Summary
One match across all `pyproject.toml` files: `packages/ai-parrot/pyproject.toml:213`, inside the optional extra `graphindex`. It is NOT in core `dependencies`, and no satellite package declares it. The `wiki` extra re-includes it via `ai-parrot[graphindex,wiki-languages,leiden]`.

## Citations
- path: `packages/ai-parrot/pyproject.toml`
  lines: 210-220
  symbol: `graphindex` (optional-dependencies)
  excerpt: |
    graphindex = [
        "rustworkx>=0.15",
        "networkx>=3.0",
        "tree-sitter>=0.23",
        "tree-sitter-languages>=1.10",
        "pathspec>=0.12",
        "aiosqlite>=0.17",
        "orjson>=3.9",
    ]
- path: `packages/ai-parrot/pyproject.toml`
  lines: 249-254
  symbol: `wiki` (optional-dependencies)
  excerpt: |
    wiki = [
        "ai-parrot[graphindex,wiki-languages,leiden]",
        "pymupdf>=1.27",
    ]
- path: `packages/ai-parrot/pyproject.toml`
  lines: 147
  symbol: `wikitoolkit` (project.scripts)
  excerpt: |
    wikitoolkit = "parrot.knowledge.wiki.cli:main"
