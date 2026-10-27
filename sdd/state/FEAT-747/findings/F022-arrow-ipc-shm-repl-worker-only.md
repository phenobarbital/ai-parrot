---
id: F022
query_id: Q015
type: wiki_query
intent: "Follow-up: Arrow / Polars / zero-copy presence — where does Arrow IPC exist today?"
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: Q003
depth: 1
merged_from: FW-014
---

# F022 — Arrow IPC over shared memory exists ONLY on the PythonREPL host→worker boundary (FEAT-380 TASK-1945); no agent-to-agent by-reference passing, no Polars in core

## Summary

`tools/repl_worker/transport.py` (FEAT-380 Module 7 / G9, TASK-1945) implements DataFrame transport host → sandboxed REPL worker as 'Arrow IPC over a `multiprocessing.shared_memory` block' with pickle+base64 as a logged fallback: `encode_dataframe(df, name) -> EncodedDataFrame`, `decode_dataframe_from_shm(shm_name, size)`, `unlink_shm`, strict-evidence validators (`validate_strict_dataframe`, `ensure_strict_json`, `StrictTransportError`). Ownership rules are documented (host creates/unlinks after worker ACK; worker only closes). The module explicitly states 'Zero-copy applies only where Arrow/pandas dtype conversion is compatible'. Entry points: `repl_worker/handle.py::WorkerHandle.inject_dataframe`, `pythonrepl.py::PythonREPLTool.inject_dataframe`. WorkingMemory is pandas (FW-004). No Polars usage surfaced in the wiki for core/tools; no in-process agent→agent by-reference path exists — the brainstorm's VERIFY 'no zero-copy path; results are serialized today' is CONFIRMED for agent-to-agent, with the nuance that an Arrow-IPC/shm primitive is already in the tree and can be reused for the same-host carrier.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 1-30
  symbol: `module docstring / encode_dataframe / decode_dataframe_from_shm / unlink_shm`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/repl_worker/transport.py (score=0.74)
  excerpt: |
    DataFrame transport: Arrow IPC over shared memory (FEAT-380 Module 7 / G9).
    Arrow IPC over a multiprocessing.shared_memory block is the primary path; pickle+base64 is the fallback only for dtypes Arrow cannot represent
    Zero-copy applies only where Arrow/pandas dtype conversion is compatible

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
  lines: n/a
  symbol: `WorkerHandle.inject_dataframe`
  excerpt: |
    Inject a DataFrame into the worker namespace via Arrow IPC/shm (TASK-1945).

- path: `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
  lines: n/a
  symbol: `PythonREPLTool.inject_dataframe`

- path: `sdd/tasks/completed/TASK-1945-dataframe-arrow-transport.md`
  lines: n/a
  symbol: `TASK-1945 DataFrame transport — Arrow IPC / shared memory`
  wiki_page_id: file:sdd/tasks/completed/TASK-1945-dataframe-arrow-transport.md (score=1.00)

## Notes

`[cross-lane: type=grep, intent=polars|pyarrow imports across packages to confirm Polars is absent from core (parent D6 picks Polars)]` (Q034 covers this partially; widen path to packages/).

[citation-check: verified] tools/repl_worker/transport.py encode_dataframe 83, decode_dataframe_from_shm 266, unlink_shm 300; repl_worker/handle.py inject_dataframe 1060; pythonrepl.py inject_dataframe 1120; polars/shared_memory absent in tools/working_memory
