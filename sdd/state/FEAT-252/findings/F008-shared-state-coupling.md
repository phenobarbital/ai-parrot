---
id: F008
query_id: Q008
type: grep
intent: Confirm REPL shared-state coupling that the in-process decision depends on
executed_at: 2026-06-23T03:55:00Z
parent_id: null
depth: 0
---

# F008 — in-process REPL shared-state coupling (subprocess-deferral evidence)

## Summary
The data_analysis path genuinely shares in-process namespace state with the REPL:
`tools/agent.py:_inject_context_to_repl` writes `python_repl.globals['previous_result']`
and `'<agent>_result'`; `dataset_manager/tool.py` exposes
`set_repl_locals_getter`/`_repl_locals_getter` so `store_dataframe` can read a
DataFrame the model built in the REPL. A subprocess REPL breaks both without a
state-transfer channel — grounding the brainstorm's "stay in-process" decision.

## Citations
- path: `packages/ai-parrot/src/parrot/tools/agent.py`
  lines: 404-422
  symbol: `_inject_context_to_repl`
  excerpt: |
    python_repl.globals['previous_result'] = context
    python_repl.globals[f'{safe_name}_result'] = agent_result.result
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
  lines: 538, 604-610
  symbol: `_repl_locals_getter, set_repl_locals_getter`

## Notes
Confirms in-process isolation is the correct near-term choice; subprocess stays
deferred.
