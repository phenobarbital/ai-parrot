# TASK-3311: QANode — feature-tier plan via the test-scope kernel

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3310
**Assigned-to**: unassigned

---

## Context

Implements spec **Module 5 — QANode integration** (§3 Module 5, AC4, AC11, AC11b, AC9b/AC9c, R12).
`QANode._default_criteria` currently derives ONE `ShellCriterion` from the private `_pytest_targets`
family and falls back to a bare `pytest` when nothing maps (`nodes/qa.py:579`). After this task:

- the mirror helpers are **moved** (TASK-3304) — the `QANode` classmethods become one-line delegations so the
  existing mirror tests keep passing unchanged;
- `_default_criteria` builds a **feature-tier** `ScopePlan` (mirror of directories ∪ core escalation, deduped
  by the ledger — **never** package suites for a non-core change) and emits **one `ShellCriterion` per
  per-distribution invocation**, carrying agent flags and the marker expression;
- an empty plan yields **no** criterion (warning log) instead of bare `pytest`;
- after the QA report returns, core-escalated criteria that passed are recorded in the ledger (AC9c).

Because criteria are now split per distribution and carry flags, **four** existing command-string assertions
in `test_qa_default_criteria.py` must be updated (lines 83, 109, 142, 277 — verified 2026-09-17), not just the
fallback one mentioned by spec AC4.

---

## Scope

- Replace the bodies of `_pytest_targets`, `_pytest_target_for`, `_deepest_existing_dir`, `_prune_nested` with
  delegations to `parrot.flows.dev_loop.test_scope.mirror` (keep signatures and decorators; shorten docstrings
  to "Delegates to test_scope.mirror.<fn> (FEAT-563)").
- Rewrite the tail of `_default_criteria` (after `files` is computed, `qa.py:571-585`): run
  `plan_tests(..., tier="feature")` via `asyncio.to_thread`; store the plan in `shared["test_scope_plan"]`;
  return one `ShellCriterion` per invocation (`name=f"pytest[{dist}]"`, suffix `" (core escalation)"` when any
  target reason is `"core"`, `command=shlex.join(inv.argv)`); empty plan → `[]` + `self.logger.warning`.
- Before `shared["qa_report"] = report` in `execute` (the SECOND occurrence, `qa.py:416`), record green core
  escalations: for each passed `CriterionResult` whose name ends with `" (core escalation)"`, call
  `record_green_escalation(Path(worktree), [dist], core files of plan.core_hits for dist)` via `asyncio.to_thread`;
  any exception → `self.logger.warning`, never fail QA.
- Remove imports that become unused (`os`, `PurePosixPath`) only if `grep` shows no other use in `qa.py`.
- Update the four existing assertions; add `test_scope/test_qanode_feature_tier.py` (parity + recording).

**NOT in scope**: kernel code (3304–3310), `_get_changed_files` behaviour (unchanged), declared validation
commands for QANode (the dev-loop brief carries no task files → `declared=()`), lint scoping.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | Delegations, feature-tier criteria, ledger recording |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py` | MODIFY | Update 4 command-string assertions |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py` | CREATE | Parity + no-bare-pytest + ledger recording tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py (existing, verified 2026-09-17)
import asyncio                                   # qa.py:22
import os                                        # qa.py:23 (only used by the mirror helpers: 652-698)
import shlex                                     # qa.py:25
from pathlib import PurePosixPath                # qa.py:26 (only used at 644)
from typing import Any, Dict, List, Optional, Tuple, Union   # qa.py:27 (Tuple also used at 1126)
from parrot.flows.dev_loop.models import (AcceptanceCriterion, QAReport, ResearchOutput, ShellCriterion, ...)  # qa.py:40-53

# tests (existing)
from parrot.flows.dev_loop import BugBrief, DevelopmentOutput, QAReport, ResearchOutput   # test_qa_default_criteria.py:15-20
from parrot.flows.dev_loop.models import CodeReviewVerdict, ManualCriterion, ShellCriterion  # :21
from parrot.flows.dev_loop.nodes.qa import QANode                                          # :22
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
class QANode(DevLoopNode):                                                        # L139
    async def execute(self, ctx, ...) -> QAReport:                                # L170
        executable = await self._default_criteria(shared, research)              # L244
        shared["qa_report"] = report                                             # L215 (early skip path) AND L416 (main path)
    async def _default_criteria(self, shared: Dict[str, Any], research: ResearchOutput) -> List[AcceptanceCriterion]:  # L529
        worktree = research.worktree_path                                        # L566
        files = list(dict.fromkeys([*reported, *diffed]))                        # L570
        targets = self._pytest_targets(files, worktree)                          # L578
        command = "pytest " + " ".join(shlex.quote(t) for t in targets) if targets else "pytest"   # L579
        return [ShellCriterion(name="pytest (derived: changed scopes)", command=command)]           # L585
    @classmethod
    def _pytest_targets(cls, files: List[str], worktree_path: str) -> List[str]:  # L588 (body L625-630)
    @classmethod
    def _pytest_target_for(cls, path: str, worktree_path: str) -> Optional[str]:  # L633
    @staticmethod
    def _deepest_existing_dir(tests_root: str, subdirs: Tuple[str, ...], worktree_path: str) -> str:  # L679
    @staticmethod
    def _prune_nested(targets: set) -> List[str]:                                # L703
    @staticmethod
    async def _get_changed_files(worktree_path: str) -> List[str]:              # L724 (unchanged)

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ShellCriterion(_AcceptanceCriterionBase):   # L66 — name: str (L47), command: str (L75), kind="shell"
class CriterionResult(BaseModel):                 # L561 — name: str, kind, exit_code, passed: bool
class QAReport(BaseModel):                        # L573 — passed: bool, criterion_results: List[CriterionResult], lint_passed: bool

# packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py — assertions to update
assert criteria[0].command == ("pytest packages/ai-parrot-tools/tests packages/ai-parrot/tests")          # L83
assert _qa_brief(dispatcher).acceptance_criteria[0].command == "pytest"                                   # L109
assert _qa_brief(dispatcher).acceptance_criteria[0].command == "pytest packages/ai-parrot/tests"          # L142
assert _qa_brief(dispatcher).acceptance_criteria[0].command == (                                          # L277-280
    "pytest packages/ai-parrot/tests/flows/dev_loop " "packages/ai-parrot/tests/loaders/test_new.py")
# helpers: fixtures worktree (L25), ctx (L34), mirrored (L201); _dispatcher (L58), _qa_brief (L69)
```

### Created by dependency tasks (verify on disk before use)
```python
# TASK-3304 parrot/flows/dev_loop/test_scope/mirror.py
def pytest_targets(files, worktree_path) -> list[str]; def pytest_target_for(path, worktree_path) -> str | None
def deepest_existing_dir(tests_root, subdirs, worktree_path) -> str; def prune_nested(targets) -> list[str]
# TASK-3306 parrot/flows/dev_loop/test_scope/context.py
def record_green_escalation(worktree: Path, hit_dists: Sequence[str], core_files: Sequence[str]) -> None
# TASK-3308 parrot/flows/dev_loop/test_scope/__init__.py
def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str, declared=(), policy=None) -> ScopePlan
# ScopePlan.invocations[*].distribution/argv/targets[*].reason ; ScopePlan.core_hits[*].path/distributions
```

### Does NOT Exist
- ~~`QAReport.test_scope_plan`~~ — store the plan in `shared["test_scope_plan"]`, not on the report
- ~~task files / declared validation commands in the dev-loop QA brief~~ — pass `declared=()`
- ~~a bare `pytest` fallback after this task~~ — removed (AC4)
- ~~`ScopePlanModel` usage in QANode~~ — not required; use the dataclass plan directly (models are for JSON boundaries)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode.execute",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._default_criteria",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._pytest_targets",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._pytest_target_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._deepest_existing_dir",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._prune_nested",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#ShellCriterion",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#CriterionResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#QAReport"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Async-first: the kernel is sync → `await asyncio.to_thread(plan_tests, worktree=..., changed_files=..., tier="feature")` (spec §7).
- `self.logger` for the empty-plan warning and ledger failures.

### Key Constraints
- Selection for a **non-core** change must equal today's mirror targets (AC11b parity): the union of targets in
  the returned criteria == `QANode._pytest_targets(files, worktree)` for the same inputs.
- The QANode unit tests use plain (non-git) `tmp_path` worktrees; the kernel degrades (no core detection) — do not
  add git setup to the existing tests.
- Ledger recording must never change `report.passed` and must never raise.
- Do not touch the early-return `shared["qa_report"] = report` at L215.

### References in Codebase
- `nodes/qa.py:529-585` — current derivation (docstring explains the union of reported ∪ diffed files; keep it)
- Spec §2 Tiers table (feature row), R12

---

## Implementation Blueprint

### Steps (in order)
1. Add kernel imports near the other `parrot.flows.dev_loop` imports — *why*: delegations and planning need them.
2. Replace the four mirror helper bodies with delegations — *why*: logic moved verbatim in TASK-3304; tests keep calling the classmethods.
3. Rewrite `_default_criteria`'s tail to the feature-tier plan — *why*: per-dist invocations, flags, no bare pytest.
4. Insert ledger recording before `shared["qa_report"] = report` (main path) — *why*: AC9c "paid once".
5. Update the four assertions and add the new test module — *why*: behaviour changed deliberately.

### `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c 'from parrot.flows.dev_loop.session_state import QaAttemptRecorded' nodes/qa.py)
# AFTER — insert below `from parrot.flows.dev_loop.session_state import QaAttemptRecorded` (verified: qa.py:59)
from parrot.flows.dev_loop.test_scope import plan_tests
from parrot.flows.dev_loop.test_scope import mirror as _scope_mirror
from parrot.flows.dev_loop.test_scope.context import record_green_escalation
```
Also change `from pathlib import PurePosixPath` (qa.py:26, occurrences: 1) to `from pathlib import Path` — FILL IN: keep
`PurePosixPath` / `os` only if grep still finds another use after step 2.

### `nodes/qa.py` (MODIFY) — `_default_criteria` tail
```python
# occurrences: 1 (verified: grep -c 'targets = self._pytest_targets(files, worktree)' nodes/qa.py)
# REPLACE qa.py:578-585 (from `targets = self._pytest_targets(files, worktree)` through
#         `return [ShellCriterion(name="pytest (derived: changed scopes)", command=command)]`) WITH:
        plan = await asyncio.to_thread(plan_tests, worktree=Path(worktree), changed_files=files, tier="feature")
        shared["test_scope_plan"] = plan
        if not plan.invocations:
            self.logger.warning(
                "No test targets derived for %s (feature tier) — no pytest criterion. Notes: %s",
                research.feat_id or research.jira_issue_key,
                "; ".join(plan.notes),
            )
            return []
        criteria: List[AcceptanceCriterion] = []
        for inv in plan.invocations:
            core = any(t.reason == "core" for t in inv.targets)
            criteria.append(
                ShellCriterion(
                    name=f"pytest[{inv.distribution}]" + (" (core escalation)" if core else ""),
                    command=shlex.join(inv.argv),
                )
            )
        self.logger.info("Derived %d feature-tier pytest criteria: %s", len(criteria), [c.command for c in criteria])
        return criteria
```
**Why**: spec M5 skeleton — "Feature-tier ScopePlan → one ShellCriterion per PytestInvocation; [] when the plan is
empty". Update the method docstring's "Returns" to match (FILL IN). `shlex.join` keeps the marker expression quoted.

### `nodes/qa.py` (MODIFY) — mirror delegations
```python
# occurrences: 1 each (verified: grep -c 'def _pytest_targets(cls' / 'def _pytest_target_for(cls' / 'def _deepest_existing_dir(' / 'def _prune_nested(' nodes/qa.py)
# REPLACE each body (keep decorator + signature):
#   _pytest_targets (L588-630):        return _scope_mirror.pytest_targets(files, worktree_path)
#   _pytest_target_for (L633-676):     return _scope_mirror.pytest_target_for(path, worktree_path)
#   _deepest_existing_dir (L679-700):  return _scope_mirror.deepest_existing_dir(tests_root, subdirs, worktree_path)
#   _prune_nested (L703-717):          return _scope_mirror.prune_nested(targets)
```
**Why**: logic lives in the kernel now; 13 mirror tests in `test_qa_default_criteria.py` call these classmethods.

### `nodes/qa.py` (MODIFY) — ledger recording in `execute`
```python
# occurrences: 2 (verified: grep -c 'shared\["qa_report"\] = report' nodes/qa.py) → disambiguate with context (qa.py:413-416):
#             len(manual),
#             files_modified,
#         )
#         shared["qa_report"] = report
# INSERT immediately BEFORE that `shared["qa_report"] = report` line:
        await self._record_green_escalations(shared, research, report)
```
Add the helper method next to `_default_criteria`:
```python
    async def _record_green_escalations(self, shared: Dict[str, Any], research: ResearchOutput, report: QAReport) -> None:
        """Record passed core-escalation criteria in the test-scope ledger (FEAT-563 AC9c). Never raises."""
        plan = shared.get("test_scope_plan")
        if plan is None or not plan.core_hits:
            return
        # FILL IN: for r in report.criterion_results if r.passed and r.name.endswith(" (core escalation)"):
        #          dist = r.name[len("pytest["):r.name.index("]")]; files = [h.path for h in plan.core_hits if dist in h.distributions]
        #          await asyncio.to_thread(record_green_escalation, Path(research.worktree_path), [dist], files)
        #          wrap all in try/except Exception → self.logger.warning — bounded by AC9c, "never fail QA"
```

### `packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py` (MODIFY)
```python
# L83 (occurrences: 1): replace single-command assertion with per-distribution expectations:
#   assert [c.name for c in criteria] == ["pytest[ai-parrot-tools]", "pytest[ai-parrot]"]  — FILL IN: order as produced by build_plan
#   assert criteria[0].command.startswith("pytest") and "packages/ai-parrot-tools/tests" in criteria[0].command
# L96-109 test_package_without_tests_is_not_a_target: nothing maps → NO pytest criterion; assert
#   dispatcher.dispatch.await_count == 1 (code review only) — mirror test_docs_only_change_derives_nothing (L113-127)
# L142: assert "packages/ai-parrot/tests" in _qa_brief(dispatcher).acceptance_criteria[0].command
# L277-280: assert both "packages/ai-parrot/tests/flows/dev_loop" and "packages/ai-parrot/tests/loaders/test_new.py"
#   appear in the single ai-parrot criterion command
```

### FILL IN checklist
- [ ] `qa.py` imports — `Path` added; drop `os`/`PurePosixPath` only if unused; bounded by ruff F401
- [ ] `qa.py::_default_criteria` docstring — Returns section matches new behaviour
- [ ] `qa.py::_record_green_escalations` — parse dist from name, core files, to_thread, never raise; bounded by AC9c
- [ ] `test_qa_default_criteria.py` — 4 assertion updates (exact order from `build_plan`)
- [ ] `test_qanode_feature_tier.py` — bodies in Test Specification

---

## Acceptance Criteria

- [ ] All existing tests in `test_qa_default_criteria.py` pass with the 4 updated assertions (AC4)
- [ ] `QANode` never emits a bare `pytest` criterion; empty plan → no criterion (AC4)
- [ ] One `ShellCriterion` per distribution, each carrying agent flags + marker expression (AC2, AC11)
- [ ] Non-core change: union of criterion targets == `QANode._pytest_targets(files, worktree)` (AC11b parity)
- [ ] Passed core-escalation criteria recorded in the ledger; failures or exceptions never change `report.passed` (AC9c)
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py
"""QANode feature tier via the test-scope kernel (FEAT-563 TASK-3311)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import DevelopmentOutput, QAReport, ResearchOutput
from parrot.flows.dev_loop.models import CodeReviewVerdict, CriterionResult
from parrot.flows.dev_loop.nodes.qa import QANode


@pytest.mark.asyncio
async def test_feature_tier_equals_mirror_selection(tmp_path):
    ...  # FILL IN: mirrored tree (packages/ai-parrot/tests/flows/dev_loop); files_changed a dev_loop source file;
         #          targets parsed from criteria commands == set(QANode._pytest_targets(files, str(tmp_path)))


@pytest.mark.asyncio
async def test_empty_feature_plan_derives_no_criterion(tmp_path, monkeypatch):
    ...  # FILL IN: change in a package without tests dir → only the code-review dispatch happens


@pytest.mark.asyncio
async def test_qanode_records_green_escalations(tmp_path, monkeypatch):
    ...  # FILL IN: monkeypatch plan_tests in nodes.qa to return a plan with a core invocation for "ai-parrot";
         #          QAReport with CriterionResult(name="pytest[ai-parrot] (core escalation)", passed=True);
         #          monkeypatch record_green_escalation in nodes.qa with a MagicMock → called once with ["ai-parrot"]
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
7. **Move this file** to `tasks/completed/TASK-3311-qanode-feature-tier.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
