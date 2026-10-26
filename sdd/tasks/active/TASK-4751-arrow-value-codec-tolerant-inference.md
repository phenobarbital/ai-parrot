# TASK-4751: Arrow value codec for repl_worker + tolerant data-variable inference

**Feature**: FEAT-750 — bots-data-fixes (Arrow transport for DataFrames in repl_worker values)
**Spec**: `sdd/specs/bots-data-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:e19ac9b4ba42`

---

## Context

Ledger `issue:e19ac9b4ba42` (major): in worker mode, `PandasAgent.ask()` crashes with
`UnpicklingError: refusing to unpickle pyarrow.lib._restore_array` because
`protocol.encode_value()` pickles DataFrames and pyarrow-backed columns pickle through
`pyarrow.lib`, which the FEAT-380 restricted unpickler correctly refuses. Under pandas 3.x
the default `str` dtype is pyarrow-backed, so any DataFrame with a text column fails.
Two existing tests in `tests/repl_worker/test_protocol.py` already fail on `dev` for this reason.

Implements spec Module 1 (Arrow value codec) and Module 2 (tolerant inference).

## Scope

- Add an Arrow IPC wire format for `pd.DataFrame` / `pd.Series` to `encode_value`/`decode_value`.
- Keep pickle as fallback only when Arrow conversion raises one of the Arrow conversion errors.
- In `PandasAgent._infer_data_variable_from_tools`, catch an exception from one candidate's
  `get_var`, log a warning, skip it.
- Tests for both.

**NOT in scope**: changing `_SAFE_PICKLE_TOP_LEVEL_MODULES` / `_UNSAFE_BUILTINS`; the
`inject_df` transport (`transport.py`); other `get_var` call sites in `data.py`; the stale
fixture in `tests/unit/bots/test_pandasagent_stale_data_variables.py`.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | Arrow marker + `_encode_arrow`/`_decode_arrow`, wired into codec |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | per-candidate try/except around `get_var` |
| `packages/ai-parrot/tests/repl_worker/test_protocol.py` | MODIFY | new `TestArrowValueCodec` class |
| `packages/ai-parrot/tests/unit/bots/test_pandasagent_infer_tolerant.py` | CREATE | tolerant-inference test |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.repl_worker.protocol import encode_value, decode_value  # protocol.py:142,182
from parrot.tools.repl_worker.protocol import _SAFE_PICKLE_TOP_LEVEL_MODULES  # protocol.py:68
from parrot.bots.data import PandasAgent  # data.py (class defines _infer_data_variable_from_tools at :2504)
import pyarrow as pa  # pyproject: "pyarrow>=25.0" (packages/ai-parrot/pyproject.toml:180)
import pandas as pd
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py
_PICKLE_MARKER = "__repl_worker_pickle_b64__"           # :35
def _safe_pickle_loads(data: bytes) -> Any:              # :126
def encode_value(value: Any) -> Any:                     # :142
    if value is None or isinstance(value, (bool, int, float, str)):   # :156  (first branch)
def decode_value(value: Any) -> Any:                     # :182
    if isinstance(value, dict) and set(value) == {_PICKLE_MARKER}:    # :191  (first branch)
# module already imports: base64, io as _io, json, pickle, struct, types, Any, Optional

# packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:43 (pattern only — do NOT import transport.py)
_ARROW_CONVERSION_ERRORS = (pa.lib.ArrowInvalid, pa.lib.ArrowNotImplementedError, pa.lib.ArrowTypeError)

# packages/ai-parrot/src/parrot/bots/data.py
async def _infer_data_variable_from_tools(self, tool_calls: List[Any], prefer_names: tuple = ()) -> Optional[str]:  # :2504
#   uses self._get_python_pandas_tool(), self._current_turn_variable_names(tool_calls), self.logger
        for var in candidates:
            value = await pandas_tool.get_var(var)            # :2547
            if isinstance(value, pd.DataFrame) and not value.empty:
                candidate_values[var] = value
```

### Does NOT Exist
- ~~`protocol._ARROW_MARKER`, `_encode_arrow`, `_decode_arrow`~~ — created by this task.
- ~~`protocol.logger`~~ — protocol.py has no module logger; do not add logging there.
- ~~a `pyarrow` entry in `_SAFE_PICKLE_TOP_LEVEL_MODULES`~~ — must stay absent.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/data.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/repl_worker/test_protocol.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/bots/test_pandasagent_infer_tolerant.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py#encode_value",
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py#decode_value",
    "sym:packages/ai-parrot/src/parrot/bots/data.py#PandasAgent._infer_data_variable_from_tools"
  ]
}
```

## Implementation Notes

### Key Constraints
- Import `pyarrow`/`pandas` lazily inside the helpers — protocol.py is imported on light paths.
- `pa.Table.from_pandas(df)` with default `preserve_index` — keeps index + extension dtypes in metadata.
- Never fall through from a malformed arrow payload to pickle; raise `ValueError`.
- Do not touch the pickle guard constants.

## Implementation Blueprint

### Steps (in order)
1. Add `_ARROW_MARKER` below `_PICKLE_MARKER` — distinct key so the decoder can never confuse the two formats.
2. Add `_encode_arrow` / `_decode_arrow` after `_safe_pickle_loads` — keep codec helpers together.
3. In `encode_value`, try `_encode_arrow` right after the JSON-scalar branch — frames must never reach the pickle branch when Arrow can carry them.
4. In `decode_value`, recognise the arrow marker before the pickle marker.
5. Wrap the `get_var` at data.py:2547 in try/except — inference is best-effort.
6. Write tests; run Validation Commands; `ruff check --fix` changed files.

### `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_PICKLE_MARKER = "__repl_worker_pickle_b64__"' protocol.py)
# AFTER — insert below `_PICKLE_MARKER = "__repl_worker_pickle_b64__"` (verified: protocol.py:35)
#: Sentinel key for a DataFrame/Series carried as a base64 Arrow IPC stream (FEAT-750).
_ARROW_MARKER = "__repl_worker_arrow_b64__"
_ARROW_KINDS = frozenset({"dataframe", "series"})
```
```python
# occurrences: 1 — AFTER the body of `def _safe_pickle_loads(data: bytes) -> Any:` (protocol.py:126)
def _encode_arrow(value: Any) -> Optional[dict[str, Any]]:
    """Encode a DataFrame/Series as a base64 Arrow IPC stream. None if not a frame or Arrow can't carry it."""
    # FILL IN: lazy `import pandas as pd, pyarrow as pa`; return None unless DataFrame/Series;
    # Series -> value.to_frame() (name "0"-safe via str()); Table.from_pandas; ipc.new_stream;
    # catch only (ArrowInvalid, ArrowNotImplementedError, ArrowTypeError) -> None. Bounded by spec §7.


def _decode_arrow(payload: dict[str, Any]) -> Any:
    """Inverse of `_encode_arrow`. Raises ValueError on an unknown kind."""
    # FILL IN: validate kind in _ARROW_KINDS (ValueError otherwise); ipc.open_stream(...).read_all().to_pandas();
    # series -> first column. Never call pickle here.
```
```python
# in encode_value, after the `if value is None or isinstance(...)` branch (protocol.py:156):
    arrow_payload = _encode_arrow(value)
    if arrow_payload is not None:
        return arrow_payload
# in decode_value, before `if isinstance(value, dict) and set(value) == {_PICKLE_MARKER}:` (protocol.py:191):
    if isinstance(value, dict) and set(value) == {_ARROW_MARKER, "kind"}:
        return _decode_arrow(value)
```
**Why**: Arrow IPC is data-only, so DataFrames cross the boundary without touching the unpickler; the guard stays as strict as FEAT-380 made it.

### `packages/ai-parrot/src/parrot/bots/data.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            value = await pandas_tool.get_var(var)' data.py) — data.py:2547
            try:
                value = await pandas_tool.get_var(var)
            except Exception as exc:  # best-effort inference must never fail the turn
                self.logger.warning("Skipping data_variable candidate %r: get_var failed: %s", var, exc)
                continue
```
**Why**: one unfetchable candidate (any decode error) must not discard the answer already computed.

### FILL IN checklist
- [ ] `_encode_arrow` body
- [ ] `_decode_arrow` body
- [ ] tests in both files

## Acceptance Criteria
- [ ] pyarrow-backed DataFrame/Series round-trip through `decode_value(encode_value(x))`.
- [ ] `_SAFE_PICKLE_TOP_LEVEL_MODULES` / `_UNSAFE_BUILTINS` unchanged.
- [ ] All tests in `test_protocol.py` pass, including the two that fail on `dev` today.
- [ ] Inference returns the surviving candidate when another candidate's `get_var` raises.
- [ ] `ruff check` clean on changed files.

## Validation Commands
- `pytest packages/ai-parrot/tests/repl_worker/test_protocol.py -q`
- `pytest packages/ai-parrot/tests/repl_worker/test_worker.py -q`
- `pytest packages/ai-parrot/tests/unit/bots/test_pandasagent_infer_tolerant.py -q`

## Test Specification
`TestArrowValueCodec` in test_protocol.py: `test_pyarrow_backed_dataframe_round_trips`,
`test_dataframe_uses_arrow_marker`, `test_series_round_trips`,
`test_arrow_unrepresentable_falls_back_to_pickle`, `test_forged_arrow_marker_fails_safely`,
`test_pickle_allowlist_unchanged`. New file: `test_infer_skips_candidate_whose_get_var_raises`.

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug bots-data-fixes --feature-id FEAT-750`).
2. Verify the Codebase Contract, set the index status to `in-progress`, implement the blueprint, run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4751 bots-data-fixes verified`; fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
