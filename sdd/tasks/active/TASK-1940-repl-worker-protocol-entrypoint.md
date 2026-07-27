# TASK-1940: Control protocol + worker entrypoint (`parrot/tools/repl_worker/`)

**Feature**: FEAT-380 — Sandbox Hardening — PythonREPLTool a worker persistente
**Spec**: `sdd/specs/sandbox-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 — the foundation of the whole feature: it **freezes the
control protocol** every later module builds on. Creates the new package
`parrot/tools/repl_worker/` with (a) length-prefixed Pydantic protocol
messages, (b) the worker process entrypoint (spawn-only) that applies
`setrlimit` before serving, and (c) the worker service loop that revalidates
the static gate and runs `_execute_code()` / `_describe_new_var()` — moved
**verbatim** from `pythonrepl.py`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py`.
- Create `protocol.py` with the Pydantic message models from spec §2 Data
  Models: `ExecRequest`, `ExecResult`, `NamespaceLossError`, `WorkerConfig`
  — plus request models for the remaining ops (`inject_df`, `get_var`,
  `set_var`, `list_ns`, `snapshot`, `reset`, `ping`) and a framing layer:
  length-prefixed (4-byte big-endian length + JSON payload) read/write over a
  binary stream, one message per request.
- Create `worker.py` — the child-process entrypoint:
  - **POSIX rlimits applied in the child before serving** (via
    `preexec_fn`/child-side setup): `RLIMIT_AS` (default ~4 GiB from
    `WorkerConfig`), `RLIMIT_CPU`, `RLIMIT_NOFILE`, `RLIMIT_CORE = 0`.
    On non-POSIX (`resource` unavailable), skip with a visible log line.
  - Service loop: read one framed message → dispatch op → write one framed
    reply. Ops in this task: `exec`, `list_ns`, `reset`, `ping`,
    `get_var`/`set_var`/`snapshot` (namespace ops are plain
    pickle/JSON-serialized values here; Arrow DF transport is TASK-1945 —
    `inject_df` may respond `not_implemented` for now).
  - **Static gate revalidated in the worker** before any `exec`:
    `PythonCodeSanitizer(general_profile())` + the AST denylist walk. Blocked
    code returns the same error shape as the host gate produces today.
  - `_execute_code()` and `_describe_new_var()` logic **moved as-is** (copy
    the bodies; adapt only `self.` references to the worker's namespace
    holder). Behavior differences vs the current REPL are bugs.
  - **Per-worker bootstrap**: the environment bootstrap (pandas/numpy/
    matplotlib imports + `save_current_plot` closure) runs once per worker
    process — this kills the `_bootstrapped` class-variable bug by design.
    `save_current_plot` in the worker writes to a **shared output directory
    passed at startup** (path or base64 travels back, never the figure).
- Unit tests: protocol roundtrip, rlimits applied in child, gate revalidation,
  per-worker bootstrap.

**NOT in scope**: host-side `WorkerHandle` / deadline SIGKILL (TASK-1941);
pool/TTL (TASK-1942); wiring `PythonREPLTool` to the worker (TASK-1943);
Arrow IPC DataFrame transport (TASK-1945).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/repl_worker/__init__.py` | CREATE | Package init, public re-exports |
| `packages/ai-parrot/src/parrot/tools/repl_worker/protocol.py` | CREATE | Pydantic messages + length-prefixed framing |
| `packages/ai-parrot/src/parrot/tools/repl_worker/worker.py` | CREATE | Child entrypoint: rlimits, gate revalidation, service loop, moved `_execute_code` |
| `packages/ai-parrot/tests/repl_worker/__init__.py` | CREATE | Test package |
| `packages/ai-parrot/tests/repl_worker/test_protocol.py` | CREATE | `test_protocol_roundtrip` |
| `packages/ai-parrot/tests/repl_worker/test_worker.py` | CREATE | `test_worker_rlimits_applied`, `test_worker_revalidates_gate`, `test_bootstrap_per_worker` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-27. Short paths below are relative
> to `packages/ai-parrot/src/`.

### Verified Imports

```python
from parrot.security.python_sanitizer import PythonCodeSanitizer, general_profile
# verified: used at parrot/tools/pythonrepl.py:231 (local import inside __init__)
# general_profile → parrot/security/python_sanitizer.py:273
# PythonCodeSanitizer → parrot/security/python_sanitizer.py:321

from parrot.security.redaction import redact_text   # pythonrepl.py:36
```

### Existing Signatures to Use (source of the moved code)

```python
# parrot/tools/pythonrepl.py (1208 lines)
class PythonREPLTool(AbstractTool):
    _bootstrapped = False        # :105 — class var; read :537, written :556
                                 # THE BUG this task fixes by moving bootstrap
                                 # into the worker process (one per worker)
    BLOCKED_IMPORTS: set         # :108
    BLOCKED_NAMES: set           # :128
    BLOCKED_ATTRIBUTES: set      # :152

    def _check_ast_security(self, tree: ast.AST) -> Optional[str]: ...   # :558
    def _serialize_execution_results(self, results) -> Dict: ...         # :627
    def _execute_code(self, query: str, debug: bool = False,
                      enforce_security: bool = True) -> str: ...         # :701
        # ns = self.locals; self.globals = ns   # :765-766
        # exec()/eval() over ns                 # :773, :786, :803, :825
    def _describe_new_var(self, var_name: str, val: Any) -> str: ...     # :871
    _ERROR_OUTPUT_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*(Error|Exception): ")  # :936
```

- `locals["execution_results"]` → dict written by executed code (registered
  at `:480`); `_serialize_execution_results` (`:627`) is the direct precedent
  for serializing outputs across the protocol — reuse its approach.
- `locals["save_current_plot"]` → closure over `self.output_dir` (defined
  `:366`, registered `:482`) — must be **recreated inside the worker**
  pointing at the shared output dir passed at startup.

### Spec-Frozen Protocol Models (spec §2 — implement exactly)

```python
class ExecRequest(BaseModel):
    op: Literal["exec"] = "exec"
    code: str
    debug: bool = False
    deadline_ms: int = Field(..., gt=0)

class ExecResult(BaseModel):
    op: Literal["result"] = "result"
    output: Optional[str] = None      # success path (str)
    status: Optional[str] = None      # "error" | "done_with_errors"
    result: Optional[Any] = None
    error: Optional[str] = None
    new_vars: list[str] = []          # feeds the host name-shadow

class NamespaceLossError(BaseModel):
    cause: Literal["timeout", "memory", "crash"]
    lost_variables: list[str]
    message: str

class WorkerConfig(BaseModel):
    rlimit_as_bytes: int = 4 * 1024**3
    rlimit_cpu_seconds: int = 300
    rlimit_nofile: int = 256
    deadline_ms: int = 60_000
    max_workers: int = 0              # 0 → max(4, cpu_count), cap 16
    idle_ttl_seconds: int = 1800
    prewarm_pool_size: int = 2
```

### Does NOT Exist

- ~~`parrot/tools/repl_worker/`~~ — this task creates it.
- ~~Any timeout/`resource`/`kill` machinery in `pythonrepl.py`~~ — zero
  occurrences (verified by grep); nothing to reuse.
- ~~Thread-scoped `resource.setrlimit()`~~ — rlimits are per-process; that is
  exactly why they must be applied in the **child**.
- ~~`fork` as a safe start method~~ — matplotlib, connection pools and parent
  threads do not tolerate it. **`spawn` is mandatory.**
- ~~An existing session concept in the REPL~~ — `self.locals` is per tool
  instance; sessions arrive with the pool (TASK-1942).

---

## Implementation Notes

### Key Constraints

- **The worker is synchronous by design** (one `exec` at a time); only the
  host side is async. Do not build an async server in the worker.
- `spawn` only. If using `subprocess`, launch
  `python -m parrot.tools.repl_worker.worker` (give `worker.py` a
  `if __name__ == "__main__":` entry); if using `multiprocessing`, force
  `get_context("spawn")`.
- Rlimits must be applied **in the child, before user code can run**. With
  `subprocess.Popen` use `preexec_fn`; with a `python -m` entrypoint,
  applying them first thing in `main()` (before heavy imports) is acceptable
  and Windows-tolerant — document the choice.
- `RLIMIT_CORE = 0` is non-negotiable: a core dump with DataFrames is a data
  leak.
- Pydantic for every message (project rule). Framing must be
  length-prefixed — never rely on newline-delimited JSON (outputs may embed
  newlines).
- Blocked-code error from the worker must match today's host-side shape so
  TASK-1943 can pass it through untouched (G5/AC6).
- Google-style docstrings + strict type hints throughout.

### Pattern to Follow

- `_serialize_execution_results()` (`pythonrepl.py:627`) for making
  execution outputs wire-safe.
- `packages/ai-parrot/tests/test_pythonrepl_security.py` for test style on
  gate behavior.

### Testing rlimits without killing the test runner

Spawn a real worker with a tiny `WorkerConfig` (e.g. `rlimit_as_bytes=512 MiB`)
and have the child report `resource.getrlimit(...)` over the protocol (or
exec `import resource; result = resource.getrlimit(resource.RLIMIT_AS)`).
Mark POSIX-only tests with
`@pytest.mark.skipif(sys.platform == "win32", ...)`.

---

## Acceptance Criteria

- [ ] Protocol roundtrip: every message model serializes → frames → parses
      back identically (`test_protocol_roundtrip`).
- [ ] Child starts with AS/CPU/NOFILE limits applied and CORE=0 on POSIX
      (`test_worker_rlimits_applied`).
- [ ] Blocked code sent straight to the worker is rejected before `exec`
      (`test_worker_revalidates_gate`) — AC6 worker half.
- [ ] Two spawned workers each run their own bootstrap
      (`test_bootstrap_per_worker`) — AC14.
- [ ] `_execute_code` behavior in the worker matches the in-process REPL for
      a plain success and a plain error snippet (same output text / error
      classification).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/repl_worker/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/repl_worker/`

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_protocol.py
import pytest
from parrot.tools.repl_worker.protocol import (
    ExecRequest, ExecResult, NamespaceLossError, WorkerConfig,
    write_frame, read_frame,   # or the equivalent framing API you define
)

def test_protocol_roundtrip():
    """Every protocol message survives frame → unframe → parse."""
    ...

# packages/ai-parrot/tests/repl_worker/test_worker.py
import sys
import pytest

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="rlimits are POSIX")

@pytest.fixture
def worker_config():
    return WorkerConfig(rlimit_as_bytes=512 * 1024**2, deadline_ms=2_000,
                        max_workers=2, idle_ttl_seconds=5, prewarm_pool_size=0)

@posix_only
def test_worker_rlimits_applied(worker_config):
    """Child reports AS/CPU/NOFILE per config and RLIMIT_CORE == 0."""
    ...

def test_worker_revalidates_gate(worker_config):
    """`import os; os.system('id')` sent directly to the worker is blocked before exec."""
    ...

def test_bootstrap_per_worker(worker_config):
    """Two workers → both have pandas/np bootstrapped independently."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm the `pythonrepl.py` anchors
   before moving code; if lines drifted, update the contract first
4. **Update status** in `sdd/tasks/index/sandbox-hardening.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1940-repl-worker-protocol-entrypoint.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
