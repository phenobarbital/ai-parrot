# TASK-1943: PythonREPLTool → worker integration + namespace API

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1941, TASK-1942
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 — the integration heart. `PythonREPLTool._execute()` stops
running `exec()` in-process and talks to the per-session worker through
`WorkerHandle`/`WorkerPool`, preserving the G5 return contract byte-for-byte.
Adds the public namespace API (`get_var`/`set_var`/`list_vars`/`snapshot`)
that replaces direct `.locals`/`.globals` access (call sites ported in
TASK-1944). Explicit degradation: if the worker cannot start, a clear error —
**the in-process `exec()` path must be unreachable** (G8/AC8).

---

## Scope

- Modify `packages/ai-parrot/src/parrot/tools/pythonrepl.py`:
  - `_execute()` (`:950`): keep the **host-side static gate** exactly as
    today (sanitizer + AST walk, fail cheap without a round-trip), then send
    `exec` to the session's worker via the pool. Map `ExecResult` to the G5
    contract: success str / `{status, result, error}` dict; `_ERROR_OUTPUT_RE`
    classification unchanged.
  - **Worker acquisition**: lazy on first `_execute()` (never in `__init__`);
    session identity comes from the tool's existing session/context plumbing —
    if the tool has none, use one worker per tool instance (instance id as
    `session_id`) and document it. Check what `AbstractTool`/callers provide
    before inventing a session key.
  - **No in-process fallback** (G8): on worker start failure, return the G5
    error dict with an explicit message; the code path to local
    `exec()`/`_execute_code` for LLM code must be structurally unreachable
    (`_execute_code` body moves out or is only invoked inside the worker
    package).
  - `reset_environment()` (`:1023`): kill + replace the session worker
    (namespace intentionally cleared).
  - Public namespace API on the tool:
    `async def get_var/set_var/list_vars/snapshot` delegating to the handle.
  - Plots: `save_current_plot` is recreated **in the worker** (TASK-1940)
    writing to a shared output dir derived from the tool's `output_dir`;
    the tool passes that dir at worker start; only the path (or base64 when
    `return_plot_as_base64=True`) crosses the boundary.
  - Remove/neutralize the `_bootstrapped` class variable on the host path
    (bootstrap is per-worker now); `reset` of it at `:1041` follows the
    worker-restart semantics.
- Keep the TASK-1939 dedicated executor only where still needed (framing I/O
  helpers if any run in threads); the shared-default executor must not come
  back.
- Unit tests per spec §4 (Module 5 rows) + integration tests
  `test_e2e_data_analysis_session` (minus `inject_df`, which lands in
  TASK-1945) and `test_e2e_runaway_loop_recovery`.

**NOT in scope**: porting external call sites (TASK-1944); Arrow DataFrame
transport — `inject_dataframe` may stay `NotImplementedError` (TASK-1945);
docs (TASK-1960).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/pythonrepl.py` | MODIFY | `_execute` → worker; namespace API; reset→restart; no in-process fallback |
| `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py` | MODIFY | Export what the tool needs |
| `packages/ai-parrot/tests/repl_worker/test_integration.py` | CREATE | Contract-invariant, persistence, isolation, reset, plot, namespace-API, no-fallback tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-27 (`pythonrepl.py` is 1208 lines).

### Verified Imports

```python
from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile
# pythonrepl.py:231 — keep the host gate intact (G6)
from parrot.tools.repl_worker.handle import WorkerHandle     # TASK-1941
from parrot.tools.repl_worker.pool import WorkerPool         # TASK-1942
from parrot.tools.repl_worker.protocol import WorkerConfig   # TASK-1940
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py
class PythonREPLTool(AbstractTool):
    name = "python_repl"                       # :100
    _bootstrapped = False                      # :105 — read :537, written :556, reset :1041
    def __init__(self, locals_dict=None, globals_dict=None, report_dir=None,
                 plt_style="seaborn-v0_8-whitegrid", palette="Set2",
                 setup_code=None, sanitize_input_enabled=True,
                 auto_save_plots=True, return_plot_as_base64=False,
                 debug=False, policy=None, **kwargs): ...    # :187-201
        # self.locals = locals_dict or {}      # :244
        # self.globals = globals_dict or {}    # :245
    def _check_ast_security(self, tree) -> Optional[str]: ...     # :558 (host gate — KEEP)
    def _execute_code(self, query, debug=False,
                      enforce_security=True) -> str: ...          # :701 (moves to worker)
    _ERROR_OUTPUT_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*(Error|Exception): ")  # :936
    async def _execute(self, code, debug=False, **kwargs) -> Any: # :950
        # :968-970: loop.run_in_executor(...)  ← replaced by worker round-trip
    def reset_environment(self) -> None: ...                      # :1023
```

```python
# INVARIANT RETURN CONTRACT (G5) — :955-985 — byte-compatible:
# success → str
# hard failure → {"status": "error", "result": f"ToolError: ...", "error": str(e)}
# classified error output → {"status": "done_with_errors", "result": output, "error": output}
```

- `locals["save_current_plot"]` closure: defined `:366` over
  `self.output_dir`, registered `:482`, used `:617` — worker-side recreation
  already exists from TASK-1940; this task passes the shared dir and handles
  the returned path/base64.
- `locals["execution_results"]`: registered `:480`, cleared `:1031`, read
  `:1011, :1063, :1110-1115` — host-side readers inside `pythonrepl.py`
  itself must go through the worker (snapshot/get_var), same as external
  callers.

### Does NOT Exist

- ~~A session concept in today's `PythonREPLTool`~~ — `self.locals` is per
  instance; the session key strategy is decided in this task (document it).
- ~~A compatibility dict-proxy for `tool.locals`~~ — **explicitly rejected**
  in the spec (Non-Goals). Do not build one. `.locals`/`.globals` stop being
  the source of truth; external call sites are ported in TASK-1944.
- ~~In-process fallback when the worker fails~~ — G8 forbids it; a test
  asserts `exec` is never reached.
- ~~`inject_df` transport~~ — arrives in TASK-1945; keep
  `inject_dataframe()` raising `NotImplementedError` with a clear message.

---

## Implementation Notes

### Key Constraints

- **`_execute_code()` moves; it is not rewritten.** Behavior differences
  between the old REPL and the worker are bugs (spec §7).
- Host gate first (cheap rejection, no worker round-trip), worker revalidates
  (defense in depth) — both sides, G6/AC6.
- Keep `sanitize_input_enabled` and `policy` kwargs working: the same policy
  must be serialized/passed to the worker at start so both gates agree.
- `ask_stream`/callers upstream see zero API change (G5); run the existing
  security test suite unmodified as a regression net.
- Two tool instances (or two session ids) → two workers → no shared
  namespace (G7/AC7 test).
- Async throughout on the host; no blocking pipe I/O on the event loop.

### References in Codebase

- `packages/ai-parrot/tests/test_pythonrepl_security.py` — must keep passing
  unmodified (gate behavior + error shapes).
- `parrot/tools/repl_worker/` — TASK-1940/41/42 deliverables.

---

## Acceptance Criteria

- [ ] `test_execute_contract_invariant`: str on success, dict on error,
      `_ERROR_OUTPUT_RE` classification identical (AC5).
- [ ] `test_no_inprocess_fallback`: worker start forced to fail → explicit
      G5 error; in-process `exec` provably not invoked (AC8).
- [ ] `test_state_persists_across_calls`: var created in call N visible in
      call N+1 (AC4/G1).
- [ ] `test_reset_environment_restarts_worker`: new worker, clean namespace.
- [ ] `test_plot_via_shared_dir`: plot lands in shared dir; only path/base64
      crosses; `return_plot_as_base64=True` returns the b64 string.
- [ ] `test_namespace_api`: `get_var`/`set_var`/`list_vars`/`snapshot`
      against a live worker.
- [ ] `test_session_isolation`: two sessions, two workers, no cross-visibility
      (AC7).
- [ ] Code rejected by the host gate never starts/reaches a worker (AC6).
- [ ] `test_e2e_runaway_loop_recovery`: infinite loop → timeout → LLM gets
      loss error with variable list → session usable again.
- [ ] Existing suite passes: `pytest packages/ai-parrot/tests/ -v`
      (including `test_pythonrepl_security.py` unmodified).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/`

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_integration.py
import pytest
from parrot.tools.pythonrepl import PythonREPLTool

@pytest.fixture
def tool(tmp_path):
    return PythonREPLTool(report_dir=str(tmp_path))


class TestExecuteContract:
    async def test_execute_contract_invariant(self, tool): ...
    async def test_no_inprocess_fallback(self, tool, monkeypatch):
        """Force worker spawn failure; assert G5 error dict and that
        PythonREPLTool never calls exec/_execute_code in-process
        (e.g. monkeypatch a sentinel that raises if reached)."""
        ...

class TestStateAndIsolation:
    async def test_state_persists_across_calls(self, tool): ...
    async def test_session_isolation(self, tmp_path): ...
    async def test_reset_environment_restarts_worker(self, tool): ...

class TestNamespaceAPI:
    async def test_namespace_api(self, tool): ...

class TestPlots:
    async def test_plot_via_shared_dir(self, tool): ...

class TestE2E:
    async def test_e2e_runaway_loop_recovery(self, tool): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1941 and TASK-1942 must be in
   `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `pythonrepl.py` anchors AND the actual
   APIs built by TASK-1940/41/42 (they are the real contract now)
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1943-pythonrepl-worker-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
