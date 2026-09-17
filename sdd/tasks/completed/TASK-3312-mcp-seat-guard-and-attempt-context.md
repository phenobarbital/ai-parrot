# TASK-3312: MCP seat pytest guard + attempt context writer

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3309
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (and the MCP half of AC5). The `sdd-coder` engine dispatches MCP
seats (nova / google-compat / grok / codex backends) through
`SddCoderEngine._run_attempt`, one fresh sub-worktree per attempt. Today nothing
stops a seat from running `pytest packages/ai-parrot/tests` (~9 min) or a bare
`pytest` through the LLM dispatchers' `run_command` tool.

This task wires the test-scope kernel into that exec point:

1. the engine writes an `AttemptContext` (tier `task`) into the attempt
   sub-worktree's per-worktree git admin dir right after the sub-worktree exists
   — this file is what turns the guard on (spec §2 Overview item 6);
2. `LLMCodeDispatcher._tool_run_command` asks `guard_argv` about every command
   after the allow-list / path checks and before `command_policy_error`:
   `allow` → unchanged; `rewrite` → run the scoped replacement invocations;
   `block` → refuse without executing.

The codex backend also goes through `_run_attempt`, so the context written here is
also what TASK-3314's codex hook reads. The native seat's context is written by
TASK-3313 (`prepare_native`), which is serialized after this task because both edit
`engine.py` and `test_engine_dispatch.py`.

---

## Scope

- Modify `SddCoderEngine._run_attempt` to write `AttemptContext(tier="task", task_id, task_file, base_ref=ctx.feature_branch)` via `write_attempt_context` immediately after `await manager.create(...)`; a write failure is logged as a warning and never fails the attempt.
- Modify `LLMCodeDispatcher._tool_run_command` to call `guard_argv(argv, worktree=Path(cwd))` (via `asyncio.to_thread`) before `command_policy_error`.
- Add `LLMCodeDispatcher._run_guarded_invocations` that runs the replacement argvs sequentially through `_run_argv` from the worktree root, merges stdout/stderr, returns the first non-zero exit code and sets `hint` to the guard message.
- `block` returns `{"ok": False, "exit_code": None, "stdout": "", "stderr": <message>}` without awaiting `_run_argv`.
- A guard exception is logged and treated as `allow` (never break a seat's command).
- Write tests for the rewrite, block, inactive (no context), guard-exception and engine-context paths.

**NOT in scope**: the kernel itself (`test_scope/guard.py`, `context.py` — TASK-3306/3309); `prepare_native` and the native Claude hook (TASK-3313); the codex hook (TASK-3314); QANode (TASK-3311).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | guard call in `_tool_run_command` + `_run_guarded_invocations` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | write `AttemptContext` in `_run_attempt` after `manager.create` |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` | MODIFY | run_command guard tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | engine writes attempt context test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# dispatchers/llm.py — already present
from parrot.flows.dev_loop.worktree_environment import command_policy_error, protected_argv, validate_write_path  # verified: dispatchers/llm.py:58
from parrot.flows.dev_loop.models import DispatchEvent, DispatchLabels, LLMCodeDispatchProfile  # verified: dispatchers/llm.py:56
import asyncio  # verified: dispatchers/llm.py:14
from pathlib import Path  # verified: dispatchers/llm.py:19

# sdd_coder/engine.py — already present
import asyncio  # verified: sdd_coder/engine.py:15
from pathlib import Path  # verified: sdd_coder/engine.py:25
from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files  # verified: sdd_coder/engine.py:54

# tests — already present
from parrot.flows.dev_loop import (DevelopmentOutput, DispatchExecutionError, DispatchOutputValidationError,
                                   LLMCodeDispatchProfile, LLMCodeDispatcher, ResearchOutput)  # verified: test_llm_code_dispatcher.py:12-19
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: sdd_coder/test_engine_dispatch.py:13
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat  # verified: sdd_coder/test_engine_dispatch.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
class LLMCodeDispatcher:  # L66
    self.logger = logging.getLogger(__name__)  # L85
    async def _tool_run_command(self, cwd: str, args: Dict[str, Any], profile: LLMCodeDispatchProfile) -> Dict[str, Any]:  # L1893
        argv = args.get("argv")                                   # L1899
        command = os.path.basename(argv[0])                       # L1902
        if command not in set(profile.allowed_commands): ...      # L1903 (returns ok False + hint)
        path_error = self._validate_command_paths(cwd, argv, profile)  # L1916
        run_cwd = cwd                                             # L1929 (may be re-anchored by args["cwd"])
        timeout = min(int(args.get("timeout_seconds") or profile.command_timeout_seconds), profile.command_timeout_seconds)  # L1939-1942
        if policy_error := command_policy_error(Path(run_cwd), argv):  # L1943
            return {"ok": False, "exit_code": None, "stdout": "", "stderr": policy_error}  # L1944
        result = await self._run_argv(argv, cwd=run_cwd, timeout=timeout)  # L1945
        payload = {**result, "ok": result["exit_code"] == 0}      # L1946
    async def _run_argv(self, argv: Sequence[str], *, cwd: str, timeout: int, stdin: Optional[str] = None) -> Dict[str, Any]:  # L2124
        # returns {"exit_code", "stdout", "stderr"}; wraps with protected_argv (L2135)

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
@dataclass(frozen=True)  # L177
class _FeatureCtx:  # L178
    worktree: str; feature_id: str; feature: str; feature_branch: str; index_path: str; spec_path: str; base_branch: str  # L181-187
class SddCoderEngine:
    self.logger = logging.getLogger(__name__)  # L345
    async def _run_attempt(self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *, attempt: int, job_id: str,
                           execution_id: Optional[str] = None, pool: Optional["ExecutionPool"] = None) -> Tuple[...]:  # L1897
        path = self._path_for(ctx, task.task_id, attempt, execution_id)   # L1923
        await manager.create(self._worker_id(task.task_id, attempt, execution_id))  # L2036
        dispatcher, profile = self._dispatcher_builder(...)                # L2037
        profile = profile.model_copy(update={"subagent": "sdd-coder"})    # L2043

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class PlannedTask(BaseModel):  # L209 — task_id: str, task_file: str, ...

# tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
class FakeDispatcher:  # L18 — dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None); records self.calls[{"brief","profile","node_id","cwd","labels"}]
def fake_builder_factory(behaviour_by_backend: dict, *, gate=None): ...  # L70 — builder.dispatchers[agent]
def _roster(*labels_backends: tuple[str, str]) -> RosterConfig: ...  # L87
@pytest.fixture
def noop_probe(): ...  # L99
# fixture git_sandbox_feature -> (worktree, feature_branch, base_path, index_path)  # sdd_coder/conftest.py:91

# tests/flows/dev_loop/test_llm_code_dispatcher.py
def _dispatcher(monkeypatch, client: _FakeClient) -> LLMCodeDispatcher: ...  # L91
async def test_run_command_rejects_non_allowlisted_command(monkeypatch, tmp_path): ...  # L449 (pattern to copy)
```

### Created by dependency tasks (verify they exist before starting)
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py  (TASK-3304)
@dataclass(frozen=True)
class AttemptContext:
    tier: str; task_id: str; task_file: str; base_ref: str

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py  (TASK-3306)
CONTEXT_FILENAME: str = "parrot-test-scope.json"
def worktree_git_dir(worktree: Path) -> Path | None: ...
def write_attempt_context(worktree: Path, ctx: AttemptContext) -> Path: ...
def read_attempt_context(worktree: Path) -> AttemptContext | None: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py  (TASK-3309)
@dataclass(frozen=True)
class GuardOutcome:
    action: str                          # "allow" | "rewrite" | "block"
    argvs: tuple[tuple[str, ...], ...]   # replacement invocations (repo-relative paths) when action == "rewrite"
    message: str
def guard_argv(argv: Sequence[str], *, worktree: Path) -> GuardOutcome: ...
```

### Does NOT Exist
- ~~`LLMCodeDispatcher._run_guarded_invocations`~~ — created by this task
- ~~`LLMCodeDispatchProfile.test_scope_*` fields~~ — the guard is driven by the attempt context file, NOT by profile fields; do not add any
- ~~`TaskScopedBrief.validation_commands`~~ / ~~`PlannedTask.validation_commands`~~ — not real; the kernel reads the task file itself
- ~~`repository_paths` returning the per-worktree git dir~~ — it returns the COMMON dir (`worktree_environment.py:26`); use `test_scope.context.worktree_git_dir`
- ~~a pytest run inside the sdd_coder engine~~ — the engine never runs tests; it only writes the context
- ~~`parrot.flows.dev_loop.test_scope.types`~~ — the module is `datatypes.py`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._tool_run_command",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._run_argv",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#_FeatureCtx",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#command_policy_error",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#PlannedTask"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# Early-return dict shape used throughout _tool_run_command (dispatchers/llm.py:1943-1944)
if policy_error := command_policy_error(Path(run_cwd), argv):
    return {"ok": False, "exit_code": None, "stdout": "", "stderr": policy_error}
```

### Key Constraints
- The kernel is sync (it shells out to git); call it with `await asyncio.to_thread(...)` — never block the loop.
- `guard_argv` gets `worktree=Path(cwd)` (the attempt worktree root), NOT `run_cwd`: plan paths are repo-relative. Replacement invocations therefore execute with `cwd=cwd`, not `run_cwd`.
- Order is fixed by the spec: allow-list → `_validate_command_paths` → cwd/timeout resolution → **guard** → `command_policy_error` → `_run_argv`.
- Never fail open into a crash: any exception from the guard → `self.logger.warning(...)` and continue as `allow`.
- A missing/failed context write in the engine must NOT fail the attempt (guard simply stays inactive) — log a warning.
- Import the kernel with the package path `parrot.flows.dev_loop.test_scope...` (in-process consumer). Never import it as top-level `test_scope` here (class-identity split).
- Keep existing return keys (`ok`, `exit_code`, `stdout`, `stderr`, `hint`) — seats' prompts rely on them.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:1893-1985` — the exec path being extended
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2028-2045` — sub-worktree creation inside the attempt `try`

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-3304/3306/3309 symbols exist (`datatypes.AttemptContext`, `context.write_attempt_context`, `guard.guard_argv`, `guard.GuardOutcome`) — *why*: this task only wires them; a missing symbol means a dependency is not merged.
2. Add the kernel imports to `llm.py` and `engine.py` — *why*: in-process consumers use the package path.
3. In `engine.py`, write the attempt context right after `manager.create` in `_run_attempt` — *why*: the guard must be active before the seat's first tool call (dispatch starts two lines later).
4. In `llm.py`, insert the guard block before `command_policy_error` and add `_run_guarded_invocations` — *why*: the spec fixes this position so path/allow-list errors keep their existing messages.
5. Add tests (dispatcher: rewrite / block / inactive / guard exception; engine: context file exists with the right fields at dispatch time) — *why*: AC5 MCP half and AC13.
6. Run the Validation Commands — *why*: AC13.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.flows.dev_loop.worktree_environment import command_policy_error, protected_argv, validate_write_path' dispatchers/llm.py)
# AFTER — insert below `from parrot.flows.dev_loop.worktree_environment import command_policy_error, protected_argv, validate_write_path` (verified: dispatchers/llm.py:58)
from parrot.flows.dev_loop.test_scope.guard import GuardOutcome, guard_argv
```
```python
# occurrences: 1 (verified: grep -c 'if policy_error := command_policy_error(Path(run_cwd), argv):' dispatchers/llm.py)
# BEFORE — insert immediately above `if policy_error := command_policy_error(Path(run_cwd), argv):` (verified: dispatchers/llm.py:1943)
        try:
            outcome: GuardOutcome = await asyncio.to_thread(guard_argv, argv, worktree=Path(cwd))
        except Exception as exc:  # noqa: BLE001 — a broken guard must never break the seat's command
            self.logger.warning("test-scope guard failed for %s: %s — running command unchanged", argv, exc)
            outcome = None
        if outcome is not None and outcome.action == "block":
            return {"ok": False, "exit_code": None, "stdout": "", "stderr": outcome.message}
        if outcome is not None and outcome.action == "rewrite":
            self.logger.info("test-scope guard rewrote %s into %d invocation(s)", argv, len(outcome.argvs))
            return await self._run_guarded_invocations(outcome.argvs, cwd=cwd, timeout=timeout, hint=outcome.message)
```
```python
# occurrences: 1 (verified: grep -c '    async def _run_argv(' dispatchers/llm.py)
# BEFORE — insert immediately above `    async def _run_argv(` (verified: dispatchers/llm.py:2124)
    async def _run_guarded_invocations(
        self,
        argvs: Sequence[Sequence[str]],
        *,
        cwd: str,
        timeout: int,
        hint: str,
    ) -> Dict[str, Any]:
        """Run the guard's replacement pytest invocations in order.

        Each invocation runs from the attempt worktree root (plan paths are
        repo-relative) through ``_run_argv``, so sandboxing is unchanged.

        Args:
            argvs: Replacement argvs produced by ``guard_argv``.
            cwd: The attempt worktree root.
            timeout: Per-invocation timeout in seconds.
            hint: The guard's explanation, surfaced to the seat.

        Returns:
            One ``run_command`` result: merged stdout/stderr, the first
            non-zero exit code (0 when all passed), ``ok`` and ``hint``.
        """
        stdout_parts: List[str] = []
        stderr_parts: List[str] = []
        exit_code: Optional[int] = 0
        for invocation in argvs:
            result = await self._run_argv(list(invocation), cwd=cwd, timeout=timeout)
            header = f"$ {shlex.join(invocation)}\n"
            stdout_parts.append(header + (result.get("stdout") or ""))
            stderr_parts.append(result.get("stderr") or "")
            # FILL IN: exit-code aggregation — keep the FIRST non-zero exit_code (None from a timeout counts as
            #          failure); keep running the remaining invocations — bounded by spec §7 R1
        return {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "stdout": "\n".join(stdout_parts),
            "stderr": "\n".join(p for p in stderr_parts if p),
            "hint": hint,
        }

```
**Why this shape**: The guard sits after every existing validation so allow-list/path errors keep their messages and before `command_policy_error` exactly as spec §3 M6 fixes. Rewrites run from `cwd` (worktree root) because the kernel emits repo-relative targets. `_run_argv` is reused so bubblewrap protection and output trimming are unchanged. `shlex` is already imported (L21).

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files' sdd_coder/engine.py)
# AFTER — insert below `from parrot.flows.dev_loop.sdd_coder.fidelity import check_banned_imports, check_fidelity, parse_task_files` (verified: sdd_coder/engine.py:54)
from parrot.flows.dev_loop.test_scope.context import write_attempt_context
from parrot.flows.dev_loop.test_scope.datatypes import AttemptContext
```
```python
# occurrences: 1 (verified: grep -c 'await manager.create(self._worker_id(task.task_id, attempt, execution_id))' sdd_coder/engine.py)
# AFTER — insert below `            await manager.create(self._worker_id(task.task_id, attempt, execution_id))` (verified: sdd_coder/engine.py:2036)
            await self._write_attempt_scope(path, task.task_id, task.task_file, ctx.feature_branch)
```
```python
# FILL IN: place this method next to `_path_for`/`_branch_for` helpers (sdd_coder/engine.py ~L1200-1215) — bounded by: private helper, no public API
    async def _write_attempt_scope(self, worktree_path: str, task_id: str, task_file: str, base_ref: str) -> None:
        """Write the task-tier test-scope context into an attempt sub-worktree (FEAT-563).

        The file turns the pytest guard on for that attempt only. A failure is
        logged and swallowed: without the file the guard is inactive, which is
        the pre-FEAT-563 behaviour, never a failed attempt.

        Args:
            worktree_path: The attempt sub-worktree root.
            task_id: TASK id being implemented.
            task_file: Repo-relative task markdown path.
            base_ref: Feature branch the attempt diffs against.
        """
        context = AttemptContext(tier="task", task_id=task_id, task_file=task_file, base_ref=base_ref)
        try:
            await asyncio.to_thread(write_attempt_context, Path(worktree_path), context)
        except Exception as exc:  # noqa: BLE001 — guard context is best-effort
            self.logger.warning("could not write test-scope context for %s in %s: %s", task_id, worktree_path, exc)
```
**Why**: `path` is computed at L1923 from the same worker id `manager.create` uses, and dispatch starts right after, so the seat's first `run_command` already sees the context. TASK-3313 reuses `_write_attempt_scope` from `prepare_native` — keep the name and signature.

### `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_run_command_rejects_non_allowlisted_command(monkeypatch, tmp_path):' test_llm_code_dispatcher.py)
# AFTER — append at the end of the file (tests are independent of position); pattern copied from L448-459
from parrot.flows.dev_loop.dispatchers import llm as llm_module
from parrot.flows.dev_loop.test_scope.guard import GuardOutcome


@pytest.mark.asyncio
async def test_run_command_rewrites_broad_pytest(monkeypatch, tmp_path):
    dispatcher = _dispatcher(monkeypatch, _FakeClient([]))
    replacement = (("pytest", "tests/test_a.py", "-q"), ("pytest", "packages/x/tests/test_b.py", "-q"))
    monkeypatch.setattr(llm_module, "guard_argv", lambda argv, *, worktree: GuardOutcome("rewrite", replacement, "scoped"))
    ran: list[list[str]] = []

    async def _fake_run(argv, *, cwd, timeout, stdin=None):
        ran.append(list(argv))
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(dispatcher, "_run_argv", _fake_run)
    result = await dispatcher._tool_run_command(str(tmp_path), {"argv": ["pytest"]}, LLMCodeDispatchProfile())
    # FILL IN: assert ran == [list(a) for a in replacement], result["ok"] is True, result["hint"] == "scoped" — AC5


@pytest.mark.asyncio
async def test_run_command_blocks_without_exec(monkeypatch, tmp_path):
    # FILL IN: guard returns GuardOutcome("block", (), "no scoped tests"); assert ok False, stderr == message,
    #          and a fake _run_argv was never awaited — AC5 / spec R4
    ...


@pytest.mark.asyncio
async def test_run_command_first_nonzero_exit_wins(monkeypatch, tmp_path):
    # FILL IN: two replacement invocations returning exit 1 then 0 → exit_code 1, both ran — spec R1
    ...


@pytest.mark.asyncio
async def test_run_command_guard_exception_runs_unchanged(monkeypatch, tmp_path):
    # FILL IN: guard raises RuntimeError → original argv executed once via _run_argv — "never break a seat"
    ...
```
**Why**: Patching `llm_module.guard_argv` (the name imported into `dispatchers/llm.py`) isolates this adapter from kernel behaviour, which TASK-3309 tests. Test bodies stay `FILL IN` by design; `...` stubs must be replaced with real bodies.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def test_engine_forces_sdd_coder_subagent(git_sandbox_feature, noop_probe):' sdd_coder/test_engine_dispatch.py)
# AFTER — insert below the end of `test_engine_forces_sdd_coder_subagent` (verified: sdd_coder/test_engine_dispatch.py:163-177)
async def test_engine_writes_attempt_context(git_sandbox_feature, noop_probe):
    """FEAT-563: every MCP attempt sub-worktree carries a task-tier AttemptContext before dispatch."""
    from parrot.flows.dev_loop.test_scope.context import read_attempt_context

    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    await engine.wait(job.job_id, 5)
    call = next(c for d in builder.dispatchers.values() for c in d.calls)
    context = read_attempt_context(Path(call["cwd"]))
    # FILL IN: assert context is not None, context.tier == "task", context.task_id == "TASK-0001",
    #          context.base_ref == feature_branch, context.task_file == call["brief"].task_file — AC5
    #          NOTE: if the attempt worktree is removed after merge, capture the context INSIDE a custom
    #          FakeDispatcher subclass's dispatch() instead of reading it afterwards.
```
**Why**: The fake dispatcher records `cwd` (the attempt sub-worktree), which is exactly where the context must exist when dispatch begins.

### FILL IN checklist
- [ ] `llm.py::_run_guarded_invocations` — first-non-zero exit aggregation, continue on failure; bounded by spec §7 R1
- [ ] `engine.py::_write_attempt_scope` — placement next to the `_path_for`/`_branch_for` helpers; bounded by private helper, no API change
- [ ] `test_llm_code_dispatcher.py` — four test bodies; bounded by AC5 / R1 / R4
- [ ] `test_engine_dispatch.py::test_engine_writes_attempt_context` — assertions (and capture-inside-dispatch if the worktree is cleaned up); bounded by AC5

---

## Acceptance Criteria

- [ ] Inside an MCP attempt, an over-broad pytest is rewritten to the kernel's scoped invocations; with an empty plan it is blocked without executing (spec AC5, MCP half)
- [ ] Outside attempts (no context file) `_tool_run_command` behaviour is byte-for-byte unchanged (spec AC5)
- [ ] A guard exception never breaks the command (runs unchanged, warning logged)
- [ ] Every `_run_attempt` sub-worktree carries `AttemptContext(tier="task", …, base_ref=<feature branch>)` before dispatch; a write failure does not fail the attempt
- [ ] Existing tests in both modified test files still pass
- [ ] All tests pass (see Validation Commands) (spec AC13)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py (appended)
async def test_run_command_rewrites_broad_pytest(monkeypatch, tmp_path): ...     # replacement argvs executed from cwd, hint set
async def test_run_command_blocks_without_exec(monkeypatch, tmp_path): ...        # ok False, _run_argv never awaited
async def test_run_command_first_nonzero_exit_wins(monkeypatch, tmp_path): ...    # R1 aggregation
async def test_run_command_guard_exception_runs_unchanged(monkeypatch, tmp_path): ...

# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py (inserted)
async def test_engine_writes_attempt_context(git_sandbox_feature, noop_probe): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3312-mcp-seat-guard-and-attempt-context.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (sonnet, sequential fallback — `complex_model_unavailable`, same
systemic roster gap as prior tasks; user-authorized direct implementation)
**Date**: 2026-09-17
**Notes**: Verified every anchor line number in `dispatchers/llm.py` and `sdd_coder/engine.py`
via `grep` before editing (all matched the contract exactly). Inserted the guard block in
`_tool_run_command` exactly at the fixed position (allow-list → path validation → cwd/timeout
resolution → **guard** → `command_policy_error` → `_run_argv`), calling `guard_argv(argv,
worktree=Path(cwd))` — the attempt worktree root, not `run_cwd` — via `asyncio.to_thread`;
guard exceptions are caught and logged, falling through as `allow`. Added
`_run_guarded_invocations` with the FILL-IN exit-code aggregation (first non-zero wins; `None`
from a timeout counts as failure code 1; every invocation still runs). Added
`_write_attempt_scope` to `engine.py` next to `_path_for`/`_branch_for` and wired its call
immediately after `manager.create` in `_run_attempt`, using the already-computed `path`
variable and `ctx.feature_branch` as `base_ref`; write failures are caught and logged, never
failing the attempt. Wrote all four `test_llm_code_dispatcher.py` FILL-IN test bodies (rewrite,
block-without-exec, first-nonzero-exit-wins, guard-exception-runs-unchanged) and the
`test_engine_dispatch.py` context-writer test (read via `call["cwd"]`/`call["brief"].task_file`
straight after `engine.wait()` — the sub-worktree was NOT removed by then, so the
`FakeDispatcher`-subclass capture-at-dispatch-time fallback noted in the blueprint was not
needed). Moved the two new test-file imports (`llm_module`, `GuardOutcome`) to the existing
top-of-file import block rather than literally appending them at the end as the blueprint's
code fragment showed, to avoid an avoidable `E402`.

**Regression check**: `test_llm_code_dispatcher.py` has 4 pre-existing failures
(`test_apply_patch_recovers_a_wrong_hunk_line_count`, `test_run_command_cwd_replaces_the_cd_prefix`,
`test_path_guard_can_be_turned_off`, `test_run_command_success_never_carries_a_glob_hint`) —
confirmed via `git stash` that these fail identically on the unmodified `HEAD` (before any of
this task's edits), so they are pre-existing environment issues, not a regression introduced
here. All 4 new dispatcher tests pass, the new engine test passes, the full `test_engine_dispatch.py`
suite is 32/32, and the full `test_scope` + `test_qa_default_criteria.py` suites remain 71/71.
`ruff check` clean on every file except pre-existing, unrelated findings confirmed present on
`HEAD` before this task (`ASYNC240` at two untouched lines in `llm.py`; `ASYNC221` inside the
three pre-existing-failure test functions, nowhere near this diff's line ranges per `git diff`).

**Deviations from spec**: none — only the four listed files were touched.

**Deviations from spec**: none | describe if any
