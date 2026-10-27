# TASK-4752: Per-variable snapshot decode survives guard-refused values

**Feature**: FEAT-751 — repl_worker snapshot survives guard-refused values
**Spec**: `sdd/specs/repl-worker-protocol-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:bbef2d4da62a`

---

## Context

`WorkerHandle.snapshot()` decodes the whole `SnapshotResponse.data` mapping in one
dict comprehension. One entry pickled by the worker that references a module outside
`_SAFE_PICKLE_TOP_LEVEL_MODULES` (e.g. an altair `Chart`, the REPL's supported
renderer) makes `_RestrictedUnpickler.find_class()` raise `pickle.UnpicklingError`
and the entire snapshot is lost. Implements spec §3 Module 1.

---

## Scope

- Add `decode_snapshot(data)` to `protocol.py`: decode each entry with
  `decode_value()`; on `pickle.UnpicklingError` substitute the placeholder
  `f"<{name}: refused by insecure-deserialization guard (not transportable)>"`
  and log a WARNING naming the variable.
- Add `import logging` and a module-level `logger` to `protocol.py`.
- Make `WorkerHandle.snapshot()` return `decode_snapshot(response.data)`.
- Write unit tests (`test_protocol.py`) and one real-worker test (`test_handle.py`).

**NOT in scope**: changing `_SAFE_PICKLE_TOP_LEVEL_MODULES`, `_UNSAFE_BUILTINS` or
`_RestrictedUnpickler`; changing `get_var()` (must keep raising); worker-side
filtering; tolerating `ValueError`/`binascii.Error` from Arrow/base64 payloads.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | add `logger` + `decode_snapshot()` |
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | `snapshot()` uses `decode_snapshot()` |
| `packages/ai-parrot/tests/repl_worker/test_protocol.py` | MODIFY | `TestDecodeSnapshot` unit tests |
| `packages/ai-parrot/tests/repl_worker/test_handle.py` | MODIFY | real-worker snapshot test with an altair Chart |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.repl_worker.protocol import decode_value, encode_value  # verified: protocol.py:259,302
from parrot.tools.repl_worker.handle import WorkerHandle  # verified: tests/repl_worker/test_handle.py:18
# protocol.py already imports: base64, io as _io, json, pickle, struct, sys, types (protocol.py:18-29)
# handle.py imports names from .protocol in a parenthesised block (handle.py:37-60) incl. decode_value
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py
_PICKLE_MARKER = "__repl_worker_pickle_b64__"              # line 36
class _RestrictedUnpickler(pickle.Unpickler):               # line 114 — raises pickle.UnpicklingError
def encode_value(value: Any) -> Any:                         # line 259; callable placeholder style at line 294
def decode_value(value: Any) -> Any:                         # line 302

# packages/ai-parrot/src/parrot/tools/repl_worker/handle.py
logger = logging.getLogger(__name__)                         # line 62
class WorkerHandle:
    def __init__(self, config: WorkerConfig, output_dir=..., ...)   # used as WorkerHandle(cfg, output_dir=report_dir)
    async def start(self) -> None
    async def execute(self, code: str, ...) -> str
    async def get_var(self, name: str) -> Any:               # line 1142 — unchanged
    async def snapshot(self) -> dict[str, Any]:              # line 1158
    async def kill(self) -> None

# packages/ai-parrot/tests/repl_worker/test_handle.py
@pytest.fixture def report_dir(tmp_path, monkeypatch)       # line 37 — dir accepted by both path guards
@pytest.fixture def real_worker_config()                     # line 52
class TestNamespaceAPI:                                      # contains test_list_vars_and_snapshot (line 202)
```

### Does NOT Exist
- ~~`parrot.tools.repl_worker.protocol.logger`~~ — no logger in protocol.py yet (this task adds it)
- ~~`decode_snapshot`~~ — does not exist yet (this task creates it)
- ~~`alt` in the REPL namespace~~ — the name is `altair` (pythonrepl.py:372)
- ~~`plt` / `save_current_plot`~~ — removed in TASK-2218

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/repl_worker/handle.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/repl_worker/test_protocol.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/repl_worker/test_handle.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py#decode_value",
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py#_RestrictedUnpickler",
    "sym:packages/ai-parrot/src/parrot/tools/repl_worker/handle.py#WorkerHandle.snapshot"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Catch only `pickle.UnpicklingError`, per entry — never a bare `except`, never `Exception`.
- A refused entry must never be partially decoded or constructed.
- The guard's message (which names the refused `module.name`) is logged only.

### References in Codebase
- `protocol.py:294` — placeholder style `"<…(not transportable)>"` to mirror.
- `test_protocol.py:242` `TestInsecureDeserializationGuard` — how gadget payloads are built.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import logging` and `logger` to `protocol.py` — *why*: the helper must log refused names and protocol.py has no logger.
2. Add `decode_snapshot()` right after `decode_value()` — *why*: keeps the host-side codec in one place, next to the function it wraps.
3. Swap the comprehension in `WorkerHandle.snapshot()` and import `decode_snapshot` — *why*: this is the call site that loses the whole snapshot.
4. Add tests, run Validation Commands, `ruff check` the four files.

### `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^import pickle$' protocol.py)
# AFTER — insert `import logging` in alphabetical order, i.e. above `import pickle`
#         (between `import json` and `import pickle`, protocol.py:22-23)
import logging
```
After the existing `from pydantic import ...` line (protocol.py:29) and before the
first module-level constant, add:
```python
logger = logging.getLogger(__name__)
```

### `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c '^def decode_value(value: Any) -> Any:$' protocol.py)
# AFTER — insert below the END of `def decode_value(value: Any) -> Any:` (protocol.py:302-319)
def decode_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    """Decode a ``SnapshotResponse.data`` mapping one entry at a time.

    One value the insecure-deserialization guard refuses (e.g. an altair
    ``Chart``, whose pickle references a module outside the allowlist) must
    not cost the caller every other variable. Such an entry is replaced by an
    inert placeholder string and a warning is logged; no object is ever
    constructed for it. Any other exception propagates unchanged.

    Args:
        data: The worker's ``{name: encode_value(value)}`` mapping.

    Returns:
        ``{name: decoded value or placeholder}``.
    """
    decoded: dict[str, Any] = {}
    for name, value in data.items():
        try:
            decoded[name] = decode_value(value)
        except pickle.UnpicklingError as exc:
            logger.warning("repl_worker snapshot: variable %r not transportable: %s", name, exc)
            decoded[name] = f"<{name}: refused by insecure-deserialization guard (not transportable)>"
    return decoded
```
**Why this shape**: per-entry try/except is the whole fix (spec §2); the guard itself is untouched (AC-4).

### `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'return {name: decode_value(value) for name, value in response.data.items()}' handle.py)
# REPLACE the line at handle.py:1161 with:
        return decode_snapshot(response.data)
```
Also add `decode_snapshot,` to the `from .protocol import (...)` block, alphabetically
right before `decode_value,` (handle.py:56), and extend the `snapshot()` docstring with
one line: "Guard-refused entries come back as placeholder strings (see protocol.decode_snapshot)."
**Why**: `get_var()` (handle.py:1142) is deliberately NOT changed — AC-5.

### `packages/ai-parrot/tests/repl_worker/test_protocol.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^class TestInsecureDeserializationGuard:' test_protocol.py)
# AFTER — add a new class after TestInsecureDeserializationGuard ends (before `class TestArrowValueCodec:`)
class TestDecodeSnapshot:
    """`decode_snapshot()` degrades guard-refused entries to placeholders (FEAT-751)."""

    def test_refused_entry_becomes_placeholder(self, caplog):
        # FILL IN: build {"greeting": "hi", "n": 3, "bad": <pickle marker of a class defined
        #          in this test module — not on the allowlist>}; assert plain values intact,
        #          data["bad"] == the exact placeholder, and "bad" appears in caplog warnings.
        ...

    def test_reduce_gadget_never_executes(self, tmp_path):
        # FILL IN: Evil.__reduce__ -> (os.system, (f"touch {tmp_path/'pwned'}",)); put it in the
        #          mapping; assert placeholder returned AND the file does not exist.
        ...

    def test_allowlisted_values_round_trip(self):
        # FILL IN: encode a DataFrame, a numpy array and a pathlib.Path with encode_value();
        #          decode_snapshot must equal per-entry decode_value results.
        ...
```
Add `decode_snapshot` to this file's existing `from parrot.tools.repl_worker.protocol import ...`.

### `packages/ai-parrot/tests/repl_worker/test_handle.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_list_vars_and_snapshot(self, real_worker_config, report_dir):' test_handle.py)
# AFTER — add as the next method of TestNamespaceAPI, below test_list_vars_and_snapshot
    async def test_snapshot_survives_unpicklable_value(self, real_worker_config, report_dir):
        """An altair Chart in the namespace no longer costs the whole snapshot (FEAT-751)."""
        handle = WorkerHandle(real_worker_config, output_dir=report_dir)
        await handle.start()
        try:
            await handle.execute("greeting = 'hi'")
            await handle.execute(
                "import pandas as pd\n"
                "chart = altair.Chart(pd.DataFrame({'a': [1, 2]}).reset_index()).mark_line().encode(x='index', y='a')"
            )
            data = await handle.snapshot()
            assert data.get("greeting") == "hi"
            # FILL IN: assert data["chart"] is the exact placeholder string
        finally:
            await handle.kill()
```

### FILL IN checklist
- [ ] `TestDecodeSnapshot` three test bodies — bounded by AC-3/AC-4
- [ ] `test_snapshot_survives_unpicklable_value` placeholder assertion — bounded by AC-2/AC-3

---

## Acceptance Criteria

- [ ] `decode_snapshot()` exists in `protocol.py` with the spec §3 contract.
- [ ] `WorkerHandle.snapshot()` uses it; a namespace holding an altair Chart returns all other variables.
- [ ] Refused entries are the exact placeholder string; a WARNING names the variable.
- [ ] `_SAFE_PICKLE_TOP_LEVEL_MODULES`, `_UNSAFE_BUILTINS`, `_RestrictedUnpickler` unchanged.
- [ ] `get_var()` still raises `pickle.UnpicklingError` for a refused value.
- [ ] Validation Commands pass; `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/repl_worker/test_protocol.py -q`
- `pytest packages/ai-parrot/tests/repl_worker/test_handle.py -q`
- `pytest packages/ai-parrot/tests/repl_worker/test_e2e.py -q`

---

## Test Specification

See the Implementation Blueprint test blocks above.

---

## Agent Instructions

1. Work in the feature worktree:
   `python -m scripts.sdd.ensure_worktree --slug repl-worker-protocol-fixes --feature-id FEAT-751`
2. Read the spec; verify the Codebase Contract; set `in-progress` in the per-spec index.
3. Implement from the blueprint, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the four files; close with `scripts/sdd/close_task.sh TASK-4752 repl-worker-protocol-fixes verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
