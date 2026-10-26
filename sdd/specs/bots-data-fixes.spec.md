---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [repl-worker, pandas-agent, security, bugfix]
---

# Feature Specification: bots-data-fixes — Arrow transport for DataFrames in repl_worker values

**Feature ID**: FEAT-750
**Date**: 2026-10-26
**Author**: Jesus Lara (via /sdd-fix, ledger `issue:e19ac9b4ba42`)
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

With the worker-mode Python REPL (default `execution_mode="worker"`), every
non-streaming `PandasAgent.ask()` whose turn produced a DataFrame with
pyarrow-backed columns crashes after the tool loop:

```
_pickle.UnpicklingError: repl_worker: refusing to unpickle pyarrow.lib._restore_array
(insecure-deserialization guard — module not on the allowlist)
```

Path: `PandasAgent.ask()` → `_infer_data_variable_from_tools()` →
`PythonREPLTool.get_var()` → `WorkerHandle.get_var()` → `protocol.decode_value()`
→ `_safe_pickle_loads()`. `encode_value()` pickles any non-JSON value, and a
pyarrow-backed column pickles through `pyarrow.lib._restore_array`, which the
FEAT-380 restricted unpickler correctly refuses.

The blast radius is larger than "unusual sources": the workspace runs pandas
3.x, whose **default `str` dtype is pyarrow-backed**, so any DataFrame with a
text column hits this. Two existing tests on `dev` already fail with this exact
error: `tests/repl_worker/test_protocol.py::TestValueCodec::test_dataframe_round_trips_via_pickle_fallback`
and `::TestInsecureDeserializationGuard::test_legitimate_dataframe_still_round_trips`.

Ledger: `issue:e19ac9b4ba42` (major, bug, discovered from FEAT-380).

### Goals
- DataFrames and Series (including pyarrow-backed / `ArrowDtype` / pandas-3
  default `str` columns) round-trip through `encode_value()`/`decode_value()`.
- The FEAT-380 insecure-deserialization guard is **not weakened**: the pickle
  allowlist (`_SAFE_PICKLE_TOP_LEVEL_MODULES`) is unchanged; `pyarrow` is NOT
  added to it.
- `_infer_data_variable_from_tools()` never fails a whole turn because one
  candidate variable cannot be fetched; it logs and skips that candidate.

### Non-Goals
- Changing the `inject_df` (host → worker) transport — it already uses Arrow IPC
  over shared memory (`transport.py`).
- Allowlisting individual pyarrow reconstruction callables in the unpickler.
- Fixing the unrelated stale fixture in
  `tests/unit/bots/test_pandasagent_stale_data_variables.py`
  (`SimpleNamespace` lacks `_assignment_target_names`; 3 tests fail on `dev`
  independently of this bug).

---

## 2. Architectural Design

### Overview

Add a second, data-only wire format to the value codec: DataFrames and Series
are encoded as a base64 **Arrow IPC stream** under a new marker key
`__repl_worker_arrow_b64__`. Decoding reads it with `pyarrow.ipc.open_stream()`
and `Table.to_pandas()` — Arrow IPC is a pure data format (pyarrow ≥ 14 does not
unpickle `PyExtensionType` payloads on read; the workspace pins `pyarrow>=25.0`),
so a forged marker from sandboxed code can at worst produce a malformed-data
error, never code execution.

Pickle stays only as the fallback when Arrow cannot represent the frame
(`ArrowInvalid` / `ArrowNotImplementedError` / `ArrowTypeError`, the same tuple
`transport.py` already uses) — e.g. object columns of arbitrary Python
objects. That fallback still goes through the unchanged restricted unpickler.

A Series is transported as a one-column frame plus its name, and restored with
`squeeze`-equivalent column selection so name and dtype survive.

```
worker: encode_value(df) ──Arrow IPC──▶ {"__repl_worker_arrow_b64__": "...", "kind": "dataframe"|"series", ...}
                         └─(Arrow error)─▶ {"__repl_worker_pickle_b64__": "..."}   (unchanged path)
host:   decode_value(...) ──▶ pa.ipc.open_stream(b).read_all().to_pandas()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `protocol.encode_value` / `decode_value` | modifies | used by worker `get_var`/`snapshot`/`set_var` and host `WorkerHandle.get_var`/`set_var`/`snapshot` |
| `PandasAgent._infer_data_variable_from_tools` | modifies | per-candidate error tolerance |
| `transport._ARROW_CONVERSION_ERRORS` | pattern reused | do not import `transport.py` at module top (it imports pyarrow eagerly; protocol.py is imported by lightweight paths) — import pyarrow lazily inside the codec |

### Data Models

Wire shape (JSON object inside the existing frames):

```python
{
    "__repl_worker_arrow_b64__": "<base64 Arrow IPC stream>",
    "kind": "dataframe" | "series",
    # series only: original name is carried in the Arrow schema column name
}
```

### New Public Interfaces
None. `encode_value`/`decode_value` keep their signatures.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Arrow value codec | yes | marker name, wire shape, error tuple, lazy pyarrow import, fallback order fixed above | — |
| M2: tolerant inference | yes | wrap the single `get_var` call at `data.py:2547` | — |

### Module 1: Arrow value codec
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`
- **Responsibility**: encode DataFrame/Series as Arrow IPC; decode the new marker; keep pickle fallback + guard unchanged.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  _ARROW_MARKER = "__repl_worker_arrow_b64__"

  def _encode_arrow(value: Any) -> Optional[dict[str, Any]]:
      """Arrow-IPC-encode a DataFrame/Series; None if Arrow cannot represent it."""

  def _decode_arrow(payload: dict[str, Any]) -> Any:
      """Inverse of _encode_arrow; raises ValueError on a malformed payload/kind."""
  ```
  `decode_value` recognises a dict whose keys are exactly `{_ARROW_MARKER, "kind"}`.

### Module 2: tolerant data-variable inference
- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`
- **Responsibility**: in `_infer_data_variable_from_tools`, a failing `get_var(var)` logs a warning (var name + exception) and skips that candidate.
- **Depends on**: —

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_pyarrow_backed_dataframe_round_trips` | M1 | `string[pyarrow]`, `ArrowDtype(float64)`, datetime, named index survive `decode_value(encode_value(df))` |
| `test_dataframe_uses_arrow_marker` | M1 | encoded DataFrame carries `_ARROW_MARKER`, not the pickle marker |
| `test_series_round_trips` | M1 | named pyarrow-backed Series round-trips (name + dtype) |
| `test_arrow_unrepresentable_falls_back_to_pickle` | M1 | object column of mixed Python objects uses the pickle marker and still decodes |
| `test_forged_arrow_marker_fails_safely` | M1 | garbage base64 / bad `kind` under the arrow marker raises (no execution, no silent success) |
| `test_pickle_allowlist_unchanged` | M1 | `"pyarrow" not in _SAFE_PICKLE_TOP_LEVEL_MODULES` |
| `test_infer_skips_candidate_whose_get_var_raises` | M2 | one candidate raises `UnpicklingError`, the other is a live DataFrame → that one is returned, no exception |

The two pre-existing failing tests in `test_protocol.py` must pass unchanged.

### Validation Contract

tests:
- packages/ai-parrot/tests/repl_worker/test_protocol.py
- packages/ai-parrot/tests/repl_worker/test_worker.py
- packages/ai-parrot/tests/repl_worker/test_handle.py
- packages/ai-parrot/tests/tools/working_memory/task_memory/test_strict_worker_transport.py
- packages/ai-parrot/tests/unit/bots/test_pandasagent_infer_tolerant.py
markers: none

---

## 5. Acceptance Criteria

- [ ] `decode_value(encode_value(df))` equals `df` for pyarrow-backed DataFrames and Series.
- [ ] `_SAFE_PICKLE_TOP_LEVEL_MODULES` and `_UNSAFE_BUILTINS` are byte-for-byte unchanged.
- [ ] Every existing `TestInsecureDeserializationGuard` test passes.
- [ ] `_infer_data_variable_from_tools` returns the surviving candidate when another candidate's `get_var` raises.
- [ ] `ruff check` clean on changed files.

---

## 6. Codebase Contract

Verified against: `8baa2ccf2` (origin/dev).

### Verified Imports
```python
from parrot.tools.repl_worker.protocol import encode_value, decode_value  # protocol.py:142,182
import pyarrow as pa  # dependency: packages/ai-parrot/pyproject.toml:180 "pyarrow>=25.0"
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py
_PICKLE_MARKER = "__repl_worker_pickle_b64__"            # line 35
_SAFE_PICKLE_TOP_LEVEL_MODULES = frozenset({...})         # line 68
class _RestrictedUnpickler(pickle.Unpickler): ...         # line 105
def _safe_pickle_loads(data: bytes) -> Any:               # line 126
def encode_value(value: Any) -> Any:                      # line 142
def decode_value(value: Any) -> Any:                      # line 182

# packages/ai-parrot/src/parrot/tools/repl_worker/transport.py
_ARROW_CONVERSION_ERRORS = (pa.lib.ArrowInvalid, pa.lib.ArrowNotImplementedError, pa.lib.ArrowTypeError)  # line 43

# packages/ai-parrot/src/parrot/bots/data.py
async def _infer_data_variable_from_tools(self, tool_calls: List[Any], prefer_names: tuple = ()) -> Optional[str]:  # line 2504
self._current_turn_variable_names(tool_calls)  # called inside, returns set
self._get_python_pandas_tool()                 # called inside
```

### Does NOT Exist
- ~~`protocol._ARROW_MARKER`~~ — added by this feature.
- ~~an Arrow path in `encode_value`~~ — today it is JSON-or-pickle only.

### Edit Sites (Blueprint Anchors)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | `_PICKLE_MARKER = "__repl_worker_pickle_b64__"` | `protocol.py:35` | 1 |
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | `def encode_value(value: Any) -> Any:` | `protocol.py:142` | 1 |
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | `def decode_value(value: Any) -> Any:` | `protocol.py:182` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `            value = await pandas_tool.get_var(var)` | `data.py:2547` | 1 |
| `packages/ai-parrot/tests/repl_worker/test_protocol.py` | MODIFY | `class TestInsecureDeserializationGuard:` | — | 1 |
| `packages/ai-parrot/tests/unit/bots/test_pandasagent_infer_tolerant.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

- Import pyarrow lazily inside `_encode_arrow`/`_decode_arrow` (protocol.py is
  imported on lightweight paths; `transport.py` documents the same concern).
- The Arrow check must run **before** the generic `json.dumps` probe and before
  the `callable(value)` check is irrelevant for frames (DataFrames are not callable).
- `pa.Table.from_pandas(df)` keeps the pandas metadata (index, extension dtypes)
  so `to_pandas()` restores them; do not pass `preserve_index=False`.
- Decoding must reject a payload whose `kind` is not `"dataframe"`/`"series"`
  with `ValueError`; it must never fall through to pickle.
- Do not catch blind `Exception` in the codec; use the Arrow error tuple. In
  `_infer_data_variable_from_tools` a broad `except Exception` with a warning is
  acceptable: inference is best-effort and must not fail a turn.

### Known Risks
- Forged arrow marker from sandboxed code: Arrow IPC is data-only on pyarrow ≥ 14
  (CVE-2023-47248 fix); workspace pins ≥ 25. Mitigation: kind whitelist + test.
- Non-string column labels / MultiIndex columns: `from_pandas` may raise; falls
  back to pickle (same as today's behaviour for those frames).

---

## 8. Open Questions

None.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-26 | Claude (/sdd-fix) | Initial spec from ledger issue e19ac9b4ba42 |
