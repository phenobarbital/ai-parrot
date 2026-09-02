---
id: F002
query_id: Q002
type: wiki_query
intent: Orient — PythonREPLTool worker integration, namespace API, dedicated executor
executed_at: 2026-09-02T13:37:05+02:00
duration_ms: 3900
parent_id: null
depth: 0
---

# F002 — Wiki orientation: PythonREPLTool ↔ worker integration

## Summary

Confirms the integration lineage: TASK-1939 (dedicated bounded executor), TASK-1943 (PythonREPLTool → worker + namespace API `get_var/set_var/list_vars/snapshot`), TASK-1944 (port `.locals`/`.globals` call sites to the namespace API — this is where `PythonPandasTool` seeding was introduced), TASK-2218 (matplotlib purge). No page names a readiness handshake.

## Citations

- path: `sdd/tasks/completed/TASK-1943-pythonrepl-worker-integration.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-1943-pythonrepl-worker-integration.md (score=1.00)
- path: `sdd/tasks/completed/TASK-1944-port-namespace-callsites.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-1944-port-namespace-callsites.md (score=0.14)
- path: `sdd/tasks/completed/TASK-1939-repl-dedicated-executor.md`
  wiki_page_id: file:sdd/tasks/completed/TASK-1939-repl-dedicated-executor.md (score=0.82)
- path: `packages/ai-parrot/tests/repl_worker/test_callsites.py`
  wiki_page_id: file:packages/ai-parrot/tests/repl_worker/test_callsites.py (score=0.07)
