# TASK-3313: Native Claude seat pytest guard (hook) + native attempt context

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3309, TASK-3312
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (native half of AC5). The native Haiku `sdd-coder` seat runs as a
Claude Code subagent; every Bash call passes through the PreToolUse hook
`worktree_environment.py --hook` (frontmatter in `.claude/agents/sdd-coder.md:16-22`
and `sdd-worker.md`), which today only wraps the command in the bubblewrap sandbox
(`hook_response`, L158). That hook runs under the **system `python3` with
stdlib-only imports**, so it must load the stdlib-only test-scope kernel by path.

This task:
1. writes the task-tier `AttemptContext` into the native sub-worktree in
   `SddCoderEngine.prepare_native` (reusing `_write_attempt_scope`, created by
   TASK-3312 — hence the dependency and the serialization on `engine.py` /
   `test_engine_dispatch.py`);
2. calls `guard_bash` from `hook_response` **before** `protected_argv`:
   `rewrite` → wrap the rewritten command; `block` → deny with the guard
   message; kernel import failure → guard skipped (the sandbox wrapper must never
   break).

---

## Scope

- Modify `SddCoderEngine.prepare_native` to call `self._write_attempt_scope(path, task_id, planned.task_file, ctx.feature_branch)` right after `path = await manager.create(worker_id)`.
- Add `_load_guard_bash()` and `_scope_guard(command, cwd)` to `worktree_environment.py` (stdlib only; relative import when imported as a package, top-level `test_scope` when run as a script).
- Modify `hook_response` Bash branch: apply `_scope_guard` before `protected_argv`; `block` raises `ValueError(message)` so the existing `except` renders a deny.
- Write tests: rewrite wraps the rewritten command; block denies; no context / ImportError / guard exception → unchanged wrapping; script-mode loader resolves `test_scope.guard`; `prepare_native` writes the context.

**NOT in scope**: the kernel (`test_scope/guard.py`, TASK-3309); the MCP adapter and `_write_attempt_scope` itself (TASK-3312); codex (TASK-3314); changing hook wiring in agent frontmatter or `dispatchers/claude.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | `_load_guard_bash`, `_scope_guard`, guard call in `hook_response` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `prepare_native` writes the attempt context |
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | hook guard tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | native context test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# worktree_environment.py — stdlib only, already present (L7-16)
from __future__ import annotations
import argparse, json, os, shlex, shutil, sys
from pathlib import Path
from typing import Any, Sequence  # verified: worktree_environment.py:16

# tests — already present
from parrot.flows.dev_loop import worktree_environment as policy  # verified: test_worktree_environment.py:16
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: sdd_coder/test_engine_dispatch.py:13
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat  # verified: sdd_coder/test_engine_dispatch.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py
def repository_paths(cwd: Path) -> tuple[Path, Path | None]:  # L26 — (checkout root, COMMON git dir)
def protected_argv(cwd: Path, argv: Sequence[str]) -> list[str]:  # L109 — raises RuntimeError without bwrap
def hook_response(payload: dict[str, Any]) -> dict[str, Any]:  # L158
    cwd = Path(payload["cwd"])                                         # L160
    command = tool_input["command"]                                    # L165
    wrapped = protected_argv(cwd, ["/bin/bash", "-c", command])        # L168
    output["updatedInput"] = {**tool_input, "command": shlex.join(wrapped)}  # L171
    except (OSError, ValueError, RuntimeError, KeyError) as exc:       # L177
        output.update(permissionDecision="deny", permissionDecisionReason=str(exc))  # L178
def main() -> None:  # L182 — explicit deny on any exception

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
async def prepare_native(self, feature: str, worktree: str, task_id: str, execution_id: Optional[str] = None) -> NativePrep:  # L1225
    ctx = await self._resolve_feature(feature, worktree)            # L1236
    planned = next((t for c in plan.chunks for t in c.tasks if t.task_id == task_id), None)  # L1244
    path = await manager.create(worker_id)                           # L1285
    self._native_inflight.add(worker_id)                             # L1286
class _FeatureCtx:  # L178 — feature_branch: str (L184)

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
class NativePrep(BaseModel):  # L325 — task_id, task_file, branch, worktree_path, seat_label, model, attempt_uid, coder_feedback, assessment_id

# tests
# test_worktree_environment.py
@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, Path]: ...  # L22-39 — fake pool worktree whose .git file points to main/.git/worktrees/task-a2
def test_hook_preserves_shell_text_and_other_fields(checkout, monkeypatch) -> None: ...  # L104 — pattern: monkeypatch policy.shutil.which → "/usr/bin/bwrap"
def test_standalone_hook_denies_invalid_input() -> None: ...  # L222 — pattern for running the script with sys.executable
# sdd_coder/test_engine_dispatch.py
async def test_plan_then_dispatch_uses_consistent_seat_assignment(git_sandbox_feature, noop_probe): ...  # L236 — native+mcp roster, engine.plan(), prepare_native()
```

### Created by dependency tasks (verify they exist before starting)
```python
# test_scope/guard.py  (TASK-3309) — stdlib only, relative imports
@dataclass(frozen=True)
class GuardOutcome:
    action: str                          # "allow" | "rewrite" | "block"
    argvs: tuple[tuple[str, ...], ...]
    message: str
def guard_bash(command: str, *, worktree: Path) -> tuple[GuardOutcome, str | None]: ...  # (outcome, rewritten command or None)

# test_scope/context.py  (TASK-3306)
def read_attempt_context(worktree: Path) -> AttemptContext | None: ...

# sdd_coder/engine.py  (TASK-3312)
async def _write_attempt_scope(self, worktree_path: str, task_id: str, task_file: str, base_ref: str) -> None: ...
```

### Does NOT Exist
- ~~`import parrot` / pydantic inside `worktree_environment.py`~~ — forbidden; the module docstring (L1-5) requires stdlib only
- ~~a per-worktree git dir from `repository_paths`~~ — it returns the COMMON dir; the kernel's `worktree_git_dir` finds the attempt context
- ~~a separate native-seat hook file~~ — the guard lives inside the existing `hook_response`
- ~~`NativePrep.test_scope`~~ / ~~`NativePrep.validation_commands`~~ — not real; do not add fields
- ~~`parrot.flows.dev_loop.test_scope.types`~~ — the module is `datatypes.py`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#hook_response",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#protected_argv",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#repository_paths",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.prepare_native",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# hook_response already converts ValueError into a deny (worktree_environment.py:177-178):
except (OSError, ValueError, RuntimeError, KeyError) as exc:
    output.update(permissionDecision="deny", permissionDecisionReason=str(exc))
```

### Key Constraints
- **Stdlib only** in `worktree_environment.py`. Load the kernel lazily inside `_load_guard_bash`: `from .test_scope.guard import guard_bash` when `__package__` is set (imported as `parrot.flows.dev_loop.worktree_environment`), otherwise `from test_scope.guard import guard_bash` (script mode: the script's directory is already `sys.path[0]`).
- `ImportError` (kernel not present in the checkout that serves the hook — the frontmatter points at `$CLAUDE_PROJECT_DIR`, i.e. the main checkout) and any guard exception → `("allow", None)`. Only an explicit `block` denies.
- Pass the checkout root (`repository_paths(cwd)[0]`) as `worktree` — kernel plans are repo-relative; the bash `cwd` may be a sub-directory.
- The rewrite must keep the command executable from the original `cwd`: the kernel's `guard_bash` owns segment rewriting (spec R2); verify its output is cwd-independent before wrapping (FILL IN below).
- Keep the `timeout`/`description`/other `tool_input` fields exactly as today (existing test L104).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py:158-179` — hook to extend
- `.claude/agents/sdd-coder.md:16-22` — how the hook is invoked (system `python3`, script path)

---

## Implementation Blueprint

### Steps (in order)
1. Verify TASK-3309 (`guard_bash`) and TASK-3312 (`_write_attempt_scope`) are merged — *why*: this task only wires them.
2. Add `_load_guard_bash` and `_scope_guard` to `worktree_environment.py` above `hook_response` — *why*: keep the hook body small and the loader testable.
3. Apply the guard in `hook_response` before `protected_argv` — *why*: spec M7 order; a block must never be sandbox-wrapped.
4. Call `_write_attempt_scope` in `prepare_native` — *why*: the native seat's first Bash call must see the context.
5. Add tests, run Validation Commands — *why*: AC5 native half, AC13.

### `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def hook_response(payload: dict\[str, Any\]) -> dict\[str, Any\]:' worktree_environment.py)
# BEFORE — insert immediately above `def hook_response(payload: dict[str, Any]) -> dict[str, Any]:` (verified: worktree_environment.py:158)
def _load_guard_bash() -> Any:
    """Import the stdlib-only test-scope guard without importing Parrot.

    Returns:
        The kernel's ``guard_bash`` callable.

    Raises:
        ImportError: The checkout serving this hook has no test-scope kernel.
    """
    if __package__:
        from .test_scope.guard import guard_bash
    else:  # run as a script: this file's directory is sys.path[0]
        from test_scope.guard import guard_bash
    return guard_bash


def _scope_guard(command: str, cwd: Path) -> tuple[str, str | None]:
    """Decide whether a native Bash command runs an over-broad pytest (FEAT-563).

    Args:
        command: The Bash command the seat issued.
        cwd: The hook's working directory.

    Returns:
        ``("allow", None)``, ``("rewrite", <command>)`` or ``("block", <message>)``.
        Import failures and guard errors always yield ``("allow", None)``.
    """
    try:
        guard_bash = _load_guard_bash()
        root, _common = repository_paths(cwd)
        outcome, rewritten = guard_bash(command, worktree=root)
    except Exception:  # noqa: BLE001 — the sandbox wrapper must never break
        return "allow", None
    if outcome.action == "block":
        return "block", outcome.message
    if outcome.action == "rewrite" and rewritten:
        # FILL IN: if the kernel's rewritten command is root-relative and cwd != root, make it runnable from cwd
        #          (e.g. prefix `cd <root> &&` only when the original command was a lone pytest) — bounded by spec R2
        #          ("never break a command")
        return "rewrite", rewritten
    return "allow", None


```
```python
# occurrences: 1 (verified: grep -c 'wrapped = protected_argv(cwd, \["/bin/bash", "-c", command\])' worktree_environment.py)
# BEFORE — insert immediately above `            wrapped = protected_argv(cwd, ["/bin/bash", "-c", command])` (verified: worktree_environment.py:168)
            action, value = _scope_guard(command, cwd)
            if action == "block":
                raise ValueError(value or "over-broad pytest blocked by the test-scope guard")
            if action == "rewrite" and value:
                command = value
```
**Why this shape**: `hook_response` already turns `ValueError` into a deny, so a block reuses the established rendering. `_scope_guard` swallows every failure so the bubblewrap wrap (the security-critical part) is never skipped because of the optional guard. The loader's two branches keep the kernel under one class identity per process.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'path = await manager.create(worker_id)' sdd_coder/engine.py)
# AFTER — insert below `        path = await manager.create(worker_id)` (verified: sdd_coder/engine.py:1285)
        await self._write_attempt_scope(path, task_id, planned.task_file, ctx.feature_branch)
```
**Why**: `prepare_native` hands `path` to `sdd-worker`, which launches the native seat there; writing first guarantees the hook sees the context on the seat's first Bash call. `_write_attempt_scope` already logs and swallows failures (TASK-3312).

### `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_standalone_hook_denies_invalid_input() -> None:' test_worktree_environment.py)
# AFTER — insert below the end of `test_standalone_hook_denies_invalid_input` (verified: test_worktree_environment.py:222-227)
def test_hook_rewrites_broad_pytest_before_sandbox(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(policy.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(policy, "_scope_guard", lambda command, cwd: ("rewrite", "pytest tests/test_a.py -q"))
    response = policy.hook_response({"cwd": str(checkout[0]), "tool_name": "Bash", "tool_input": {"command": "pytest"}})
    updated = response["hookSpecificOutput"]["updatedInput"]
    assert shlex.split(updated["command"])[-3:] == ["/bin/bash", "-c", "pytest tests/test_a.py -q"]


def test_hook_blocks_with_guard_message(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: _scope_guard → ("block", "no scoped tests"); assert permissionDecision == "deny" and the reason
    #          contains the message; no updatedInput — AC5 / spec R4
    ...


def test_scope_guard_import_error_allows(checkout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: monkeypatch policy._load_guard_bash to raise ImportError; assert policy._scope_guard("pytest", checkout[0])
    #          == ("allow", None) and hook_response still wraps the ORIGINAL command
    ...


def test_standalone_loader_resolves_kernel_by_path() -> None:
    # FILL IN: subprocess [sys.executable, "-S", "-c", ...] with sys.path[0] = dirname(policy.__file__), import
    #          worktree_environment as a top-level module and print _load_guard_bash().__module__ → "test_scope.guard";
    #          proves the script-mode path works with no site-packages (system python3)
    ...
```
**Why**: Monkeypatching `policy._scope_guard` isolates the hook adapter; the kernel's decisions are covered by TASK-3309. The `-S` subprocess test is the only proof the system-python import path works.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)
```python
# FILL IN: disambiguate — insert after `test_engine_writes_attempt_context` (added by TASK-3312); quote its last
#          2–3 lines as the anchor after verifying they are unique — bounded by: serialized after TASK-3312
async def test_prepare_native_writes_attempt_context(git_sandbox_feature, noop_probe):
    """FEAT-563: the native sub-worktree carries a task-tier AttemptContext before sdd-worker launches the seat."""
    from parrot.flows.dev_loop.test_scope.context import read_attempt_context

    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(
        seats=[
            RosterSeat(label="h", kind="native"),
            RosterSeat(label="a", backend="nova", model="model-a"),
            RosterSeat(label="b", backend="codex", model="model-b"),
        ]
    )
    engine = SddCoderEngine(
        roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=fake_builder_factory({})
    )
    plan = await engine.plan("demo", str(worktree))
    native_id = next(t.task_id for t in plan.chunks[0].tasks if t.native)
    prep = await engine.prepare_native("demo", str(worktree), native_id)
    context = read_attempt_context(Path(prep.worktree_path))
    # FILL IN: assert context is not None, tier "task", task_id == native_id, task_file == prep.task_file,
    #          base_ref == feature_branch — AC5
```

### FILL IN checklist
- [ ] `worktree_environment.py::_scope_guard` — cwd-independence of the rewritten command; bounded by spec R2
- [ ] `test_worktree_environment.py` — three test bodies (block, ImportError, `-S` loader); bounded by AC5 / R4
- [ ] `test_engine_dispatch.py` — anchor disambiguation after TASK-3312's test + assertions; bounded by AC5

---

## Acceptance Criteria

- [ ] Inside a native attempt, an over-broad pytest Bash command is rewritten (and still sandbox-wrapped) or denied with the guard message when the plan is empty (spec AC5, native half)
- [ ] Without an attempt context, or when the kernel cannot be imported, `hook_response` output is identical to today
- [ ] `worktree_environment.py` still imports only the standard library at module level
- [ ] `prepare_native` sub-worktrees carry `AttemptContext(tier="task", …, base_ref=<feature branch>)`
- [ ] Existing tests in both modified test files still pass
- [ ] All tests pass (see Validation Commands) (spec AC13)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
def test_hook_rewrites_broad_pytest_before_sandbox(checkout, monkeypatch) -> None: ...
def test_hook_blocks_with_guard_message(checkout, monkeypatch) -> None: ...
def test_scope_guard_import_error_allows(checkout, monkeypatch) -> None: ...
def test_standalone_loader_resolves_kernel_by_path() -> None: ...

# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py
async def test_prepare_native_writes_attempt_context(git_sandbox_feature, noop_probe): ...
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
7. **Move this file** to `tasks/completed/TASK-3313-native-hook-guard.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
