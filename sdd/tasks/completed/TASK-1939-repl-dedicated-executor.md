# TASK-1939: Palliative — dedicated bounded executor for PythonREPLTool

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / G10 / AC1. Today `PythonREPLTool._execute()` dispatches
LLM-generated code with `loop.run_in_executor(None, ...)` — the **default
ThreadPoolExecutor shared by the whole framework**. A runaway loop passes the
static gate (it is legitimate code) and permanently hijacks a shared-pool
thread (Python threads cannot be killed). This task is the immediate,
independent stopgap decided in the brainstorm: a dedicated, bounded executor
so a runaway loop exhausts only the REPL's own pool.

**This task lands on `dev` immediately and independently** — it does not wait
for the worker architecture (Modules 2–9). Per the spec's Worktree Strategy,
it may be implemented directly on a short-lived branch off `dev` (or first in
the feature worktree and cherry-picked), but it must not be entangled with the
worker code.

---

## Scope

- Add a module-level (or class-level, lazily created) dedicated
  `concurrent.futures.ThreadPoolExecutor` for `PythonREPLTool`, with a
  configurable size defaulting to **4 threads** (e.g. `__init__` kwarg
  `executor_max_workers: int = 4`, env-overridable if a config surface already
  exists in the tool's kwargs).
- Replace `run_in_executor(None, self._execute_code, code, debug)` at
  `pythonrepl.py:970` with the dedicated executor.
- Name the threads (`thread_name_prefix="python-repl"`) so hijacked threads
  are identifiable in diagnostics.
- Write unit tests proving the default executor is no longer used and the
  pool is bounded.

**NOT in scope**: any worker process, timeout, SIGKILL, or rlimit work
(Modules 2–5); changing the return contract of `_execute()` (G5 — must remain
byte-identical); touching the sanitizer or AST gate.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/pythonrepl.py` | MODIFY | Dedicated bounded `ThreadPoolExecutor`; swap the `None` executor at `:970` |
| `packages/ai-parrot/tests/test_pythonrepl_executor.py` | CREATE | Tests for AC1 |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-27 (file is 1208 lines).

### Verified Imports

```python
# pythonrepl.py already imports asyncio and re at module top.
# You will need:
from concurrent.futures import ThreadPoolExecutor
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py
class PythonREPLTool(AbstractTool):
    name = "python_repl"                          # :100
    args_schema = PythonREPLArgs                  # :102
    _bootstrapped = False                         # :105 (class variable — do NOT touch here)

    def __init__(self, locals_dict=None, globals_dict=None, ...,
                 debug=False, policy=None, **kwargs): ...   # :187-201

    def _execute_code(self, query, debug=False,
                      enforce_security=True) -> str: ...    # :701

    async def _execute(self, code: str, debug: bool = False,
                       **kwargs) -> Any: ...                # :950
        # :968-970 (the exact lines to change):
        #     loop = asyncio.get_event_loop()
        #     output = await loop.run_in_executor(None, self._execute_code, code, debug)
```

```python
# INVARIANT RETURN CONTRACT (G5) — pythonrepl.py:955-985 — DO NOT ALTER:
# success → str; failure → {"status": ..., "result": ..., "error": ...}
# classification via _ERROR_OUTPUT_RE (:936) / _is_error_output
```

### Does NOT Exist

- ~~A dedicated executor for the REPL~~ — `:970` uses the shared default pool.
  You are creating it.
- ~~Any timeout/`signal`/`resource`/`kill` machinery in `pythonrepl.py`~~ —
  zero occurrences (verified by grep). This task does NOT add any either.
- ~~`self.executor` attribute on `PythonREPLTool`~~ — does not exist yet.

---

## Implementation Notes

### Pattern to Follow

```python
# One executor per tool instance keeps shutdown simple and scopes the bound:
self._repl_executor = ThreadPoolExecutor(
    max_workers=executor_max_workers,
    thread_name_prefix="python-repl",
)
...
output = await loop.run_in_executor(self._repl_executor, self._execute_code, code, debug)
```

A single module-level shared executor for all instances is also acceptable —
choose one, document why in the code, and test it. Per-instance is
recommended (session isolation of thread starvation is closer to the spirit
of G7).

### Key Constraints

- The G5 return contract of `_execute()` must be byte-identical — this change
  swaps the executor only.
- Do not eagerly create the executor at import time; lazy creation in
  `__init__` or on first `_execute()` is fine.
- Log the executor creation with `self.logger.debug`.

### References in Codebase

- `packages/ai-parrot/tests/test_pythonrepl_security.py` — existing test file
  for this tool; follow its fixture/import style.

---

## Acceptance Criteria

- [ ] `pythonrepl.py` no longer passes `None` as the executor for
      `_execute_code` (AC1) — `grep -n "run_in_executor(None" ` returns
      nothing for the exec path.
- [ ] Pool is bounded (default 4) and configurable via `__init__`.
- [ ] Return contract unchanged: success str / error dict (existing security
      tests still pass).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_pythonrepl_executor.py packages/ai-parrot/tests/test_pythonrepl_security.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/pythonrepl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/test_pythonrepl_executor.py
import asyncio
import threading
import pytest
from parrot.tools.pythonrepl import PythonREPLTool


@pytest.fixture
def tool():
    return PythonREPLTool(sanitize_input_enabled=True)


class TestDedicatedExecutor:
    async def test_exec_runs_on_named_repl_thread(self, tool):
        """Code executes on the dedicated pool, not the default executor."""
        out = await tool._execute("import threading\nresult = threading.current_thread().name")
        # thread name prefix proves the dedicated pool was used
        assert "python-repl" in str(out)

    async def test_pool_is_bounded(self, tool):
        """Executor max_workers honours the configured bound (default 4)."""
        assert tool._repl_executor._max_workers == 4

    async def test_return_contract_unchanged(self, tool):
        """G5: str on success, dict on error."""
        ok = await tool._execute("x = 1 + 1")
        assert isinstance(ok, (str, dict))
        err = await tool._execute("raise ValueError('boom')")
        assert isinstance(err, dict) and err["status"] in ("error", "done_with_errors")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `:968-970` still matches before editing
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1939-repl-dedicated-executor.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: Added `executor_max_workers: int = 4` kwarg to `PythonREPLTool.__init__`;
created `self._repl_executor = ThreadPoolExecutor(max_workers=executor_max_workers,
thread_name_prefix="python-repl")` right after the execution-environment init,
logged via `self.logger.debug`. Swapped `run_in_executor(None, ...)` →
`run_in_executor(self._repl_executor, ...)` at the single call site in
`_execute()` (`:990`, was `:970` pre-edit). Verified via grep this was the only
`run_in_executor` occurrence in the file. Return contract (G5) untouched.
All 38 tests pass (`test_pythonrepl_executor.py` + `test_pythonrepl_security.py`).
`ruff check` on the modified file shows the same 18 pre-existing errors as
`dev` HEAD (verified via `git stash` diff) — zero new errors introduced; the
new test file lints clean.

**Deviations from spec**: The task's Test Specification scaffold for
`test_exec_runs_on_named_repl_thread` (`import threading` inside sandboxed
code passed to `tool._execute(...)`) is not achievable unmodified: `threading`
is categorically denied by the (out-of-scope) allowlist gate's
`deny_data_io` set regardless of profile (`python_sanitizer.py`
`_DATA_IO_IMPORTS`). Per task scope ("touching the sanitizer or AST gate" is
NOT in scope), the test was adapted to verify the same property — that
`_execute()`'s dedicated named pool (`tool._repl_executor`) is real and
functional — by dispatching directly to `tool._repl_executor` via
`loop.run_in_executor` and asserting the resulting thread name, instead of
routing through sandboxed code text. AC1 (no `run_in_executor(None, ...)` in
the exec path) is covered separately by `test_default_executor_not_used`
(source inspection) and a passing grep.
