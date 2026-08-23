---
id: F014
query_id: Q023
type: git_log
intent: Recent activity on the wiki package (conflict risk with in-flight work)
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F014 — 25 commits in 45 days; none touch store resolution, ids, or merge helpers

## Summary
Dominant themes: Perl scanner (FEAT ~ TASK-2259..2261, languages/), Obsidian vault mode + MCP
exposure (861ab2110, 211cc3aaa), ArangoDB backend usability (c51372341, Javier León —
two-language search), supervised ingestion (TASK-2072..2075), MCP server (TASK-2080..2082),
CodeQL fixes (f2c34cb44). No commit touches `_resolve_read_store`, `context.py` ids, or
`search.py` merge helpers. `b5893f4e4` "wire the PageIndex plane" touched cli.py — rebase risk
only. FEAT-449 (legal wiki) is still at plan stage (state.json phase plan_drafted, untracked).

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/`
  excerpt: |
    da9c0f866 2026-08-21 Jesus fix: suppress SyntaxWarning ...
    b5893f4e4 2026-08-21 Jesus fix(bedrock,wiki): ... wire the PageIndex plane
    c51372341 2026-08-20 Javier León fix(wiki): make the ArangoDB backend usable, searchable in two languages
    861ab2110 2026-08-16 Claude feat(wiki): expose the Obsidian vault through the wikitoolkit MCP server
    3c8f713b8 2026-08-03 Jesus feat(mcp-local-server-wikitoolkit): TASK-2081 — WikiToolkit MCP server + CLI command
    216bd0c1f 2026-08-02 Jesus Lara feat(supervised-wiki-ingestion): TASK-2075 — wikitoolkit ingest CLI
- path: `sdd/state/FEAT-449/state.json`
  excerpt: |
    "phase": "plan_drafted"
