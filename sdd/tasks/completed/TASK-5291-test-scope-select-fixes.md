# TASK-5291: Test-scope selector — plan a task-declared `parrot e2e run`, report an operand-less command

**Feature**: FEAT-833 test-scope-select-fixes
**Spec**: `sdd/specs/test-scope-select-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none (external: FEAT-829 / PR #2009 merged into the worktree first)
**Assigned-to**: unassigned
**Discovered-from**: `issue:3ae0b2ae0ef4`

## Context
Implements M1–M3 of the spec. A task-declared `parrot e2e run --plan <plan>` Validation Command is
silently dropped by the selector: `ParrotE2EAdapter.operands()` returns `[]` for a matching argv and
`_declared_targets()` only emits targets per operand, with no note for the empty case. The worktree
must contain FEAT-829's commits (`_plan_setting`, `planner._runner_settings`) before this task starts.

## Scope
- M1 (`runners/parrot_e2e.py`): `operands()` returns `[<plan>]` from `--plan <path>` / `--plan=<path>`
  (`[]` without `--plan`, `None` when not matching); `distribution_of()` uses the target when non-empty,
  else `_plan_setting(settings)`; `invocation()` uses the first non-empty `target.path`, else
  `_plan_setting(settings)`.
- M2 (`select.py`): `_declared_targets()` appends `declared command has no operands, dropped: <argv>`
  when `adapter.operands(argv)` is an empty list, then continues.
- M3: tests in `test_runner_parrot_e2e.py` (AC-1..AC-3) and `test_planner.py` (AC-4..AC-6).

**NOT in scope**: `issue:dee91130fa06`; `check_task_graph`; `planner._runner_settings`; the `cargo` /
`vitest` adapters; `contract.py`.

## Files to Create / Modify
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/parrot_e2e.py` (modify — `operands`, `distribution_of`, `invocation`, one private `_plan_operand(argv)` helper)
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` (modify — `_declared_targets` only)
- `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py` (modify — add tests)
- `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` (modify — add tests, keep existing ones)

## Codebase Contract (Anti-Hallucination)
Verified against `origin/dev` @ `8e45e381e1` (`select.py`) and `origin/feat-FEAT-829-test-scope-planner-fixes`
@ `8b77d1761d` (`runners/parrot_e2e.py`, `test_planner.py`).

**Verified Imports**
- `from parrot.flows.dev_loop.test_scope import TestContract, TestTarget`
- `from parrot.flows.dev_loop.test_scope.datatypes import Invocation, RunnerContract`
- `from parrot.flows.dev_loop.test_scope.runners.parrot_e2e import ADAPTER, parse_e2e_verdict`
- `from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry`
- `from parrot.flows.dev_loop.test_scope.select import plan_tests`

**Existing Signatures**
- `ParrotE2EAdapter.matches(argv)` (`parrot_e2e.py:130-132`); `operands(argv)`: `return [] if self.matches(argv) else None` (`:134-136`); `distribution_of(self, target, *, settings)`: `return Path(_plan_setting(settings)).parent.name or "e2e"` (`:146-148`); `invocation(...)`: `owner = settings.get("owner_id", "sdd-coder"); argv = ("parrot", "e2e", "run", "--plan", _plan_setting(settings), "--owner-id", owner)` (`:160-162`).
- `_plan_setting(settings) -> str` raises `ValueError` for absent/empty plan (`parrot_e2e.py:111-119`).
- `_declared_targets(declared, notes, *, worktree, registry=None, tier="task")` (`select.py:91-124`): the operand loop is `for operand in adapter.operands(argv) or ():` (`:115`); notes at `:110`, `:113`, `:121`.
- `plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None, registry=None) -> ScopePlan` (`select.py:140`); `plan.notes`, `plan.invocations`.
- `TestTarget(path, distribution, reason, runner=...)`; `Invocation(distribution, argv, targets, runner, report_path, report_format)`.
- `test_planner.py` already defines `_e2e_block(plan)`, `_pytest_block(tmp_path, path)`, `_e2e_invocations(plan)` (FEAT-829) and `test_non_pytest_declared_command_produces_runner_target` (`declared=(("fake-test", "tests/test_fake.py"),)` pattern).
- `test_runner_parrot_e2e.py` imports `pytest` and `Path`; `test_matches_and_argv` pins the argv with a settings plan and `targets=[]`.

**Does NOT Exist**
- `--plan` parsing anywhere in `parrot_e2e.py`; a note for an operand-less declared command in `select.py`.
- A `plan` attribute on `Invocation` / `TestTarget`.

## Implementation Notes
- `_plan_operand(argv: Sequence[str]) -> str | None`: scan `argv[3:]`; `--plan=<v>` → `<v>`; `--plan` followed by a value → that value; else `None`. `operands()` → `[plan] if plan else []` for a matching argv.
- `distribution_of`: `Path(target or _plan_setting(settings)).parent.name or "e2e"`.
- `invocation`: `plan = next((t.path for t in targets if t.path), None) or _plan_setting(settings)`.
- `select.py`: compute `operands = adapter.operands(argv)` once; `if operands is not None and not operands: notes.append(f"declared command has no operands, dropped: {' '.join(argv)}"); continue`; keep the existing loop over `operands or ()`.
- Tests use `RunnerRegistry({}, {})` (built-ins resolve lazily) and `tmp_path`; no files need to exist for a `parrot-e2e` declared target (`_declared_targets` does not check the disk).

## Acceptance Criteria
Spec AC-1..AC-7.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py -q`

Run from the worktree root with `PYTHONPATH=$PWD/packages/ai-parrot/src`.

## Test Specification
- `test_runner_parrot_e2e.py`: `test_operands_surface_the_plan` (AC-1, parametrized over `run`/`verify`, `--plan X`/`--plan=X`, no `--plan`, non-matching); `test_distribution_prefers_target` (AC-2); `test_invocation_prefers_target_plan` (AC-3, including `ValueError` with neither).
- `test_planner.py`: `test_declared_e2e_command_is_planned_at_merge_tier` (AC-4 incl. task-tier note); `test_declared_e2e_without_plan_is_reported` (AC-5); `test_declared_plan_and_contract_plan_keep_their_own_invocation` (AC-6).

## Agent Instructions
Merge `origin/feat-FEAT-829-test-scope-planner-fixes` into the worktree before editing. Lint the changed files with `ruff check`. Stage only the four files listed above.

## Completion Note

**Completed by**: Claude Code `/sdd-fix` session (`agent:sdd-fix:b0aaa6fe`)
**Date**: 2026-11-07
**Notes**: Implemented M1–M3 in `6070680528`, on top of `origin/feat-FEAT-829-test-scope-planner-fixes`
(merged into the worktree as `2a6af38c7c`; PR #2009 not yet on `dev` at the time).
- M1: `_plan_operand(argv)` parses `--plan <path>` / `--plan=<path>`; `operands()` returns `[plan]`, `[]`
  without `--plan`, `None` when not matching. `distribution_of()` uses the target when non-empty;
  `invocation()` uses the first non-empty `target.path`, else `_plan_setting(settings)`.
- M2: `_declared_targets()` notes `declared command has no operands, dropped: <argv>` for a matched
  command whose `operands()` is an empty list.
- M3: three adapter tests (AC-1..AC-3) and three `plan_tests` tests (AC-4..AC-6).

Validation (worktree `PYTHONPATH`): `test_runner_parrot_e2e.py` + `test_planner.py` 39 passed;
`test_select.py` + `test_select_contract_mode.py` 13 passed; `ruff check` and `black --check -l 120` clean on
the four files. CLI repro: a task file declaring `parrot e2e run --plan sdd/state/FEAT-581/e2e-plan.md` —
`parrot sdd tests select --tier merge --base origin/dev --task-file … --no-baseline` plans only pytest on
`dev` code and plans `parrot e2e run --plan sdd/state/FEAT-581/e2e-plan.md --owner-id sdd-coder` on this
branch; `parrot e2e run` alone yields the M2 note.

**Deviations from spec**: none.
