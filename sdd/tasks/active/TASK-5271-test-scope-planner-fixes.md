# TASK-5271: Test-scope planner — contract runner settings reach the invocation

**Feature**: FEAT-829 test-scope-planner-fixes
**Spec**: `sdd/specs/test-scope-planner-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:a3aebc40ef48`

## Context
Implements M1–M3 of the spec. A spec Validation Contract that declares a `parrot-e2e` runner block
with its own `plan:` makes `parrot sdd tests select --tier merge|feature` exit 2 with `error: 'plan'`:
`build_plan()` rebuilds each runner's settings from the registry only (`planner.py:102`) and drops
the contract block's settings that `plan_tests()` used one call earlier; `ParrotE2EAdapter` then
raises `KeyError('plan')` and the whole plan — pytest targets included — fails.

## Scope
- M1: `build_plan()` resolves each `(runner, distribution)` group's settings through a new private
  `_runner_settings(registry, contract, *, runner, distribution, adapter)` helper: registry settings as
  the base, the matching contract block's settings merged on top (block chosen by
  `adapter.distribution_of("", settings=merged) == distribution`, else the first block of that kind;
  no block / no contract → registry settings unchanged).
- M2: `ParrotE2EAdapter.distribution_of()` and `.invocation()` read the plan through a private
  `_plan_setting(settings) -> str` that raises `ValueError` (message names `'plan'` and
  `test_runners.toml`) when the key is absent or empty, instead of `KeyError`.
- M3: regression tests for M1 in `test_planner.py` and for M2 in `test_runner_parrot_e2e.py`.

**NOT in scope**: `issue:3ae0b2ae0ef4` (`ParrotE2EAdapter.operands()` returning `[]` for a task-declared
`parrot e2e run`); `contract.py`; `RunnerRegistry` / `test_runners.toml` loading; the `cargo` /
`vitest` adapters; `green_cache.py` (it already forwards `contract=`).

## Files to Create / Modify
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` (modify — `build_plan` group loop + new `_runner_settings` helper)
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/parrot_e2e.py` (modify — `_plan_setting` helper, `distribution_of`, `invocation`)
- `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` (modify — add tests, keep existing ones)
- `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py` (modify — add one test)

## Codebase Contract (Anti-Hallucination)
Verified against `origin/dev` @ `fa06da14ad`.

**Verified Imports**
- `from parrot.flows.dev_loop.test_scope import TestContract, TestTarget`
- `from parrot.flows.dev_loop.test_scope.datatypes import Invocation, RunnerContract`
- `from parrot.flows.dev_loop.test_scope.planner import build_plan`
- `from parrot.flows.dev_loop.test_scope.runners.registry import RunnerRegistry, load_registry`
- `from parrot.flows.dev_loop.test_scope.runners.base import RunnerAdapter` (Protocol, `base.py:80-82`) — for the helper's type hint; `planner.py` currently imports only `RunnerRegistry, load_registry` from `.runners.registry` (`planner.py:11`)
- `from parrot.flows.dev_loop.test_scope.runners.parrot_e2e import ADAPTER`
- `from parrot.flows.dev_loop.test_scope.select import plan_tests`

**Existing Signatures**
- `build_plan(targets, *, tier, worktree, policy, escalated=(), core_hits=(), skipped_escalations=(), cap_hits=None, cap_impacted=None, notes=(), contract: TestContract | None = None, mode="fallback", registry: RunnerRegistry | None = None) -> ScopePlan` (`planner.py:71-86`). Group loop `planner.py:99-112`: `for runner, distribution in sorted(groups): group = groups[(runner, distribution)]; adapter = registry.adapter_for_kind(runner); settings = registry.settings_for(runner)`; non-pytest runners get `adapter.invocation(group, distribution=..., worktree=..., settings=settings, policy=..., report_path="")`; the pytest branch (`:114-150`) passes the same `settings` to `adapter.invocation` twice (default and permissive targets).
- `RunnerRegistry.settings_for(kind) -> Mapping[str, str]` — returns a fresh `dict` copy (`registry.py:66-68`); `RunnerRegistry({}, {})` lazily resolves the built-in `"pytest"` and `"parrot-e2e"` adapters (`registry.py:30-44`).
- `RunnerContract(kind, targets, settings=MappingProxyType({}), tiers=("task", "merge", "feature"))` frozen dataclass (`datatypes.py:71-85`); `TestContract(schema, runners=None, digest="", *, …)` with `.runners: tuple[RunnerContract, ...]` (`datatypes.py:87-96`).
- `ParrotE2EAdapter.distribution_of(self, target, *, settings) -> str`: `return Path(settings["plan"]).parent.name or "e2e"` (`parrot_e2e.py:135-137`); `invocation(...)`: `owner = settings.get("owner_id", "sdd-coder"); argv = ("parrot", "e2e", "run", "--plan", settings["plan"], "--owner-id", owner)` (`parrot_e2e.py:149-151`); `default_tiers = frozenset({"merge", "feature"})` (`:118`).
- `PytestAdapter.invocation` ignores `settings` (`runners/pytest.py:47-66`).
- `plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None, registry=None) -> ScopePlan` (`select.py:140-148`); for `tier != "task"` it emits one `"contract"` target per operand, or one with `path=""` for a block with no targets, using `runner.settings` for `distribution_of` (`select.py:176-194`), then `build_plan(..., contract=contract, registry=registry)` (`select.py:247-257`).
- Test fixture `FakeAdapter` in `test_planner.py:51-87` (`kind="fake"`, `distribution_of` → `"root"`).
- Existing `test_matches_and_argv` (`test_runner_parrot_e2e.py:64-75`) pins the argv with a plan present.

**Does NOT Exist**
- Any contract-aware settings lookup in `planner.py`.
- A `plan` default in `ParrotE2EAdapter`; `RunnerRegistry({}, {}).settings_for("parrot-e2e") == {}`.
- A `settings` field on `Invocation`.

## Implementation Notes
- `_runner_settings` is pure: `base = dict(registry.settings_for(runner))`; `candidates = [b for b in contract.runners if b.kind == runner]` when `contract is not None`, else `[]`; chosen = first candidate for which `adapter.distribution_of("", settings={**base, **b.settings}) == distribution` (catch `ValueError, KeyError` → not a match), else `candidates[0]` if any; return `{**base, **chosen.settings}` or `base`.
- Call it once per group, replacing `planner.py:102`, and keep passing the result to every `adapter.invocation` call in the loop (pytest included — the pytest adapter ignores it, so pytest `argv` stays byte-identical).
- M2: one module-level `_plan_setting(settings: Mapping[str, str]) -> str`; `distribution_of` and `invocation` call it. Message: `parrot-e2e runner has no 'plan' setting — declare plan: in the spec's runner block or under [runners.parrot-e2e] in .parrot/test_runners.toml`.
- Tests: drive the real adapter through `plan_tests(worktree=tmp_path, changed_files=[], tier="merge", contract=…, registry=RunnerRegistry({}, {}))` — no files need to exist because a `parrot-e2e` block has no targets (`select.py:182` skips the on-disk check for `path == ""`); the pytest block needs its operand file created under `tmp_path` (pattern: `test_plan_groups_contract_targets_by_runner_and_distribution`, `test_planner.py:207-227`).
- Do not touch `contract.py`, `select.py`, `green_cache.py`.

## Acceptance Criteria
Spec AC-1..AC-6.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_parrot_e2e.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`

Run from the worktree root with `PYTHONPATH=$PWD/packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

## Test Specification
- `test_planner.py`: `test_contract_e2e_block_settings_reach_invocation` (AC-1: empty registry, contract
  pytest + parrot-e2e blocks → e2e invocation argv/distribution, pytest invocation present, no exception);
  `test_contract_block_settings_override_registry_settings` (AC-2: registry plan + owner_id, block plan only →
  block plan, registry owner_id); `test_two_e2e_blocks_keep_their_own_plan` (AC-3); `test_fallback_mode_uses_registry_settings`
  (AC-4: `contract=None` with registry plan → registry plan).
- `test_runner_parrot_e2e.py`: `test_missing_plan_is_value_error` (AC-5: `{}` and `{"plan": ""}` for both
  `distribution_of` and `invocation`; message contains `'plan'` and `test_runners.toml`).

## Agent Instructions
Lint the changed files with `ruff check` before committing. Stage only the four files listed above.

## Completion Note
<!-- Filled in when the task is closed. -->
