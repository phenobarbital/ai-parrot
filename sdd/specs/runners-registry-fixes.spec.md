---
type: feature
base_branch: dev
feature_id: FEAT-834
projects: [ai-parrot]
tags: [sdd, dev-loop, test-scope, security, ledger-fix]
discovered_from: issue:29e8e7ad138f
docs:
  policy: none
---

# Feature Specification: runner registry loads from a trusted ref; runner cwd stays in the worktree

**Feature ID**: FEAT-834
**Date**: 2026-11-07
**Author**: Jesus Lara (spec drafted with Claude via /sdd-fix)
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger issue `issue:29e8e7ad138f` (vulnerability, major, found by the FEAT-709 review).

`load_registry(worktree)` (`test_scope/runners/registry.py`) reads `.parrot/test_runners.toml` from the
working tree it is given. Its `[extensions]` table names `module:Class` entries that `_extension_adapter`
imports with `importlib.import_module` and constructs with no arguments.

Three callers run inside the engine/dispatcher process, not inside a seat sandbox, and pass a worktree that a
coder seat can write:

- `dispatchers/llm.py::_tool_run_command` → `guard_argv(argv, worktree=Path(cwd))` → `guard._runner_for` and
  `guard._task_plan` → `plan_tests` → `load_registry(<attempt worktree>)`.
- `sdd_coder/background.py::ValidationSupervisor.start` → `load_registry(worktree)` (task tier: the attempt
  worktree).
- `sdd_coder/engine.py::_profile_with_runner_binaries` → `load_registry(Path(path))` (the attempt worktree).

A seat that writes `.parrot/test_runners.toml` into its attempt worktree therefore makes the engine import a
module and run its constructor (and extend the seat's `allowed_commands` with that adapter's `binaries`). The
fidelity gate rejects an undeclared file only after the attempt ends, too late.

Separately, `VitestAdapter` uses `settings["cwd"]` without checking that it stays inside the worktree
(`mirror_targets` resolves `worktree / settings["cwd"]`; `invocation` passes it through as `Invocation.cwd`).
An absolute path or `../..` points the runner outside the checkout.

### Goals

- Engine-process callers never read the runner TOML from a seat-writable working tree. They read it from a git
  ref the seat cannot move: the attempt's base (feature branch or fork SHA). Seats cannot write `.git`.
- A runner `cwd` setting that is absolute or escapes the worktree is rejected, at load time and in
  `VitestAdapter`.

### Non-Goals (explicitly out of scope)

- No change to the TOML schema or to the extension mechanism itself (a committed, reviewed TOML may still name
  extensions).
- Seat-side callers (`select_tests.py`, `check_task_graph.py`, `cache_test_contract.py`, `planner.py`,
  `select.py` defaults) keep reading the working tree: they run inside the seat's own sandbox.
- No change to the fidelity gate.

---

## 2. Architectural Design

### `load_registry(worktree, *, ref=None)`

- `ref is None`: unchanged (read `<worktree>/.parrot/test_runners.toml`).
- `ref` set: read the TOML from git with `git -C <worktree> show <ref>:.parrot/test_runners.toml`.
  - `ref` must be non-empty and must not start with `-` (option injection) → else `ValueError`.
  - `git rev-parse --verify --quiet <ref>^{commit}` fails → `ValueError` (fail closed, never fall back to the
    working tree).
  - the path is absent at `ref` (`git cat-file -e <ref>:<path>` fails) → empty `RunnerRegistry({}, {})`.
  - the content is parsed and validated by the same code path as the working-tree read.
- Stdlib only (`subprocess`), so `test_stdlib_only.py` keeps passing.

### `cwd` containment

- `load_registry` rejects any runner `cwd` setting that is absolute, or whose normalized form is `..` or starts
  with `../` → `ValueError("<CONFIG_PATH>: runner <kind> cwd must stay inside the worktree")`.
- `VitestAdapter` gets one private helper `_contained_cwd(worktree, settings) -> Path` that resolves
  `worktree / settings["cwd"]` and raises `ValueError` unless it is inside `worktree.resolve()`.
  `mirror_targets` and `invocation` use it; `validate_settings` reports an escaping `cwd` as a diagnostic
  instead of raising.

### Callers

- `guard._runner_for(argv, *, worktree)`: read `read_attempt_context(worktree)`. With a context, load
  `load_registry(worktree, ref=ctx.base_ref)`; without one, use the built-ins only
  (`RunnerRegistry({}, {})`) — no TOML is read.
- `guard._task_plan(worktree)`: pass `registry=load_registry(worktree, ref=ctx.base_ref)` to `plan_tests`
  (a `ValueError` from loading → return `None`, i.e. guard inactive, as today for a broken guard).
- `background.ValidationSupervisor.start`: `load_registry(worktree, ref=base_ref if tier == "task" else None)`.
  Task tier always has a fork-SHA `base_ref` (already enforced). Merge/feature tiers run in the feature
  worktree, which seats do not write.
- `engine._profile_with_runner_binaries(profile, path, *, ref)`: `load_registry(Path(path), ref=ref)`; the
  attempt call site passes `ctx.feature_branch` (the same base `_write_attempt_scope` records).

---

## 3. Module Breakdown

### Module 1: trusted-ref registry + cwd containment
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/vitest.py`
- **Responsibility**: `ref=` support in `load_registry`; `cwd` validation at load; `VitestAdapter._contained_cwd`.

### Module 2: engine-process callers pass the trusted ref
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/guard.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
- **Responsibility**: the three engine-process load sites use the attempt base ref.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_load_registry_from_ref_ignores_working_tree_toml` | M1 | git repo with a committed TOML; working tree rewritten with an `[extensions]` entry; `load_registry(wt, ref="HEAD")` returns the committed settings and imports nothing |
| `test_load_registry_from_ref_without_config_is_empty` | M1 | ref without the file → built-ins only, even when the working tree has one |
| `test_load_registry_rejects_bad_ref` | M1 | unknown ref and a `-`-prefixed ref → `ValueError` |
| `test_load_registry_rejects_escaping_cwd` | M1 | `cwd = "/etc"` and `cwd = "../x"` → `ValueError` |
| `test_vitest_rejects_cwd_outside_worktree` | M1 | `mirror_targets` / `invocation` raise; `validate_settings` returns a diagnostic |
| `test_guard_without_context_ignores_worktree_toml` | M2 | a worktree TOML with a broken extension does not make the guard import it |
| existing `test_guard.py`, `test_runners_registry.py`, `test_runner_vitest.py`, `test_stdlib_only.py` | M1/M2 | unchanged and passing |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_vitest.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py
markers: none

### Test Data / Fixtures

Tests build throwaway git repos under `tmp_path` (`git init`, commit, then edit the working tree).

---

## 5. Acceptance Criteria

- [ ] AC-1 With `ref` set, `load_registry` never reads the working-tree TOML and never imports an extension that
  exists only there.
- [ ] AC-2 An unknown or `-`-prefixed `ref` raises `ValueError`; a ref without the file yields built-ins only.
- [ ] AC-3 A runner `cwd` that is absolute or escapes the worktree is rejected by `load_registry` and by
  `VitestAdapter`.
- [ ] AC-4 `guard`, `background.ValidationSupervisor.start` (task tier) and `engine._profile_with_runner_binaries`
  load the registry from the attempt base ref; the guard without an attempt context reads no TOML.
- [ ] AC-5 Validation Contract tests pass; `ruff check` clean on the changed files.

---

## 6. Codebase Contract

- `CONFIG_PATH = ".parrot/test_runners.toml"` — `registry.py:14`.
- `_extension_adapter(kind, target) -> RunnerAdapter` — `registry.py:117`.
- `load_registry(worktree: Path) -> RunnerRegistry` — `registry.py:133`.
- `VitestAdapter.mirror_targets(changed, *, worktree, settings)` uses `(worktree / settings["cwd"]).resolve()` —
  `vitest.py:42-44`; `invocation(...)` returns `cwd=settings["cwd"]` — `vitest.py:66-90`;
  `validate_settings(settings, *, worktree)` — `vitest.py:114`.
- `guard._runner_for(argv, *, worktree)` — `guard.py:34`; `guard._task_plan(worktree)` — `guard.py:42`;
  `guard_argv` — `guard.py:60`.
- `read_attempt_context(worktree) -> AttemptContext | None` — `test_scope/context.py:61`;
  `AttemptContext.base_ref: str` — `test_scope/datatypes.py:227-233`.
- `plan_tests(..., registry=...)` uses `registry or load_registry(worktree)` — `test_scope/select.py:157`.
- `ValidationSupervisor.start(..., tier, ..., base_ref=None, ...)`; task tier requires `base_ref` —
  `sdd_coder/background.py:557`; registry load — `background.py:611`.
- `SddCoderEngine._profile_with_runner_binaries(self, profile, path)` — `sdd_coder/engine.py:1439`; call site
  `engine.py:3765`, with `ctx.feature_branch` in scope (`engine.py:3745`).
- `_tool_run_command` → `guard_argv(argv, worktree=Path(cwd))` — `dispatchers/llm.py:1968` (unchanged).

---

## 7. Implementation Notes & Constraints

- `registry.py` and `vitest.py` stay stdlib-only.
- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`.

---

## 8. Open Questions

None.

---

## Revision History

| Rev | Date | Change |
|---|---|---|
| 0.1 | 2026-11-07 | Initial spec from ledger issue `issue:29e8e7ad138f` |
