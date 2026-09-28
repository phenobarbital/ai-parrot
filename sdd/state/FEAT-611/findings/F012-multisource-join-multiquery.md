---
id: F012
query_id: Q011
type: read
intent: multi-source join and multiquery lanes
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F012 — Join/union between sources and multiquery slugs

## Summary
Only fixture with sibling sources is linked_dashboard_join.json (activity join targets). Topological order in Python executor and TS lane; missing/cyclic → data_stage error. Multiquery: toolkit sets is_multiquery from describe_slug but never multi_output; frame selection multi_output→'result'→sole key, else []. qs_save_multiquery (allow_write=True) can save tExplode/Join pipelines.

## Citations
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_dashboard_join.json`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_multiquery_public.json`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/executor.py`
  lines: 97-150
  symbol: topological ordering
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/index.ts`
  lines: 91-159
  symbol: ordering / ensureFrame
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/linked/fetch.ts`
  lines: 22-48
  symbol: frame selection, fetchSource
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/query_slug.py`
  lines: 154, 206-238
  symbol: MultiQS dispatch, `_select_multi_frame`
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 379, 605
  symbol: is_multiquery, qs_save_multiquery
