# TASK-4270: LSP Session Source Fixes

**Feature**: FEAT-657 — LSP Session Fixes
**Spec**: `sdd/specs/lsp-session-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements the four source-code fixes in `PyrightSession` identified
by ledger issues from TASK-3502 code review. All changes are in a single file
(`session.py`) plus its `_spawn_process` subprocess creation call.

---

## Scope

- Fix 1: Add `serverInfo.version` cross-check in `_handshake` after the
  initialize response.
- Fix 2: Set `_notification_event` in `_reader_loop` when it exits on crash,
  so blocked `diagnostics()` callers wake immediately.
- Fix 3: Change `_DEFAULT_SHUTDOWN_TIMEOUT_S`, `_DEFAULT_TERMINATE_TIMEOUT_S`,
  `_DEFAULT_KILL_TIMEOUT_S` from 5.0 to 2.0.
- Fix 4: Spawn the subprocess with `start_new_session=True` and use
  `os.killpg` in `_terminate_process` for process-group signaling (POSIX
  only, fall back to per-PID on other platforms).

**NOT in scope**: test additions (TASK-4271), toolkit changes, protocol changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py` | MODIFY | All 4 fixes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.lsp.models import LSPConfig, LSPFailure  # verified: session.py:40
from parrot_tools.lsp.protocol import ParsedMessage  # verified: session.py:41
import os  # verified: session.py:31
import signal  # NOT currently imported — must add
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/lsp/session.py:75-77
_DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0
_DEFAULT_TERMINATE_TIMEOUT_S = 5.0
_DEFAULT_KILL_TIMEOUT_S = 5.0

# session.py:434
async def _handshake(self, config: LSPConfig) -> None:

# session.py:458
self._server_capabilities = response.result.get("capabilities") if isinstance(response.result, dict) else None

# session.py:537
async def _reader_loop(self) -> None:

# session.py:543-546
except LSPFailure as exc:
    self._crashed = True
    self._fail_all_pending(exc)
    return

# session.py:409
async def _spawn_process(self, config: LSPConfig) -> None:

# session.py:416-423
self._process = await asyncio.create_subprocess_exec(
    *config.server_command,
    cwd=str(config.repo_root),
    env=env,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)

# session.py:937
async def _terminate_process(self) -> None:

# session.py:942-943
with contextlib.suppress(ProcessLookupError):
    proc.terminate()

# session.py:949-950
with contextlib.suppress(ProcessLookupError):
    proc.kill()

# models.py:139
expected_server_version: str = "1.1.414"
```

### Does NOT Exist
- ~~`PyrightSession._server_version`~~ — no stored version attribute exists
- ~~`PyrightSession.process_group`~~ — no such attribute
- ~~`LSPConfig.use_process_group`~~ — no such config option

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/lsp/session.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/lsp/session.py#PyrightSession._handshake",
    "sym:packages/ai-parrot-tools/src/parrot_tools/lsp/session.py#PyrightSession._reader_loop",
    "sym:packages/ai-parrot-tools/src/parrot_tools/lsp/session.py#PyrightSession._spawn_process",
    "sym:packages/ai-parrot-tools/src/parrot_tools/lsp/session.py#_terminate_process"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `os.killpg` is POSIX-only; guard with `hasattr(os, 'killpg')`.
- `start_new_session=True` is passed to `create_subprocess_exec` in
  `_spawn_process` only — the version-check subprocess in `_verify_version`
  does NOT need it (it's short-lived and has no children).
- The `serverInfo.version` check in `_handshake` is a WARNING when absent
  (some LSP servers omit it), a hard `LSPFailure` when present but wrong.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import signal` at the top — *why*: needed for `signal.SIGTERM` / `signal.SIGKILL` in `_terminate_process`.
2. Change the three `_DEFAULT_*_TIMEOUT_S` constants from 5.0 to 2.0 — *why*: spec §2 says 2 s per stage.
3. Add `serverInfo.version` cross-check after line 458 in `_handshake` — *why*: detect PATH-shadow mismatch between `_verify_version` and `_spawn_process`.
4. Add `self._notification_event.set()` after `_fail_all_pending(exc)` in `_reader_loop` — *why*: wake blocked `diagnostics()` callers immediately on crash.
5. Add `start_new_session=True` to the `create_subprocess_exec` call in `_spawn_process` — *why*: make the child a session leader so `os.killpg` targets the whole group.
6. Replace `proc.terminate()` / `proc.kill()` in `_terminate_process` with `os.killpg` calls, guarded by `hasattr(os, 'killpg')` — *why*: kill grandchildren too.

### `packages/ai-parrot-tools/src/parrot_tools/lsp/session.py` (MODIFY)

**Change 1 — add import:**
```python
# occurrences: 1 (verified: grep -c 'import re' session.py)
# AFTER — insert below `import re` (verified: session.py:33)
import signal
```

**Change 2 — fix timeouts:**
```python
# occurrences: 1 (verified: grep -c '_DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0' session.py)
# REPLACE `_DEFAULT_SHUTDOWN_TIMEOUT_S = 5.0` (verified: session.py:75)
_DEFAULT_SHUTDOWN_TIMEOUT_S = 2.0
_DEFAULT_TERMINATE_TIMEOUT_S = 2.0
_DEFAULT_KILL_TIMEOUT_S = 2.0
```

**Change 3 — serverInfo version cross-check in `_handshake`:**
```python
# occurrences: 1 (verified: grep -c 'self._server_capabilities = response.result.get' session.py)
# AFTER — insert below `self._server_capabilities = ...` (verified: session.py:458)
if isinstance(response.result, dict):
    server_info = response.result.get("serverInfo", {})
    reported_version = server_info.get("version") if isinstance(server_info, dict) else None
    if reported_version is not None and reported_version != config.expected_server_version:
        raise LSPFailure(
            "server_version_mismatch",
            f"initialize serverInfo.version {reported_version!r} "
            f"does not match expected {config.expected_server_version!r}",
        )
    if reported_version is None:
        self.logger.warning("server did not report serverInfo.version in initialize response")
```

**Change 4 — wake notification event on crash:**
```python
# occurrences: 1 (verified: grep -c 'self._fail_all_pending(exc)' session.py)
# AFTER — insert below `self._fail_all_pending(exc)` (verified: session.py:545)
self._notification_event.set()
```

**Change 5 — start_new_session in _spawn_process:**
```python
# occurrences: 1 (verified: grep -c 'stderr=asyncio.subprocess.PIPE,$' session.py — second create_subprocess_exec)
# REPLACE the create_subprocess_exec call in _spawn_process (verified: session.py:416-423)
self._process = await asyncio.create_subprocess_exec(
    *config.server_command,
    cwd=str(config.repo_root),
    env=env,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    start_new_session=True,
)
```

**Change 6 — process-group signaling in _terminate_process:**
```python
# occurrences: 1 (verified: grep -c 'proc.terminate()' session.py — the one inside _terminate_process)
# REPLACE the terminate/kill block (verified: session.py:942-950)
if hasattr(os, "killpg"):
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGTERM)
else:
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
try:
    await asyncio.wait_for(proc.wait(), timeout=self._terminate_timeout_s)
    return
except asyncio.TimeoutError:
    pass
if hasattr(os, "killpg"):
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
else:
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
```
**Why**: `os.killpg` targets the entire process group (the session leader and all
its children). `PermissionError` is suppressed alongside `ProcessLookupError`
because a reaped process group raises it on some kernels. The `hasattr` guard
preserves the existing per-PID behavior on Windows.

### FILL IN checklist
- [ ] `_handshake` version mismatch message format — bounded by AC-1/AC-2
- [ ] `_terminate_process` error logging after SIGKILL timeout — existing pattern at session.py:954

---

## Acceptance Criteria

- [ ] `_handshake` raises `LSPFailure("server_version_mismatch")` when
      `serverInfo.version` differs from `config.expected_server_version` (AC-1)
- [ ] `_handshake` logs a warning when `serverInfo` is absent (AC-2)
- [ ] `_reader_loop` sets `_notification_event` on crash exit (AC-3)
- [ ] `_DEFAULT_SHUTDOWN_TIMEOUT_S` == `_DEFAULT_TERMINATE_TIMEOUT_S` ==
      `_DEFAULT_KILL_TIMEOUT_S` == 2.0 (AC-4)
- [ ] `_terminate_process` uses `os.killpg` on POSIX (AC-5)
- [ ] `_spawn_process` passes `start_new_session=True` (AC-6)
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/lsp/session.py`

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/lsp/test_session_lifecycle.py -q`

---

## Test Specification

Tests are in TASK-4271.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug lsp-session-fixes --feature-id FEAT-657`)
2. **Read the spec** at `sdd/specs/lsp-session-fixes.spec.md` for full context
3. **Verify the Codebase Contract** — confirm every anchor still matches
4. **Update status** in `sdd/tasks/index/lsp-session-fixes.json` → `"in-progress"`
5. **Implement** — apply each blueprint change in order
6. **Verify** all acceptance criteria and run Validation Commands
7. **Commit the code** — stage only `session.py`
8. **Close the task** with `scripts/sdd/close_task.sh TASK-4270 lsp-session-fixes verified`

---

## Completion Note

All four fixes applied to `session.py`. Existing `test_session_lifecycle.py` passes (21); ruff clean. New tests are TASK-4271.

**Completed by**: Claude (sdd-start)
**Date**: 2026-10-14
**Notes**: `import re` anchor was line 32, not 33. The `create_subprocess_exec` block matches twice (`_verify_version` and `_spawn_process`), so the edit was disambiguated via `env=env`; only `_spawn_process` got `start_new_session=True`. A version mismatch raised in `_handshake` is reaped by `start()`'s existing `_cleanup_partial_startup`.

**Deviations from spec**: none
