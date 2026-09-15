---
id: F014
query_id: Q016
type: git_log
intent: Recent history on the tool and its sibling sources.
executed_at: 2026-09-15T02:54:00Z
duration_ms: 800
parent_id: null
depth: 0
---
# F014 — No commits in 90 days on qsource.py, querytoolkit.py or query_slug.py
## Summary
`git log --since="90 days"` on the three files returns nothing. `qsource.py` was last touched 2026-03-23 (monorepo migration TASK-405 / dependency fixes) and 2026-03-22 (TASK-389 lazy imports); its logic predates December 2025. There is no in-flight work to coordinate with; the `DataNotFound` TYPE_CHECKING bug (F002) has been latent since the lazy-import change.
## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  excerpt: |
    fd2a35e1e|2026-03-23|fixing dependencies of all tools
    8253e8bdf|2026-03-23|feat(monorepo-migration): TASK-405 — Tools Migration Batch 3 (Complex/Heavy)
    65fd61bca|2026-03-22|feat(runtime-dependency-reduction): TASK-389 — Database/Query Tools Lazy Imports
    7b61d3924|2026-03-07|Simple MCP Server now support importing decorated tools (@tool)
    d26ebc59a|2025-12-10|fixing load time for agents
