# TASK-5293: Engine-process registry callers load from the attempt base ref

**Feature**: FEAT-834 — runner registry loads from a trusted ref; runner cwd stays in the worktree
**Spec**: `sdd/specs/runners-registry-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5292
**Assigned-to**: unassigned
**Discovered-from**: `issue:29e8e7ad138f`

---

## Context

Spec §2 (Module 2). Three load sites run in the engine/dispatcher process against a seat-writable attempt
worktree: the test-scope guard (reached from `dispatchers/llm.py::_tool_run_command`), the background
validation supervisor, and the engine's runner-binaries profile extension. With TASK-5292's `ref=`, each must
read the registry from the attempt base ref, which lives in the shared `.git` that seats cannot write.

---

## Scope

- `guard._runner_for(argv, *, worktree)`: `ctx = read_attempt_context(worktree)`; with a ctx use
  `load_registry(worktree, ref=ctx.base_ref)`, without one use `RunnerRegistry({}, {})` (built-ins, no TOML
  read). `ValueError` → `None` (unchanged).
- `guard._task_plan(worktree)`: build `registry = load_registry(worktree, ref=ctx.base_ref)` (on `ValueError`
  return `None`) and pass `registry=registry` to `plan_tests`.
- `background.py` (inside `ValidationSupervisor.start`): `load_registry(worktree, ref=base_ref if tier == "task" else None)`
  — task tier always carries the fork-SHA `base_ref`; merge/feature tiers run in the feature worktree.
- `engine._profile_with_runner_binaries(self, profile, path, *, ref: str | None = None)`:
  `load_registry(Path(path), ref=ref)`; attempt call site passes `ref=ctx.feature_branch`.
- Tests listed under Test Specification.

**NOT in scope**: `dispatchers/llm.py` (unchanged — it already calls `guard_argv`); seat-side callers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py` | MODIFY | load registry from `ctx.base_ref` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | task tier loads from `base_ref` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `ref=` on profile helper + call site |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py` | MODIFY | guard ignores working-tree TOML |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_capability.py` | MODIFY | profile helper honours `ref` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# guard.py:10-15
from .context import read_attempt_context
from .runners.registry import load_registry          # add RunnerRegistry to this import
from .select import changed_files, plan_tests
# background.py:55
from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry, load_registry
# engine.py:95
from parrot.flows.dev_loop.test_scope.runners.registry import load_registry
```

### Existing Signatures to Use
```python
def load_registry(worktree: Path, *, ref: str | None = None) -> RunnerRegistry   # created by TASK-5292
class RunnerRegistry: __init__(self, adapters, settings)                        # registry.py:23
def read_attempt_context(worktree: Path) -> AttemptContext | None               # test_scope/context.py:61
AttemptContext.base_ref: str                                                     # test_scope/datatypes.py:233
def _runner_for(argv, *, worktree: Path) -> RunnerAdapter | None                 # guard.py:34; load at :37 (1 occurrence)
def _task_plan(worktree: Path) -> ScopePlan | None                               # guard.py:42; `return plan_tests(` at :52 (1 occurrence)
def plan_tests(*, worktree, changed_files, tier, declared, ..., registry=None)   # select.py:157 uses `registry or load_registry(worktree)`
# background.py:611 (1 occurrence), inside start(..., tier, ..., base_ref: Optional[str] = None, ...):
            runner_registry = await asyncio.to_thread(load_registry, worktree)
# engine.py:1439 / :1448 / :3765 (1 occurrence each)
    def _profile_with_runner_binaries(self, profile: Any, path: str) -> Any:
            binaries = load_registry(Path(path)).binaries
            profile = self._profile_with_runner_binaries(profile, path)   # ctx.feature_branch in scope (engine.py:3745)
# test_engine_capability.py:26
    out = _bare_engine()._profile_with_runner_binaries(profile, str(tmp_path))
```

### Does NOT Exist
- No `trusted_ref` attribute on `_FeatureCtx`; use `ctx.feature_branch`.
- `plan_tests` has no `ref=` parameter; pass a pre-built `registry=`.
- `guard_argv` has no `ref=`/`base_ref=` parameter and must not gain one (the dispatcher API stays unchanged).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_capability.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py#_runner_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py#_task_plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._profile_with_runner_binaries"
  ]
}
```

---

## Implementation Notes

- No attempt context → built-ins only, never the working-tree TOML — because without a context the guard
  allows everything anyway, and reading the TOML there would reopen the hole.
- Keep `ref` optional on `_profile_with_runner_binaries` — because the existing test calls it positionally.

---

## Implementation Blueprint

### `guard.py`
```python
from .runners.registry import RunnerRegistry, load_registry


def _runner_for(argv: Sequence[str], *, worktree: Path) -> RunnerAdapter | None:
    """Return the registered runner for ``argv``, or None when registry loading fails.

    The registry is read from the attempt base ref, never the seat-writable working tree.
    """
    ctx = read_attempt_context(worktree)
    try:
        registry = load_registry(worktree, ref=ctx.base_ref) if ctx is not None else RunnerRegistry({}, {})
        return registry.adapter_for_argv(argv)
    except ValueError:
        return None
```
`_task_plan`: after the ctx check, `try: registry = load_registry(worktree, ref=ctx.base_ref) except ValueError: return None`, then `plan_tests(..., registry=registry)`.

### `background.py` (line 611)
```python
            runner_registry = await asyncio.to_thread(
                load_registry, worktree, ref=base_ref if tier == "task" else None
            )
```

### `engine.py`
```python
    def _profile_with_runner_binaries(self, profile: Any, path: str, *, ref: Optional[str] = None) -> Any:
        ...
            binaries = load_registry(Path(path), ref=ref).binaries
    # call site (engine.py:3765)
            profile = self._profile_with_runner_binaries(profile, path, ref=ctx.feature_branch)
```
FILL IN: confirm `Optional` is imported in engine.py (else use `str | None`); update the docstring Args.

### FILL IN checklist
- [ ] Guard tests from Test Specification.
- [ ] Engine test: committed ref without the TOML + working-tree TOML naming a runner binary → binaries unchanged.

---

## Acceptance Criteria

- [ ] AC-4 guard, background (task tier) and engine profile load from the attempt base ref; guard without
  context reads no TOML.
- [ ] Existing `test_guard.py` and `test_engine_capability.py` tests still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_capability.py -q`

---

## Test Specification

- `test_guard_without_context_ignores_worktree_toml`: `tmp_path` (no git) holding a TOML whose `[extensions]`
  names an importable module that records construction; with `_task_plan` monkeypatched to `None`,
  `guard_argv(["pytest"], worktree=tmp_path)` allows and the module is never imported.
- `test_profile_with_runner_binaries_uses_ref`: git repo, committed tree without TOML, working tree TOML with a
  fake extension adding `binaries=("evil",)`; `_profile_with_runner_binaries(profile, wt, ref="HEAD")` leaves
  `allowed_commands` without `"evil"`.

---

## Agent Instructions

1. Work in `feat-FEAT-834-runners-registry-fixes` after TASK-5292 is merged there; run tests with `PYTHONPATH=packages/ai-parrot/src`.
2. Implement from the Blueprint, run the Validation Commands.
3. Commit only the listed files; close with `parrot sdd task close TASK-5293 runners-registry-fixes verified`.

---

## Completion Note

_(fill in on completion)_
