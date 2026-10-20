# TASK-4520: Kernel datatypes: `Invocation` hard cut and runner-aware result types

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models and §3 Module 2 (datatypes half). Every later task builds on the
runner-tagged `Invocation`, `TestTarget.runner`, `RunReport`, `Failure`, `RunnerSummary` and
`ValidationVerdict`. `PytestInvocation` is renamed to `Invocation` as a **hard cut** (no alias —
memory "no external consumers; hard cuts OK"); this task updates every in-repo reference so the
tree stays green. `TestContract`'s shape is NOT changed here (TASK-4522 owns it).

---

## Scope

- Rename `PytestInvocation` → `Invocation` in `test_scope/datatypes.py` and add the fields `runner="pytest"`, `cwd="."`, `report_path=""`, `report_format="junit"`, `timeout_s=0` (all defaulted so existing constructions keep working).
- Add `TestTarget.runner: str = "pytest"` (last field, defaulted).
- Add the frozen stdlib dataclasses `RunReport`, `Failure`, `RunnerSummary`, `ValidationVerdict` exactly as spec §2 Data Models (field order fixed).
- Update every reference to `PytestInvocation` (source + tests listed below) and the `test_scope/__init__.py` exports; rename `test_scope/models.py` `PytestInvocationModel` → `InvocationModel` and add the new fields to it.
- Fix the docstring reference in `nodes/qa.py:581`.

**NOT in scope**: `TestContract` schema 2 (TASK-4522); `with_junit`/`suite_name` behaviour (TASK-4523); any planner logic change (TASK-4524).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` | MODIFY | rename + new dataclasses |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` | MODIFY | exports |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | type rename only |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | type rename only |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py` | MODIFY | InvocationModel rename + fields |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | type rename only (string annotations) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | docstring rename |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_datatypes_runners.py` | CREATE | new dataclass tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_models.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py` | MODIFY | rename |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_merge_scope_and_bg_wait.py` | MODIFY | rename |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | rename |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation, ScopePlan, TestTarget  # datatypes.py:11,22,42 (PytestInvocation goes away here)
from parrot.flows.dev_loop.test_scope.models import PytestInvocationModel  # test_scope/models.py:21 (renamed here)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py
@dataclass(frozen=True)
class TestTarget:            # line 11 — path, distribution, reason
@dataclass(frozen=True)
class PytestInvocation:      # line 22 — distribution, argv, targets
class ScopePlan:             # line 42 — invocations: tuple[PytestInvocation, ...]
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py:21 and :42 — "PytestInvocation" in the import list and __all__
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py:8 import, :40 return annotation, :57 constructor, :75 docstring, :86 list annotation
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py:20 import, :106 with_junit(invocation: PytestInvocation, …), :127 suite_name(invocation: PytestInvocation)
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py:21 class PytestInvocationModel(BaseModel); :43 invocations: list[PytestInvocationModel]; :59 constructor
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py:60 TYPE_CHECKING import; string annotations at :876,:877,:1022,:1040,:1116,:1148
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:581 docstring mention
```

### Does NOT Exist
- ~~`Invocation`, `RunReport`, `Failure`, `RunnerSummary`, `ValidationVerdict`~~ — created here
- ~~a `PytestInvocation = Invocation` alias~~ — forbidden (hard cut)
- ~~`TestContract.runners`~~ — TASK-4522

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_datatypes_runners.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_mcp.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_merge_scope_and_bg_wait.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_select_tests.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#PytestInvocation",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#TestTarget",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#ScopePlan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py#PytestInvocationModel"
  ]
}
```

---

## Implementation Notes

- Keep the module stdlib-only (`test_stdlib_only.py` guards it).
- Do the rename with an exact-token replace per file, then `grep -rn PytestInvocation packages scripts tests` must return nothing outside `build/`.
- `Mapping` fields in frozen dataclasses follow the `ScopePlan.__post_init__` MappingProxyType pattern (datatypes.py:56-61).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Rename the class and add the defaulted fields — *why*: every constructor call in the tree passes only distribution/argv/targets, so defaults keep them valid.
2. Add the four new dataclasses after `BaselineVerdict` — *why*: TASK-4521/4523/4529 import them and must not redefine shapes.
3. Replace every `PytestInvocation` token in the listed files — *why*: hard cut, no alias.
4. Write `test_datatypes_runners.py` — *why*: freezes defaults and immutability.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class PytestInvocation:' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py)
# REPLACE the class at datatypes.py:22-27 with:
@dataclass(frozen=True)
class Invocation:
    """One runner command for exactly one (runner, distribution) group (FEAT-709)."""

    distribution: str
    argv: tuple[str, ...]
    targets: tuple[TestTarget, ...]
    runner: str = "pytest"
    cwd: str = "."  # repo-relative
    report_path: str = ""  # repo-relative; "" when stdout-parsed
    report_format: str = "junit"  # "junit" | "libtest" | "e2e-verdict" | "exit-code"
    timeout_s: int = 0  # 0 => runner default from settings

# occurrences: 1 (verified: grep -c 'class BaselineVerdict:' …/datatypes.py)
# AFTER — insert below the BaselineVerdict class body (verified: datatypes.py:87-93)
@dataclass(frozen=True)
class RunReport:
    """Normalized outcome of one Invocation, whatever its runner."""

    runner: str
    suite: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_s: float
    exit_code: int
    status: str  # "passed" | "failed" | "timed_out" | "no_report" | "unavailable"
    nodes: tuple[tuple[str, str], ...] = ()
    failure_text: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    unmapped: int = 0

    def __post_init__(self) -> None:
        """Freeze ``failure_text``."""
        # FILL IN: MappingProxyType wrap, same as ScopePlan.__post_init__ (datatypes.py:56-61)


@dataclass(frozen=True)
class Failure:
    """One failed node as a seat sees it."""

    runner: str
    nodeid: str
    verdict: str  # "new_red" | "baseline_red" | "unknown"
    excerpt: str


@dataclass(frozen=True)
class RunnerSummary:
    """Per-invocation counts inside a verdict."""

    runner: str
    suite: str
    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    cached: int
    duration_s: float
    exit_code: int
    status: str


@dataclass(frozen=True)
class ValidationVerdict:
    """The only validation payload a coder seat ever receives (FEAT-709)."""

    schema: int
    status: str  # "passed" | "failed" | "timed_out" | "unavailable" | "blocked"
    tier: str
    runners: tuple[RunnerSummary, ...]
    failures: tuple[Failure, ...]
    cached: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
```
**Why**: The field names and order are fixed by spec §2 Data Models; TASK-4529 serializes them by name. `TestTarget` gains `runner: str = "pytest"` as its LAST field (append after `reason`).

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    PytestInvocation,' …/test_scope/__init__.py) — import list line 21
# REPLACE `    PytestInvocation,` in the `from .datatypes import (` block with:
    Failure,
    Invocation,
    RunnerSummary,
    RunReport,
    ValidationVerdict,
# and in __all__ (line 42) replace "PytestInvocation" with "Invocation", "Failure", "RunReport",
# "RunnerSummary", "ValidationVerdict" — keep __all__ alphabetical (FILL IN: final ordering)
```
**Why**: Exports are the kernel's public surface for path imports (`import test_scope`).

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_datatypes_runners.py` (CREATE)
```python
"""FEAT-709 TASK-4520: runner-aware kernel datatypes."""

import dataclasses

import pytest

from parrot.flows.dev_loop.test_scope.datatypes import (
    Invocation, RunReport, TestTarget, ValidationVerdict,
)


def test_invocation_defaults_are_pytest():
    inv = Invocation(distribution="ai-parrot", argv=("pytest",), targets=())
    assert (inv.runner, inv.cwd, inv.report_format, inv.timeout_s) == ("pytest", ".", "junit", 0)


def test_target_runner_default():
    assert TestTarget(path="x", distribution="d", reason="declared").runner == "pytest"


def test_run_report_failure_text_is_frozen():
    # FILL IN: build a RunReport with failure_text={"n": "t"} and assert item assignment raises TypeError
    ...


def test_verdict_is_frozen():
    verdict = ValidationVerdict(schema=1, status="passed", tier="task", runners=(), failures=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.status = "failed"  # type: ignore[misc]
```
**Why**: Smallest set that freezes the defaults later tasks rely on.

### FILL IN checklist
- [ ] `RunReport.__post_init__` — MappingProxyType wrap; bounded by the ScopePlan pattern
- [ ] `__init__.py` `__all__` ordering — alphabetical
- [ ] every listed test file — token rename only, no behaviour change

---

## Acceptance Criteria

- [ ] `grep -rn PytestInvocation packages/*/src packages/*/tests scripts tests` returns nothing (build/ excluded).
- [ ] All listed existing tests still pass unchanged apart from the rename.
- [ ] `test_stdlib_only.py` passes.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_datatypes_runners.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`
- `pytest tests/sdd_scripts/test_select_tests.py -q`

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
7. Close with `scripts/sdd/close_task.sh TASK-4520 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
