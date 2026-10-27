---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [repl-worker, security]
---

# Feature Specification: repl_worker snapshot survives guard-refused values

**Feature ID**: FEAT-751
**Date**: 2026-10-27
**Author**: Jesus Lara (via /sdd-fix, Claude)
**Status**: approved
**Target version**: next dev release

Source: ledger `issue:bbef2d4da62a` (minor bug), fix group `fixgroup:6d5aa622bafe`,
discovered while fixing `issue:d49f93c8ac02` (PR #1820).

---

## 1. Motivation & Business Requirements

### Problem Statement
`WorkerHandle.snapshot()` decodes every namespace entry in a single dict
comprehension through `decode_value()`. When the worker had to pickle one value
(anything that is not JSON-native, Arrow-encodable or callable) and that pickle
references a module outside `_SAFE_PICKLE_TOP_LEVEL_MODULES`,
`_RestrictedUnpickler.find_class()` raises `pickle.UnpicklingError` and the
**whole** snapshot is lost — not just the one variable.

Repro (real worker): `chart = altair.Chart(df).mark_line().encode(x='index', y='a')`,
then `await handle.snapshot()` →
`UnpicklingError: repl_worker: refusing to unpickle altair.vegalite.v5.api.Chart
(insecure-deserialization guard — module not on the allowlist)`.
altair is the REPL's supported renderer (matplotlib was removed in TASK-2218), so
any agent session that binds a chart to a variable loses `snapshot()` entirely.
`PythonREPLTool`'s locals snapshot path goes through the same call.

### Goals
- `snapshot()` returns every decodable variable even when some entries are refused
  by the insecure-deserialization guard.
- A refused entry is replaced by an inert placeholder string (same style as
  `encode_value()`'s `"<…(not transportable)>"` placeholder for callables) and a
  warning naming the variable is logged.
- The guard, its allowlist and `_UNSAFE_BUILTINS` are unchanged; a refused payload
  never constructs an object and a `__reduce__` gadget never executes.

### Non-Goals (explicitly out of scope)
- Widening `_SAFE_PICKLE_TOP_LEVEL_MODULES` (e.g. adding `altair`) — that would
  weaken a security boundary that runs on attacker-shaped data in the host.
- Changing `get_var()`: a single, explicitly requested variable that cannot be
  decoded should keep failing loudly.
- Worker-side filtering of non-allowlisted values: the host must be robust
  regardless of what the (untrusted) worker sends, so the fix lives host-side.
- Tolerating other decode errors (malformed Arrow/base64 payloads) — see §8.

---

## 2. Architectural Design

### Overview
Add a host-side helper `decode_snapshot()` to `protocol.py`, next to
`decode_value()`. It decodes each entry of a `SnapshotResponse.data` mapping
independently. For an entry whose decode raises `pickle.UnpicklingError`, it
logs a warning and substitutes the placeholder
`"<{name}: refused by insecure-deserialization guard (not transportable)>"`.
`WorkerHandle.snapshot()` calls `decode_snapshot(response.data)` instead of its
inline comprehension. Nothing else in the codec changes.

### Component Diagram
```
worker: _dispatch(SnapshotRequest) ── encode_value() per var ──▶ SnapshotResponse.data
host:   WorkerHandle.snapshot() ── decode_snapshot(data) ──▶ decode_value() per var
                                         └── UnpicklingError ─▶ placeholder + logger.warning
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `protocol.decode_value()` | uses | called once per entry, unchanged |
| `protocol._RestrictedUnpickler` | relies on | its `UnpicklingError` is the only error caught |
| `WorkerHandle.snapshot()` | modifies | one-line swap to `decode_snapshot()` |

### Data Models
No new models. `SnapshotResponse` is unchanged.

### New Public Interfaces
```python
def decode_snapshot(data: dict[str, Any]) -> dict[str, Any]: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: per-variable snapshot decode | yes | signature, caught exception, placeholder text and call site fixed below | — |

### Module 1: Per-variable snapshot decode
- **Path**: `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py`,
  `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py`
- **Responsibility**: decode a snapshot mapping entry by entry, replacing
  guard-refused entries with an inert placeholder; wire it into `WorkerHandle.snapshot()`.
- **Depends on**: existing `decode_value()` / `_RestrictedUnpickler`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py (modifies; new func after decode_value, protocol.py:302)
  import logging  # new module import
  logger = logging.getLogger(__name__)  # new module-level logger

  def decode_snapshot(data: dict[str, Any]) -> dict[str, Any]:
      """Decode a SnapshotResponse.data mapping one entry at a time.

      Entries whose decode raises pickle.UnpicklingError (the
      insecure-deserialization guard) become the placeholder
      "<{name}: refused by insecure-deserialization guard (not transportable)>"
      and a warning naming the variable is logged. No object is constructed for
      a refused entry. Every other entry is decode_value(entry). Other exceptions
      propagate unchanged.
      """

  # packages/ai-parrot/src/parrot/tools/repl_worker/handle.py (modifies handle.py:1158-1161)
  async def snapshot(self) -> dict[str, Any]:  # verified: handle.py:1158
      """Return a serializable dump of the whole worker namespace.

      Guard-refused entries are placeholders (see protocol.decode_snapshot).
      """
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `TestDecodeSnapshot::test_refused_entry_becomes_placeholder` | M1 | mapping with plain values + one pickle payload of a non-allowlisted class → plain values intact, refused one equals the placeholder |
| `TestDecodeSnapshot::test_reduce_gadget_never_executes` | M1 | an `os.system`-style `__reduce__` payload inside the mapping becomes a placeholder; side effect (e.g. touching a file) never happens |
| `TestDecodeSnapshot::test_allowlisted_values_round_trip` | M1 | DataFrame / numpy / pathlib entries decode exactly as `decode_value` does |

### Integration Tests
| Test | Description |
|---|---|
| `test_handle.py::TestNamespaceAPI::test_snapshot_survives_unpicklable_value` (real worker) | bind `greeting = 'hi'` and an altair Chart, `snapshot()` returns `greeting == 'hi'` and a placeholder string for the chart |

### Validation Contract

tests:
- packages/ai-parrot/tests/repl_worker/test_protocol.py
- packages/ai-parrot/tests/repl_worker/test_handle.py
- packages/ai-parrot/tests/repl_worker/test_e2e.py
markers: none

### Test Data / Fixtures
Reuse `real_worker_config` and `report_dir` from `test_handle.py`; the unit tests
build payloads with `base64.b64encode(pickle.dumps(obj))` like
`TestInsecureDeserializationGuard` does.

---

## 5. Acceptance Criteria

- [ ] `decode_snapshot()` exists in `protocol.py` with the §3 contract.
- [ ] `WorkerHandle.snapshot()` uses it; a namespace holding an altair Chart returns all other variables.
- [ ] Refused entries are the exact placeholder string and a warning is logged with the variable name.
- [ ] `_SAFE_PICKLE_TOP_LEVEL_MODULES`, `_UNSAFE_BUILTINS` and `_RestrictedUnpickler` are byte-identical to the base commit.
- [ ] `get_var()` still raises `pickle.UnpicklingError` for a refused value.
- [ ] New and existing tests in `test_protocol.py`, `test_handle.py`, `test_e2e.py` pass; `ruff check` clean on changed files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.tools.repl_worker.protocol import decode_value, encode_value  # verified: protocol.py:259,302
from parrot.tools.repl_worker.handle import WorkerHandle                  # verified: tests/repl_worker/test_handle.py:18
```
`protocol.py` imports today (lines 18-29): `base64`, `io as _io`, `json`, `pickle`,
`struct`, `sys`, `types`, `typing.Any/BinaryIO/Literal/Optional`, pydantic. It has
**no** `logging` import and no `logger` yet. `handle.py` imports `decode_value`
from `.protocol` (handle.py:37-60) and has `logger = logging.getLogger(__name__)` at handle.py:62.

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py
_PICKLE_MARKER = "__repl_worker_pickle_b64__"                 # line 36
class _RestrictedUnpickler(pickle.Unpickler):                  # line 114
    def find_class(self, module: str, name: str) -> Any:       # raises pickle.UnpicklingError
def _safe_pickle_loads(data: bytes) -> Any:                     # line 135
def encode_value(value: Any) -> Any:                            # line 259
def decode_value(value: Any) -> Any:                            # line 302
class SnapshotResponse(BaseModel):                              # data: dict[str, Any]

# packages/ai-parrot/src/parrot/tools/repl_worker/handle.py
class WorkerHandle:
    async def get_var(self, name: str) -> Any:                  # line 1142
    async def snapshot(self) -> dict[str, Any]:                 # line 1158
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `decode_snapshot` | `decode_value()` | per-entry call | `protocol.py:302` |
| `WorkerHandle.snapshot` | `decode_snapshot()` | replaces inline comprehension | `handle.py:1161` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.tools.repl_worker.protocol.logger`~~ — no logger in protocol.py yet (M1 adds it)
- ~~`decode_snapshot`~~ — does not exist yet (M1 creates it)
- ~~`save_current_plot`, `plt` in the REPL namespace~~ — removed in TASK-2218

### Edit Sites (Blueprint Anchors)

Verified against: 4a8a52c35

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | `def decode_value(value: Any) -> Any:` | `protocol.py:302` | 1 |
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | MODIFY | `import pickle` | `protocol.py:23` | 1 |
| `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py` | MODIFY | `return {name: decode_value(value) for name, value in response.data.items()}` | `handle.py:1161` | 1 |
| `packages/ai-parrot/tests/repl_worker/test_protocol.py` | MODIFY | `class TestInsecureDeserializationGuard:` | `test_protocol.py:242` | 1 |
| `packages/ai-parrot/tests/repl_worker/test_handle.py` | MODIFY | `async def test_list_vars_and_snapshot(self, real_worker_config, report_dir):` | `test_handle.py:202` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Placeholder style mirrors `encode_value()`'s callable placeholder (protocol.py:294).
- Catch only `pickle.UnpicklingError`, per entry; never a bare `except`.
- Module-level `logger = logging.getLogger(__name__)`; log the variable name and the
  guard's message at WARNING.

### Known Risks / Gotchas
- A container entry (dict/list) holding one refused value becomes a single
  placeholder for the whole entry — acceptable, the entry is not partially decoded.
- The guard message includes the refused `module.name`, taken from worker-shaped
  data; it is only logged and embedded as text, never resolved.
- Real-worker tests are load-sensitive (seen in `test_memory_guardrails`,
  `test_integration`); rerun a single failure alone before treating it as a regression.

### External Dependencies
None (altair 5.5 is already installed and used only in the integration test).

---

## 8. Open Questions

- [ ] Should malformed Arrow / base64 payloads (`ValueError`, `binascii.Error`) in a
  snapshot also degrade to a placeholder instead of failing the snapshot? Out of
  scope here; worth a follow-up ledger issue if seen. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

Status: skipped (no exploration document — spec authored from ledger issue via /sdd-fix)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- Isolation: one feature worktree `feat-FEAT-751-repl-worker-protocol-fixes`.
- Module dependency graph: single module M1, no edges.
- Shared files: none beyond M1's own.
- Exclusive resources: none.
- Cross-feature dependencies: none (PRs #1819 and #1820 are already merged on dev).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-27 | Jesus Lara (Claude) | Initial draft from ledger issue:bbef2d4da62a |
