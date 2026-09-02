---
id: F015
query_id: Q014
type: read
intent: Probe — plain PythonREPLTool locally; worker bootstrap cost
executed_at: 2026-09-02T13:40:00+02:00
duration_ms: 6000
parent_id: null
depth: 0
---

# F015 — Baseline (idle 12-core host): bootstrap ≈ 2.4 s, everything works

## Summary

`scratchpad/repro.py` (plain `PythonREPLTool`, two `_execute` calls + `list_vars`): first call **2.45 s** (includes cold spawn), second 0.00 s, `list_vars` OK. Worker timeline from the drain logs: spawn `13:40:02.761` → `STARTING APP: Navigator` `13:40:04.71` (≈1.95 s just to reach the parrot package init) → `repl_worker: ready` `13:40:05.20` (≈2.4 s). Three workers boot concurrently (1 session + 2 spares). Import alone: `python -c "from parrot.tools.pythonrepl import PythonREPLTool"` = **1.74 s wall** idle. So on an idle machine the 5 s budget has ~2.5 s of headroom; any 2× slowdown (CPU contention, cold page cache, slow navconfig/vault/logstash init) eats it.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py`
  lines: 275
  excerpt: |
    [INFO] 13:40:05,200 __main__(worker.py:275) :: repl_worker: ready (max_workers config=0), entering service loop
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: 187
  excerpt: |
    [DEBUG] 13:40:02,761 WorkerHandle: spawned worker pid=81228
