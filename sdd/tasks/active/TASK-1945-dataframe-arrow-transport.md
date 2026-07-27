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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
