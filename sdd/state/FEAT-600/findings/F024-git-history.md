---
id: F024
query_id: Q026/Q027
type: git_log
intent: knowledge/wiki is hot (201 commits / 30 days); bots/database is quiet (6 commits / 60 days)
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F024 — knowledge/wiki is hot (201 commits / 30 days); bots/database is quiet (6 commits / 60 days)

## Summary

knowledge/wiki: 201 commits since 2026-08-25 — FEAT-578 ADR plane (merged PR #1442 2026-09-20 + review-fix series), FEAT-584 sdd-execution-optimization (lazy ADR registration in CLI hook startup, 2026-09-21), FEAT-587, FEAT-595 hook prefilter/light console entry (2026-09-23), bookstore MCP plugin fix (2026-09-24). Files repeatedly touched: mcp_server.py, cli.py, claude_code/installer+assets. bots/database: 6 commits — TASK-2816 history ownership (2026-09-04), A2UI TASK-2565 (2026-08-29), formatting; no schema/cache logic change since FEAT-178.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/`
  lines: -
  excerpt: |
    3196ec57c 2026-09-23 feat(wiki): dedicated light wikitoolkit console entry for claude-hook (TASK-3673, FEAT-595); 705f6a56f 2026-09-20 Merge PR #1442 feat-FEAT-578-sdd-spec-wiki-adr; 72a4eb7fc 2026-09-21 TASK-3569 lazy ADR registration for wiki CLI hook startup
- path: `packages/ai-parrot/src/parrot/bots/database/`
  lines: -
  excerpt: |
    668e2521a4 2026-09-04 feat(conversation-history-ownership): TASK-2816; 051939fae0 2026-08-29 TASK-2565 a2ui
