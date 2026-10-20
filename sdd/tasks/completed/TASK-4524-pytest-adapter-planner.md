# TASK-4524: Pytest adapter and runner-aware planner / select / mirror

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4521, TASK-4522, TASK-4523
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (planner half). Moves pytest-specific argv building (`AGENT_FLAGS`, `-m`, `-n auto`,
`--confcutdir`) into `runners/pytest.py`, makes `build_plan` group per `(runner, distribution)` and makes
`plan_tests` plan non-pytest contract blocks and declared commands through the registry. **Regression bar**:
for a pytest-only contract the produced argv tuples are byte-identical to FEAT-699.

---

## Scope

- Create `runners/pytest.py` with module-level `ADAPTER = PytestAdapter()` delegating to the existing `contract.py`/`mirror.py`/`planner.py` helpers.
- `plan_tests(..., registry=None)`: declared commands are classified via `registry.adapter_for_argv` (non-pytest operands become targets with that runner); contract runner blocks other than pytest add `reason="contract"` targets; a runner not eligible for the tier ⇒ note, skipped.
- `build_plan(..., registry)`: group by `(target.runner, distribution)`; pytest groups keep today's contract/default/markers split; other runners call `adapter.invocation(...)`.
- `mirror.py`: no behaviour change for pytest; expose nothing new (vitest mirror lives in its adapter).

**NOT in scope**: Guard (TASK-4525); vitest/cargo/e2e adapters (TASK-4526..4528); cache/baseline scoping (TASK-4525).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/pytest.py` | CREATE | pytest adapter |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | per-runner grouping |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | registry-aware planning |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_pytest.py` | CREATE | adapter tests + byte-identical regression |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` | MODIFY | grouping tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from ..contract import _pytest_operands, is_broad_pytest, normalize_pytest_argv  # contract.py:91,151,66
from ..mirror import pytest_file_targets, distribution_of  # mirror.py:84,166
from ..policy import AGENT_FLAGS, ScopePolicy  # policy.py:8,82
from ..report import parse_junit_report  # TASK-4523
from .base import RunnerAdapter  # TASK-4521
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py
PER_DIST_EXTRA_ARGS = ("--confcutdir", "{worktree}")                 # line 13
def marker_expression_for(targets, *, contract, policy) -> str           # line 21
def _invocation(distribution, targets, *, worktree, policy, marker_expression=None)   # line 32
#   line 56: argv = ("pytest", *AGENT_FLAGS, "-m", expression, *xdist, *extra, *kept_paths)
def build_plan(targets, *, tier, worktree, policy, escalated=(), core_hits=(), skipped_escalations=(), cap_hits=None, cap_impacted=None, notes=(), contract=None, mode="fallback") -> ScopePlan  # line 59
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
def _declared_targets(declared, notes, *, worktree) -> list[str]        # line 91
def plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None) -> ScopePlan  # line 123
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py:84 pytest_file_targets ; :166 distribution_of
```

### Does NOT Exist
- ~~`runners/pytest.py`~~ — created here
- ~~`plan_tests(registry=…)`~~ — added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/pytest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_pytest.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#build_plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#_invocation",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#_declared_targets",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py#is_broad_pytest"
  ]
}
```

---

## Implementation Notes

- `registry=None` ⇒ `load_registry(worktree)` (absent TOML ⇒ built-ins).
- `_invocation` stays in planner.py as the pytest adapter's implementation detail (adapter calls it) — moving the code is not required; byte-identity is.
- Non-pytest declared commands: TODAY `_declared_targets` silently ignores them (contract.py:141 docstring). Now they become targets; their invocations use `distribution = adapter.distribution_of(...)`.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Write the regression test FIRST capturing current argv tuples for 3 representative plans — *why*: byte-identity bar.
2. Create `PytestAdapter` delegating to existing helpers — *why*: no logic duplication.
3. Rework `build_plan` grouping — *why*: per-runner invocations.
4. Teach `plan_tests` about non-pytest declared/contract targets — *why*: spec §2 Overview.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/pytest.py` (CREATE)
```python
"""Pytest runner adapter (FEAT-709 M3). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..contract import _pytest_operands, is_broad_pytest
from ..datatypes import Invocation, RunReport, TestTarget
from ..mirror import distribution_of, pytest_file_targets
from ..policy import TIERS, ScopePolicy
from ..report import parse_junit_report


class PytestAdapter:
    kind = "pytest"
    binaries = ("pytest", "python", "python3")
    default_tiers = frozenset(TIERS)
    report_format = "junit"

    def matches(self, argv: Sequence[str]) -> bool:
        return bool(argv) and Path(argv[0]).name == "pytest"

    def operands(self, argv: Sequence[str]) -> list[str] | None:
        return _pytest_operands(argv)

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool:
        return is_broad_pytest(argv, worktree=worktree)

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]:
        return pytest_file_targets(list(changed), str(worktree))

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str:
        return distribution_of(target)

    def invocation(self, targets: Sequence[TestTarget], *, distribution: str, worktree: Path,
                   settings: Mapping[str, str], policy: ScopePolicy, report_path: str) -> Invocation:
        # FILL IN: delegate to planner._invocation (import inside the method to avoid a cycle) and
        #          return dataclasses.replace(inv, report_path=report_path) — argv MUST stay byte-identical
        raise NotImplementedError

    def parse_report(self, *, report_path: Path | None, exit_code: int, stdout: str, stderr: str,
                     duration_s: float, timed_out: bool, suite: str) -> RunReport:
        # FILL IN: parse_junit_report(report_path, runner="pytest", …); report_path None ⇒ "no_report"
        raise NotImplementedError

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]:
        return [f"pytest: unknown setting {k!r}" for k in settings if k not in {"markers", "timeout_s", "tiers"}]


ADAPTER = PytestAdapter()
```
**Why**: `ADAPTER` is the module attribute the registry's lazy loader reads (TASK-4521).

### FILL IN checklist
- [ ] `PytestAdapter.invocation` / `parse_report`
- [ ] `build_plan` grouping per `(runner, distribution)`; pytest path unchanged
- [ ] `plan_tests` non-pytest declared + contract blocks; tier-ineligible note
- [ ] byte-identical regression test over three plans (declared-only, contract, contract+markers)

---

## Acceptance Criteria

- [ ] pytest-only plans are byte-identical to the pre-change argv tuples (regression test).
- [ ] A contract with a pytest and a fake second runner yields one invocation per `(runner, distribution)`.
- [ ] A non-pytest declared command produces targets for its runner (no longer silently dropped).
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_pytest.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4524 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator); implemented by gpt-5.6-terra (codex), attempt 1, 627.6s
**Date**: 2026-10-20
**Notes**: Merge-tier validation: test_planner marker-order assertion fixed in 7967c8710 (review fix); remaining reds: 5 pre-existing bwrap failures + test_background_contract.py (owned by TASK-4530). Closed via close_task.sh.

**Deviations from spec**: none
