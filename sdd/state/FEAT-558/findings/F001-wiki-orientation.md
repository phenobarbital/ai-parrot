---
id: F001
query_id: Q001
type: wiki_query
intent: Orient — locate the current QuerySource tool, sibling sources and prior SDD tasks.
executed_at: 2026-09-15T02:40:00Z
duration_ms: 4000
parent_id: null
depth: 0
---
# F001 — Wiki orientation: QuerySource surfaces in the repo
## Summary
The wiki ranks three QS() consumers: `parrot_tools/qsource.py` (QSourceTool, score 0.28/0.00 on the file), `parrot/tools/dataset_manager/sources/query_slug.py` (QuerySlugSource / MultiQuerySlugSource, TASK-215) and `parrot/tools/dataset_manager/computed.py` (imports the QS function catalog). Prior SDD work: TASK-389 (lazy imports for DB/query tools), TASK-215 (QuerySlugSource). No page names a "QuerysourceToolkit" — it does not exist yet.
## Citations
- path: `packages/ai-parrot-tools/src/parrot_tools/qsource.py`
  symbol: `QSourceTool`
  excerpt: wiki id file:packages/ai-parrot-tools/src/parrot_tools/qsource.py — "QuerySource Tool for AI-Parrot"
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  symbol: `QuerySlugSource`, `MultiQuerySlugSource`, `_get_qs`
  excerpt: wiki sym ..#_get_qs (score 1.00) "Lazily import QS from querysource."
- path: `sdd/tasks/completed/TASK-215-queryslug-source.md`
- path: `sdd/tasks/completed/TASK-389-db-tools-lazy-imports.md`
