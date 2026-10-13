# TASK-4271: LSP Session Fix Tests

**Feature**: FEAT-657 — LSP Session Fixes
**Spec**: `sdd/specs/lsp-session-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4270
**Assigned-to**: unassigned

---

## Context

This task adds tests for the four source-code fixes applied in TASK-4270.
All tests use the existing `fake_server.py` test infrastructure from FEAT-580
M2, which provides a scriptable subprocess over real pipes.

---

## Scope

- Add a test that `_handshake` raises `LSPFailure("server_version_mismatch")`
  when the server reports a different `serverInfo.version`.
- Add a test that `_handshake` logs a warning (does not raise) when
  `serverInfo` is absent from the initialize response.
- Add a test that a crashed reader loop wakes a blocked `diagnostics()`
  caller immediately (no timeout wait).
- Add a test that verifies `_DEFAULT_SHUTDOWN_TIMEOUT_S` etc. are 2.0.
- Add a test that `_spawn_process` creates the subprocess with
  `start_new_session=True`.

**NOT in scope**: source-code changes (TASK-4270), toolkit changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py` | MODIFY | Add test cases for the 4 fixes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.lsp.models import LSPConfig, LSPFailure  # verified: test_session_lifecycle.py:16
from parrot_tools.lsp.session import PyrightSession  # verified: test_session_lifecycle.py:18
from parrot_tools.lsp.session import (
    _DEFAULT_SHUTDOWN_TIMEOUT_S,
    _DEFAULT_TERMINATE_TIMEOUT_S,
    _DEFAULT_KILL_TIMEOUT_S,
)  # public module-level constants, verified: session.py:75-77
```

### Existing Signatures to Use
```python
# test_session_lifecycle.py:20
FAKE_SERVER = Path(__file__).parent / "fake_server.py"

# test_session_lifecycle.py:23
_TIMEOUT_S = 2.0

# test_session_lifecycle.py:25
_VERSION_OK_COMMAND = [sys.executable, "-c", "print('pyright 1.1.414')"]
```

### Does NOT Exist
- ~~`test_session_lifecycle.py::TestServerInfoVersion`~~ — no such class yet
- ~~`test_session_lifecycle.py::TestCrashWakesDiagnostics`~~ — no such class yet
- ~~`fake_server.py` serverInfo configuration~~ — the fake server's initialize response shape needs to be checked

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/lsp/session.py#PyrightSession._handshake",
    "sym:packages/ai-parrot-tools/src/parrot_tools/lsp/session.py#PyrightSession._reader_loop"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Tests must use `fake_server.py` (scripted subprocess), not mocks.
- The fake server's initialize response must be modified or a new script
  variant created to control `serverInfo.version` in the response.
- The crash-wakes-diagnostics test needs to verify that `diagnostics()` returns
  quickly (well under timeout) after the reader loop crashes.

### References in Codebase
- `packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py` — existing test patterns
- `packages/ai-parrot-tools/tests/lsp/fake_server.py` — scriptable LSP subprocess

---

## Implementation Blueprint

### Steps (in order)
1. Read `fake_server.py` to understand how to control `serverInfo` in the
   initialize response — *why*: tests need a server that reports wrong/absent
   `serverInfo.version`.
2. Add `TestDefaultTimeouts` class — *why*: trivial constant check (AC-4).
3. Add `TestServerInfoVersionCheck` class with two tests (mismatch raises,
   absent warns) — *why*: AC-1/AC-2.
4. Add `TestCrashWakesDiagnostics` test — *why*: AC-3.
5. Add `TestProcessGroupSignaling` test verifying `start_new_session=True` —
   *why*: AC-6.

### `packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py` (MODIFY)

```python
# AFTER — append at end of file

class TestDefaultTimeouts:
    """Verify spec-pinned 2s shutdown timeouts (AC-4)."""

    def test_default_timeouts_are_2s(self) -> None:
        assert _DEFAULT_SHUTDOWN_TIMEOUT_S == 2.0
        assert _DEFAULT_TERMINATE_TIMEOUT_S == 2.0
        assert _DEFAULT_KILL_TIMEOUT_S == 2.0


# FILL IN: TestServerInfoVersionCheck — needs fake_server.py understanding
# to create a variant that reports wrong serverInfo.version.
# Bounded by AC-1 (raises on mismatch) and AC-2 (warns when absent).

# FILL IN: TestCrashWakesDiagnostics — needs to start a session, open a
# document, then crash the fake server mid-diagnostics wait and assert
# the diagnostics() call returns quickly. Bounded by AC-3.

# FILL IN: TestProcessGroupSignaling — needs to verify start_new_session=True
# is passed by checking the spawned process is a session leader (os.getsid).
# Bounded by AC-6.
```

### FILL IN checklist
- [ ] `TestServerInfoVersionCheck` — how to inject wrong `serverInfo.version` in fake_server.py; bounded by AC-1/AC-2
- [ ] `TestCrashWakesDiagnostics` — crash timing and assertion threshold; bounded by AC-3
- [ ] `TestProcessGroupSignaling` — verify `start_new_session=True` effect; bounded by AC-6

---

## Acceptance Criteria

- [ ] Test for `serverInfo.version` mismatch raises `LSPFailure` (AC-1)
- [ ] Test for absent `serverInfo` logs warning, does not raise (AC-2)
- [ ] Test for crash waking `diagnostics()` callers fast (AC-3)
- [ ] Test for default timeouts == 2.0 (AC-4)
- [ ] Test for `start_new_session=True` (AC-6)
- [ ] All existing LSP session tests still pass
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py`

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py -q`

---

## Test Specification

See Implementation Blueprint above — tests are the primary deliverable.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
2. **Read TASK-4270's changes** first — the source fixes must already be in place
3. **Read `fake_server.py`** to understand how to script server responses
4. **Verify the Codebase Contract** — confirm test imports and patterns
5. **Implement** the tests per the blueprint
6. **Run** `pytest packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py -q`
7. **Commit** — stage only the test file
8. **Close the task** with `scripts/sdd/close_task.sh TASK-4271 lsp-session-fixes verified`

---

## Completion Note

Added tests for all four fixes. `test_session_lifecycle.py`: 26 pass; rest of `tests/lsp`: 142 pass, 3 skipped.

**Completed by**: Claude (sdd-start)
**Date**: 2026-10-14
**Notes**: `test_bedrock_mantle_seat.py` fails collection (`parrot.interfaces.file.session` import) — pre-existing environment issue, unrelated; excluded from the run. The process-group test asserts the server is its own session leader via `os.getsid`.

**Deviations from spec**: `fake_server.py` also modified (not listed in Files) — added scenarios `server_info_mismatch` and `crash_after_handshake`, since the fixture could not otherwise emit `serverInfo` or crash after the handshake.
