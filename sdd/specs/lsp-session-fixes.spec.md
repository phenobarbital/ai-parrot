---
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [lsp, fix, ledger-driven]
---

# Feature Specification: LSP Session Fixes

**Feature ID**: FEAT-657
**Date**: 2026-10-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.30.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`PyrightSession` (FEAT-580 M2) has four verified issues discovered during
code review of TASK-3502:

1. **`_handshake` never cross-checks `serverInfo.version`** (major) —
   The initialize response carries `serverInfo.version` from the running
   Pyright process, but `_handshake` ignores it. If `_verify_version` ran
   a different binary than the one `_spawn_process` actually started (e.g.
   PATH shadowing), the mismatch goes undetected.

2. **`_reader_loop` doesn't wake diagnostic waiters on crash** (minor) —
   When the reader loop exits on EOF or protocol failure it calls
   `_fail_all_pending()` (waking request futures) but never sets
   `_notification_event`, leaving `diagnostics()` callers blocked until
   their timeout expires instead of failing fast.

3. **Default shutdown timeouts are 5.0s, not spec-pinned 2s** (minor) —
   `_DEFAULT_SHUTDOWN_TIMEOUT_S` / `_DEFAULT_TERMINATE_TIMEOUT_S` /
   `_DEFAULT_KILL_TIMEOUT_S` are all 5.0 s. The spec's §2 "bounded
   process shutdown" says 2 s per stage.

4. **`_terminate_process` signals only the child PID, not a process
   group** (minor, ESCALATE) — `proc.terminate()` / `proc.kill()` send
   SIGTERM/SIGKILL to the immediate child only. If Pyright forks
   (node does), grandchildren are orphaned.

### Goals

- Fix all four issues in a single, self-contained feature.
- No behavioral regressions in existing LSP tests.

### Non-Goals

- Adding new LSP capabilities or methods.
- Changing the toolkit or protocol layers.

---

## 2. Technical Design

### Module: `parrot_tools/lsp/session.py`

**Fix 1 — serverInfo.version cross-check in `_handshake`:**

After the initialize response is received (line ~458), extract
`response.result["serverInfo"]["version"]` (when present) and compare it
against `config.expected_server_version`. On mismatch, raise
`LSPFailure("server_version_mismatch", ...)`. When `serverInfo` is absent
or has no `version` key, log a warning but do not fail (the pre-handshake
`_verify_version` already validated).

**Fix 2 — wake `_notification_event` on crash:**

At the end of `_reader_loop`, after setting `self._crashed = True` and
calling `_fail_all_pending()`, also call `self._notification_event.set()`
so that any `diagnostics()` coroutine blocked on
`self._notification_event.wait()` wakes immediately and observes the
crashed state.

**Fix 3 — align default timeouts to spec:**

Change the three module-level constants:
```python
_DEFAULT_SHUTDOWN_TIMEOUT_S = 2.0
_DEFAULT_TERMINATE_TIMEOUT_S = 2.0
_DEFAULT_KILL_TIMEOUT_S = 2.0
```

**Fix 4 — process-group signaling in `_terminate_process`:**

Use `os.killpg(proc.pid, signal.SIGTERM)` instead of `proc.terminate()`,
and `os.killpg(proc.pid, signal.SIGKILL)` instead of `proc.kill()`.
Guard with `ProcessLookupError` (already present). Spawn the subprocess
with `start_new_session=True` (in `_spawn_process`) so it becomes a
session leader and `os.killpg` targets the entire group. If the platform
does not support `os.killpg` (Windows), fall back to the current
per-PID behavior.

### Testing

All fixes are testable via the existing `tests/lsp/test_session.py`
test infrastructure (mock subprocess). Add:
- A test that `_handshake` raises on serverInfo version mismatch.
- A test that `_handshake` warns (not fails) when serverInfo is absent.
- A test that a crashed reader loop wakes a blocked `diagnostics()` caller.
- A test verifying the default timeouts are 2.0 s.
- A test that `_terminate_process` sends SIGTERM to the process group.

---

## 3. Acceptance Criteria

1. `_handshake` raises `LSPFailure("server_version_mismatch")` when
   `serverInfo.version` differs from `config.expected_server_version`.
2. `_handshake` logs a warning (does not raise) when `serverInfo` is absent.
3. `_reader_loop` sets `_notification_event` on crash exit.
4. `_DEFAULT_SHUTDOWN_TIMEOUT_S` == `_DEFAULT_TERMINATE_TIMEOUT_S` ==
   `_DEFAULT_KILL_TIMEOUT_S` == 2.0.
5. `_terminate_process` uses `os.killpg` on POSIX; falls back to per-PID
   on platforms without it.
6. The subprocess is spawned with `start_new_session=True`.
7. All existing LSP session tests pass.
8. New tests cover each fix.

---

## 4. Ledger Provenance

| Issue ID | Title | Severity |
|----------|-------|----------|
| `issue:ba27fc15246d` | PyrightSession never cross-checks initialize's serverInfo.version | major |
| `issue:736bb2d8440a` | _reader_loop doesn't wake blocked diagnostic waiters on server crash | minor |
| `issue:a31f68257dba` | Shutdown timeouts default to 5.0s, not spec-pinned 2s | minor |
| `issue:b4763b2b4836` | _terminate_process signals only the immediate child PID, not a process group | minor |
