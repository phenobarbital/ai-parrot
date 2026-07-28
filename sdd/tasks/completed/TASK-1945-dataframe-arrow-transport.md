# TASK-1945: DataFrame transport — Arrow IPC / shared memory (`inject_df`)

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1943
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 / G9 / AC9. DataFrames must cross the host→worker boundary
without an expensive copy: Arrow IPC over shared memory as the primary path,
pickle **only** as a fallback for dtypes Arrow cannot represent — and that
fallback must log a warning (mandatory, not optional). Integrates the
existing sharing surfaces: `ToolManager.share_dataframe()` /
`auto_push_to_pandas` and `PythonPandasTool`'s df seeding from TASK-1944.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py`:
  - Serialize a `pd.DataFrame` to Arrow IPC
    (`pyarrow.Table.from_pandas` → IPC stream) into a
    `multiprocessing.shared_memory.SharedMemory` block; the `inject_df`
    protocol message carries `{name, shm_name, size, format: "arrow"}`.
  - Worker side: open the shm block, read the IPC stream zero-copy where
    dtypes allow, `to_pandas()`, bind into the namespace, close+unlink per
    the shm ownership rule you define (document who unlinks).
  - **Pickle fallback**: on `pyarrow` conversion failure (unsupported dtype),
    fall back to pickle bytes (`format: "pickle"`) and emit
    `logger.warning` naming the DataFrame and the offending dtype (G9 —
    observable slow path).
- Implement `WorkerHandle.inject_dataframe()` (replacing the
  `NotImplementedError` from TASK-1941) and wire
  `PythonREPLTool.inject_dataframe()` / the seeding path from TASK-1944 to
  use it.
- Wire the `inject_df` op in `worker.py`'s dispatch (stubbed
  `not_implemented` since TASK-1940).
- Integrate `ToolManager.share_dataframe()` (`manager.py:1749`) and
  `auto_push_to_pandas` (`:273`): the push into the pandas tool now crosses
  the process via `inject_dataframe`.
- Unit tests: `test_df_arrow_roundtrip` (dtype fidelity),
  `test_df_pickle_fallback_warns`. Integration:
  `test_e2e_data_analysis_session` now includes the `inject_df` leg;
  `test_e2e_concurrent_sessions`.

**NOT in scope**: general (non-DataFrame) `set_var` transport — that stays
as TASK-1943 built it; ToolResult compression (frozen by team decision —
do NOT refactor `manager.py`/`pythonpandas.py` beyond the integration
points).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py` | CREATE | Arrow IPC + shm encode/decode; pickle fallback with warning |
| `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | MODIFY | Real `inject_df` op |
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | `inject_dataframe()` implementation |
| `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | MODIFY | Seed DataFrames via transport |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `share_dataframe`/`auto_push_to_pandas` cross-process push |
| `packages/ai-parrot/tests/repl_worker/test_transport.py` | CREATE | Roundtrip + fallback tests |
| `packages/ai-parrot/tests/repl_worker/test_e2e.py` | CREATE/MODIFY | Full-session + concurrent-session e2e |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-27. Short paths relative to
> `packages/ai-parrot/src/`.

### Verified Imports

```python
import pyarrow as pa                       # present via pandas>=2 dependency chain
from multiprocessing import shared_memory  # stdlib
from parrot.tools.repl_worker.protocol import WorkerConfig  # TASK-1940
```

### Existing Signatures to Use

```python
# parrot/tools/manager.py
# ToolManager._shared = {"dataframes": {}}        # :264
# share_dataframe()                                # :1749-1756
# auto_push_to_pandas                              # :273

# parrot/tools/pythonpandas.py (post-TASK-1944 seeding path)
# df_locals registration :122, merge :128-130, clone :229-236, :292
```

```python
# Warning-on-fallback is MANDATORY (spec §7 Patterns):
# self.logger.warning("DataFrame %r fell back to pickle transport: %s", name, reason)
```

### Does NOT Exist

- ~~A DataFrame wire format in the current protocol~~ — TASK-1940 stubbed
  `inject_df`; this task defines the payload.
- ~~Guaranteed zero-copy for all dtypes~~ — Arrow zero-copy applies only to
  compatible dtypes; object columns will copy. Do not claim otherwise in
  docs/logs.
- ~~ToolResult compression work~~ — frozen as-is by team decision; touch
  `manager.py`/`pythonpandas.py` only at the named integration points.
- ~~`pyarrow` as a new dependency to add~~ — already available via pandas≥2;
  do NOT add it to `pyproject.toml` as a new top-level requirement without
  checking it is not already declared.

---

## Implementation Notes

### Key Constraints

- shm lifecycle is the hard part: define ownership explicitly (recommended:
  host creates + writes + sends name; worker opens + copies/decodes +
  closes; host unlinks after the worker's ack). Leaked shm segments fail
  CI on Linux (`/dev/shm` fills) — test teardown must assert none remain.
- Chunk large frames if a single shm block is impractical; otherwise one
  block per frame is fine for v1 — document the limit.
- Fallback trigger is `pa.Table.from_pandas` raising (e.g.
  `pyarrow.lib.ArrowInvalid` / `ArrowNotImplementedError`) — catch those,
  not blind `Exception`.
- Async host side; the shm write is CPU/memory-bound and may run in the
  tool's dedicated executor (TASK-1939).
- Pydantic for the new protocol payload model (`InjectDFRequest`).

### References in Codebase

- `parrot/tools/repl_worker/protocol.py` — framing to reuse.
- `_serialize_execution_results` precedent (`pythonrepl.py:627`) for
  wire-safety decisions.

---

## Acceptance Criteria

- [ ] `test_df_arrow_roundtrip`: host→worker DataFrame identical (dtypes,
      values, index) via Arrow/shm (AC9).
- [ ] `test_df_pickle_fallback_warns`: non-Arrow dtype → pickle path +
      warning logged (AC9).
- [ ] `share_dataframe()`/`auto_push_to_pandas` deliver frames into the
      worker namespace (visible to executed code by name).
- [ ] No shm leaks after tests (teardown assertion).
- [ ] `test_e2e_data_analysis_session`: inject_df → multi-turn exec → plot →
      snapshot; state persists.
- [ ] `test_e2e_concurrent_sessions`: N sessions under the ceiling work;
      ceiling+1 rejected.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/repl_worker/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/`

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_transport.py
import pandas as pd
import pytest

@pytest.fixture
def sample_df():
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

async def test_df_arrow_roundtrip(sample_df):
    """DataFrame survives host→worker via Arrow/shm with dtype fidelity."""
    ...

async def test_df_pickle_fallback_warns(caplog):
    """DataFrame with a non-Arrow-serializable object column → pickle + warning."""
    ...

# packages/ai-parrot/tests/repl_worker/test_e2e.py
async def test_e2e_data_analysis_session(sample_df): ...
async def test_e2e_concurrent_sessions(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1943 must be in `sdd/tasks/completed/`
   (TASK-1944's seeding path should also be checked; coordinate if pending)
3. **Verify the Codebase Contract** — confirm `manager.py:1749`/`:273`
   anchors and the handle/worker APIs as actually built
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1945-dataframe-arrow-transport.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**:
- `transport.py` (new): `encode_dataframe(df, name) -> EncodedDataFrame`
  (Arrow IPC into a fresh `SharedMemory` block; falls back to pickle+base64
  ONLY on `pa.lib.ArrowInvalid`/`ArrowNotImplementedError`/`ArrowTypeError`,
  always with `logger.warning` naming the DataFrame — G9), plus
  `decode_dataframe_from_shm`/`decode_pickle_payload` (worker side) and
  `unlink_shm` (host side, idempotent). **shm ownership contract** (documented
  in the module docstring): host creates+writes+sends name, worker
  opens+decodes+closes (never unlinks), host unlinks only after receiving the
  worker's ACK (the framed response to `inject_df`) — verified leak-free via
  `/dev/shm` diffing in `test_no_shm_leaks_after_inject`.
- `protocol.py`: `InjectDfRequest` gained explicit `format`/`shm_name`/`size`/
  `payload` fields (replacing the placeholder `handle: Any`) — safe to
  redefine since TASK-1940 stubbed this op with zero real callers.
- `worker.py`: real `inject_df` dispatch — decodes via `transport.py` then
  `namespace.set_var()`. The `from .transport import ...` is a LOCAL import
  inside the dispatch branch (not top-of-file) specifically to keep
  `pyarrow` off the module's import-time surface — `transport.py` pulls in
  pyarrow, and importing it eagerly at `worker.py` load time would happen
  BEFORE `apply_rlimits()` runs in `main()`, breaking the established
  "rlimits before heavy imports" invariant (TASK-1940/1942) that
  `WorkerNamespace`'s own pandas/numpy/matplotlib import already follows.
- `handle.py`: `WorkerHandle.inject_dataframe()` implemented (replacing the
  TASK-1941 `NotImplementedError` stub) — encodes off the event loop
  (`run_in_executor`), sends `InjectDfRequest`, unlinks the shm block in a
  `finally` after the response.
- `pythonrepl.py`: added `PythonREPLTool.inject_dataframe()` (delegates to
  the worker handle) — explicitly named in the task's Scope text though not
  in the file table (see Deviations).
- `pythonpandas.py`: `PythonPandasTool._get_worker_handle()`'s worker-seeding
  (TASK-1944) now routes actual DataFrame values through
  `inject_dataframe()` (Arrow) instead of `set_var()` (always-pickle);
  scalar metadata (`*_row_count`/`*_col_count`/`*_shape`/`*_columns`) stays
  on `set_var()`.
- `manager.py`: `share_dataframe()` needed a real bug fix — see Deviations.
- 18 new tests (`test_transport.py` ×7, `test_e2e.py` ×3 + a
  `share_dataframe` regression, `test_handle.py`'s
  `test_inject_dataframe_not_implemented` rewritten to
  `test_inject_dataframe` since the feature it tested — raising
  `NotImplementedError` — is now implemented). Full suite:
  `pytest packages/ai-parrot/tests/repl_worker/
  packages/ai-parrot/tests/test_pythonrepl_security.py
  packages/ai-parrot/tests/test_pythonrepl_executor.py -q` → **112 passed**;
  verified zero orphaned worker processes (`ps aux`) and zero leaked shm
  segments (`ls /dev/shm/`) after the full run. `ruff check` on every
  modified/created source file matches the established pre-existing
  per-file baselines exactly (manager.py 1, pythonpandas.py 7, pythonrepl.py
  18 — all pre-existing; handle.py/protocol.py/worker.py/transport.py 0).

**Deviations from spec**:
1. **`pythonrepl.py` modified though absent from the Files to
   Create/Modify table** — the task's own Scope text explicitly says "wire
   `PythonREPLTool.inject_dataframe()` ... to use it", which requires the
   method to exist on the tool class. Added as a thin delegate to
   `WorkerHandle.inject_dataframe()`, mirroring `get_var`/`set_var`/
   `list_vars`/`snapshot`'s existing pattern (TASK-1943).
2. **`manager.py`'s `share_dataframe()` had a pre-existing, unrelated bug**
   fixed as part of satisfying this task's own acceptance criterion
   ("share_dataframe()/auto_push_to_pandas deliver frames into the worker
   namespace"): it called `pandas_tool.add_dataframe(safe, df,
   regenerate_guide=True)`, but `add_dataframe(self, name, df)` never
   accepted a `regenerate_guide` kwarg — every call raised `TypeError`,
   silently swallowed by the surrounding `except Exception`, so the
   auto-push into `python_pandas` never actually ran, on `dev` or before
   this task. Fixed by dropping the invalid kwarg. No behavior beyond "the
   call no longer silently no-ops" changed.
3. **No `manager.py` changes were needed for the actual cross-process
   delivery** — `share_dataframe()`/`add_dataframe()` stay fully
   synchronous (as today); the DataFrame reaches the worker lazily,
   transparently, via `PythonPandasTool._get_worker_handle()`'s existing
   diff-based seeding (TASK-1944) the next time that tool's worker is
   acquired — now upgraded to use Arrow transport instead of `set_var()`'s
   always-pickle path. `manager.py` itself only needed the `TypeError` fix
   above to actually reach that seeding path at all.
4. **`WorkerHandle.inject_dataframe()`'s Arrow encode step runs on the
   default executor** (`loop.run_in_executor(None, ...)`), not
   `PythonREPLTool`'s TASK-1939 dedicated `_repl_executor` — threading that
   specific executor through would require a new constructor parameter
   cascading through `WorkerHandle`/`WorkerPool` (mirroring the
   `repl_kwargs` extension from TASK-1943) for a narrow, infrequent
   operation (DataFrame injection, not the hot per-exec path TASK-1939
   targeted). Documented as a minor, deliberate simplification rather than
   silently expanding scope further; a candidate follow-up if profiling
   ever shows this matters.
5. **`test_handle.py`'s `test_inject_dataframe_not_implemented` was
   rewritten** to `test_inject_dataframe` (asserting the real roundtrip
   instead of `NotImplementedError`) — the behavior it tested (TASK-1941's
   stub) no longer exists after this task implements the feature; this is
   the same category of "necessary test update because an earlier task's
   test scaffolding described intentionally-temporary behavior" already
   established in TASK-1943's Completion Note.
