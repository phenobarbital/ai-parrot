---
id: FC-013
query_id: [Q031]
type: read
intent: "Polars / Arrow usage in core and tools (D6 feasibility, where dataframes already flow); read the Arrow IPC transport used by the REPL worker."
executed_at: 2026-10-25T22:47:25Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-013 — No Polars anywhere; pyarrow is used in 10 modules, and an Arrow-IPC dataframe transport (shared memory, pickle fallback refused in strict mode) already exists for the REPL worker

## Summary

Files matching `import polars|pl.DataFrame|to_arrow|write_ipc|read_ipc|pyarrow` in core + tools (non-test): `tools/toolkit.py`, `tools/dataset_manager/sources/{iceberg,__init__}.py`, `tools/working_memory/task_memory/blob.py`, `tools/repl_worker/{transport,worker,handle,protocol}.py`, `parrot_tools/sandboxtool.py`, `parrot_tools/powerbi.py` — all pyarrow, none Polars. `tools/repl_worker/transport.py` (FEAT-380 G9 / FEAT-538) implements `encode_dataframe()` producing `EncodedDataFrame(format: "arrow" | "pickle", shm_name, size, payload)`: Arrow IPC stream (`pa.ipc.new_stream`) over `multiprocessing.shared_memory`, pickle+base64 only as a logged fallback, and `StrictTransportError` raised before any pickle when strict (task-memory evidence must never travel as pickle). This is the in-repo precedent for D6 ("Arrow IPC ... sandbox-safe choice over pickle") but it is host↔worker, not network.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 1-7
  symbol: module docstring
  excerpt: |
    """DataFrame transport: Arrow IPC over shared memory (FEAT-380 Module 7 / G9).
    Arrow IPC over a multiprocessing.shared_memory block is the primary
    path; pickle+base64 is the fallback **only** for dtypes Arrow cannot
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 36
  symbol: import
  excerpt: |
    import pyarrow as pa
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 46-56
  symbol: `StrictTransportError`
  excerpt: |
    class StrictTransportError(Exception):
        Raised **before** any pickle payload is constructed (FEAT-538 §2 "REPL
        Recovery"). Task-memory evidence must never travel as pickle
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 74-80
  symbol: `EncodedDataFrame`
  excerpt: |
    class EncodedDataFrame(NamedTuple):
        format: str  # "arrow" | "pickle"
        payload: Optional[str]  # base64 pickle bytes, format == "pickle" only
- path: `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`
  lines: 83-167
  symbol: `encode_dataframe`
  excerpt: |
    def encode_dataframe(
        with pa.ipc.new_stream(sink, table.schema) as writer:
        return EncodedDataFrame(format="arrow", shm_name=shm.name, size=size, payload=None)
- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/iceberg.py`
  lines: 1
  symbol: (pyarrow user — not read)
- path: `packages/ai-parrot/src/parrot/tools/toolkit.py`
  lines: 1
  symbol: (pyarrow user — not read)
- path: `packages/ai-parrot-tools/src/parrot_tools/powerbi.py`
  lines: 1
  symbol: (pyarrow user — not read)

## Notes

Polars would be a new dependency (FC-002); the WorkingMemory summariser is pandas-only (FC-005). The Arrow IPC encode/decode helpers in transport.py are reusable for S2.
