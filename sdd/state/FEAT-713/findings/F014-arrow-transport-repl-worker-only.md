---
id: F014
query_id: Q004
type: wiki_query
intent: "Orient: Arrow transport for DatasetManager / pandas REPL worker (FEAT-750, PR #1836)."
executed_at: 2026-11-11T22:41:00Z
duration_ms: 0
parent_id: null
depth: 1
lane_ids: [FW-004]
---

# F014 — Arrow already crosses one boundary in core: the PythonREPL host↔worker transport (Arrow IPC over shared memory, pickle refused in strict mode, Arrow value codec from FEAT-750); there is no Polars in core

## Summary

The graph's Arrow hits are all on the REPL worker: `tools/repl_worker/transport.py` (FEAT-380 TASK-1945, hardened by FEAT-538) encodes a DataFrame as an Arrow IPC stream in a `multiprocessing.shared_memory` block, with pickle+base64 only as a logged fallback and `StrictTransportError` raised before any pickle when strict; FEAT-750 `bots-data-fixes` (TASK-4751) added an Arrow value codec for repl_worker values. Earlier research (FEAT-746 FC-013, FEAT-747 F022) recorded that pyarrow is imported in about ten core/tools modules and that Polars appears nowhere. This is precedent for FEAT-713's "Arrow as the bridge, no pickle across trust boundaries", and a caveat for its polars path (`df.to_arrow()`): there is no Polars user to serve today.

## Citations

- wiki: `file:sdd/tasks/completed/TASK-4751-arrow-value-codec-tolerant-inference.md` (Q004 score=1.00)

- wiki: `file:sdd/specs/bots-data-fixes.spec.md` (Q004 score=0.98)

- wiki: `file:sdd/state/FEAT-746/findings/.audit/FC-013-polars-arrow-footprint.md` (Q004 score=0.71; Q003 score=0.55)

- wiki: `file:sdd/state/FEAT-747/findings/F022-arrow-ipc-shm-repl-worker-only.md` (Q004 score=0.23)

- wiki: `sym:packages/ai-parrot/tests/repl_worker/test_e2e.py#test_share_dataframe_delivers_into_worker_namespace` (Q004 score=0.00; Q003 score=0.32)

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 1-7
  symbol: module docstring
  excerpt: |
    """DataFrame transport: Arrow IPC over shared memory (FEAT-380 Module 7 / G9).
    Arrow IPC over a multiprocessing.shared_memory block is the primary
    path; pickle+base64 is the fallback **only** for dtypes Arrow cannot

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 46-56
  symbol: `StrictTransportError`
  excerpt: |
    class StrictTransportError(Exception):
        Raised **before** any pickle payload is constructed (FEAT-538 §2 "REPL

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 83-167
  symbol: `encode_dataframe`
  excerpt: |
    with pa.ipc.new_stream(sink, table.schema) as writer:
    return EncodedDataFrame(format="arrow", shm_name=shm.name, size=size, payload=None)

- path: `sdd/specs/bots-data-fixes.spec.md`
  lines: null
  symbol: title
  excerpt: |
    Feature Specification: bots-data-fixes — Arrow transport for DataFrames in repl_worker values

## Notes

- `transport.py` line ranges are second-hand, from FEAT-746 FC-013 (2026-10-25); FEAT-750 and PR #1836 touched the worker after that date, so the ranges may have shifted.
- [cross-lane: type=read, intent=re-verify transport.py anchors (encode_dataframe, StrictTransportError) and locate the FEAT-750 Arrow value codec module]
