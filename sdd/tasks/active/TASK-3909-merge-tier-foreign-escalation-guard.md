# TASK-3909: Merge-tier escalation may not import a foreign red baseline

**Feature**: FEAT-618 — Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. `plan_tests()` turns "this distribution has more
impacted tests than `impact_cap`" into "run that distribution's **entire**
suite" (`select.py:186-189`). A change confined to
`parrot/outputs/a2ui/linked/*` therefore escalates outward until the merge gate
collects ~2800 tests across every distribution — and inherits whatever red
baseline those distributions happen to carry. The gate then reports a red that
no task's diff caused, for every task in the feature.

FEAT-604 reduced the *cost* of this escalation (ledger-backed skipping); it did
not stop an escalation from importing a foreign red baseline. This task does.

---

## Scope

- Add `ScopePolicy.escalate_foreign_dists: bool = False`.
- In `plan_tests()`'s cap-exceeded branch, skip a cap-only escalation into a
  distribution that owns **none** of the changed files and is not reached by
  `detect_core()`, recording the skip in `ScopePlan.notes`.
- Keep a skipped foreign escalation out of `escalated` (matching the existing
  invariant documented at `select.py:191-198`).
- Write tests for both the guard and the `escalate_foreign_dists=True` opt-out.

**NOT in scope**: re-architecting `impact.py` or the escalation ledger in
`context.py` (FEAT-604 owns those); changing `ScopePlan`'s shape, `cap_hits` or
`cap_impacted`; the `tests/__init__.py` collision (TASK-3908); any
`parrot-formdesigner` failure.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | add `escalate_foreign_dists` field |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | guard the cap-escalation branch |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_foreign_escalation_guard.py` | CREATE | unit tests for the guard and the opt-out |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy   # verified: test_scope/policy.py:773
from parrot.flows.dev_loop.test_scope.select import plan_tests    # verified: test_scope/select.py:123
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py
TIERS: tuple[str, ...] = ("task", "merge", "feature")   # line 769

@dataclass(frozen=True)                                  # line 772
class ScopePolicy:                                       # line 773
    """Per-tier knobs; defaults are the module constants above."""
    impact_cap: int = DEFAULT_IMPACT_CAP                 # line 776
    impact_depth: int = DEFAULT_IMPACT_DEPTH             # line 777
    core_fanin_threshold: int = DEFAULT_CORE_FANIN_THRESHOLD  # line 778
    core_paths: tuple[str, ...] = CORE_PATHS             # line 779
    xdist_safe: frozenset[str] = XDIST_SAFE_DISTRIBUTIONS  # line 780

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py
def _dist(path: str) -> str:                             # line 118
    """`distribution_of`, stripping a `::node` suffix first."""

def plan_tests(*, worktree: Path, changed_files: Sequence[str], tier: str,
               declared: Sequence[Sequence[str]] = (),
               policy: ScopePolicy | None = None) -> ScopePlan:   # line 123

# the cap-escalation branch this task guards (select.py:185-191):
#     for dist, paths in by_dist.items():
#         if len(paths) > policy.impact_cap:
#             cap_candidates[dist] = paths
#             notes.append(
#                 f"{dist}: {len(paths)} impacted tests exceed cap {policy.impact_cap}, escalated to suite"
#             )
#         else:
#             targets += [TestTarget(path=path, distribution=dist, reason="import") for path in paths]
```

### Does NOT Exist
- ~~`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/select_tests.py`~~ — **the path in the originating ledger issue is wrong**; the selector is `test_scope/select.py`. `scripts/sdd/select_tests.py` is a separate, unrelated CLI.
- ~~`parrot/flows/dev_loop/validation/`~~ — no such package.
- ~~`ScopePolicy.exclude_distributions`~~ / ~~`ScopePolicy.skip_foreign`~~ — not real fields; only the five at `policy.py:776-780` exist.
- ~~`ScopePlan.skipped_foreign`~~ — do not add a new return field; report through the existing `notes` list.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_foreign_escalation_guard.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py#ScopePolicy",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#_dist"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `ScopePolicy` is a **frozen dataclass** — add the new field with a default so
  every existing construction site keeps working.
- "Foreign" means: `dist not in {_dist(f) for f in changed_files}` **and** `dist`
  is not in the `core_dists` set `detect_core()` produces. A core-reached
  distribution is escalated for a reason this task must not override.
- A skipped foreign escalation contributes **no** `TestTarget` and must not be
  added to `escalated` — `select.py:191-198`'s comment explains why a
  zero-invocation distribution appearing in both `escalated` and
  `skipped_escalations` is an inconsistency.
- Leave `cap_hits` and `cap_impacted` computed exactly as today; the FEAT-604
  ledger interaction downstream depends on them.

### References in Codebase
- `select.py:191-198` — the existing comment stating the `escalated` invariant.
- `select.py:205-216` — where `to_run` / `ledger_skipped` are resolved.

---

## Implementation Blueprint

### Steps (in order)
1. Add the policy field — *why*: the guard must be switchable so callers can restore pre-FEAT-618 behaviour (AC5).
2. Compute the changed-file distribution set once, before the `by_dist` loop — *why*: recomputing `_dist` per iteration is wasted work and invites drift.
3. Guard the cap branch — *why*: this is the single line that converts "too many impacted tests" into "import another package's red".
4. Write both tests — *why*: AC4 and AC5 are the only proof the guard is scoped correctly.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    xdist_safe: frozenset\[str\] = XDIST_SAFE_DISTRIBUTIONS' policy.py)
# AFTER — insert below `    xdist_safe: frozenset[str] = XDIST_SAFE_DISTRIBUTIONS` (verified: policy.py:780)
    escalate_foreign_dists: bool = False
    """Allow a cap-only escalation into a distribution owning none of the changed files.

    False (the default, FEAT-618) skips such an escalation and records it in
    ``ScopePlan.notes`` instead of contributing the distribution's whole suite —
    so a merge-tier verdict cannot absorb an unrelated package's failing
    baseline. True restores the pre-FEAT-618 behaviour for callers that want it.
    """
```
**Why**: a defaulted field on a frozen dataclass keeps every existing
`ScopePolicy()` call site valid. The default is `False` because the broken
behaviour is the one being retired; `True` is the explicit opt-back-in AC5 tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            for dist, paths in by_dist.items():' select.py)
# REPLACE the cap branch at select.py:185-191, which currently reads:
#     for dist, paths in by_dist.items():
#         if len(paths) > policy.impact_cap:
#             cap_candidates[dist] = paths
#             notes.append(...)
#         else:
#             targets += [...]
            changed_dists = {_dist(path) for path in changed_files}
            for dist, paths in by_dist.items():
                if len(paths) > policy.impact_cap:
                    # FILL IN: when `not policy.escalate_foreign_dists` and `dist`
                    # is foreign (not in `changed_dists`), append the skip note
                    # below and `continue` WITHOUT adding `dist` to
                    # `cap_candidates` — bounded by AC4 and by the `escalated`
                    # invariant at select.py:191-198.
                    #   notes.append(
                    #       f"{dist}: cap-only escalation into a distribution owning none of the "
                    #       f"changed files; skipped (ScopePolicy.escalate_foreign_dists=False)"
                    #   )
                    cap_candidates[dist] = paths
                    notes.append(
                        f"{dist}: {len(paths)} impacted tests exceed cap {policy.impact_cap}, escalated to suite"
                    )
                else:
                    targets += [TestTarget(path=path, distribution=dist, reason="import") for path in paths]
```
**Why**: skipping before `cap_candidates[dist] = paths` is what keeps the
distribution out of `cap_hits`, `cap_impacted`, `to_run` and therefore out of
`escalated` — one `continue` enforces the whole invariant. Do not filter later
in the function; by then the ledger bookkeeping has already been built.
**Core exemption**: `detect_core()` runs *after* this loop, so a distribution
skipped here can still be re-added as a `"core"` target below — that is correct
and must not be suppressed.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_foreign_escalation_guard.py` (CREATE)
```python
"""FEAT-618 TASK-3909: merge-tier escalation must not import a foreign red baseline."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.policy import ScopePolicy  # verified: policy.py:773
from parrot.flows.dev_loop.test_scope.select import plan_tests   # verified: select.py:123


def test_cap_only_foreign_escalation_is_skipped(tmp_path: Path) -> None:
    """AC4: a cap-exceeded distribution owning none of the changed files yields no target."""
    # FILL IN: build a worktree fixture whose changed files live in distribution X
    # and whose impact index pushes unrelated distribution Y past impact_cap;
    # assert no Y target, Y absent from plan.escalated, and the skip note present
    # — bounded by AC4.
    raise NotImplementedError


def test_opt_in_restores_previous_targets(tmp_path: Path) -> None:
    """AC5: escalate_foreign_dists=True reproduces the pre-FEAT-618 target set."""
    policy = ScopePolicy(escalate_foreign_dists=True)
    # FILL IN: same fixture as above; assert the Y suite target IS present and Y
    # appears in plan.escalated exactly as before — bounded by AC5.
    raise NotImplementedError


def test_core_reached_distribution_is_not_skipped(tmp_path: Path) -> None:
    """A distribution detect_core() reaches is still escalated, guard or not."""
    # FILL IN: assert the guard does not suppress a "core" target — bounded by
    # the core exemption in the select.py block.
    raise NotImplementedError
```
**Why this shape**: the three tests pin the guard's exact boundary — it fires,
it can be switched off, and it never swallows a core escalation. Build the
fixture from a real temporary git worktree; `plan_tests()` shells out to
`git rev-parse --is-inside-work-tree` (`select.py:150-160`) and silently skips
all impact detection when that fails, which would make the tests pass vacuously.

### FILL IN checklist
- [ ] `select.py` — the foreign-skip `continue`; bounded by AC4 + the `escalated` invariant
- [ ] `test_foreign_escalation_guard.py::test_cap_only_foreign_escalation_is_skipped`; bounded by AC4
- [ ] `test_foreign_escalation_guard.py::test_opt_in_restores_previous_targets`; bounded by AC5
- [ ] `test_foreign_escalation_guard.py::test_core_reached_distribution_is_not_skipped`; bounded by the core exemption

---

## Acceptance Criteria

- [ ] **AC4** A merge-tier plan for an `outputs/a2ui/linked/*`-only diff contains no `parrot-formdesigner` and no `ai-parrot-embeddings` target, and names each skipped foreign escalation in `notes`.
- [ ] **AC5** `ScopePolicy(escalate_foreign_dists=True)` reproduces the pre-FEAT-618 target set exactly.
- [ ] A skipped foreign escalation appears in neither `escalated` nor `skipped_escalations`.
- [ ] A `detect_core()`-reached distribution is still escalated.
- [ ] **AC7** `ruff check` clean on both changed source files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_foreign_escalation_guard.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`

---

## Test Specification

See the `test_foreign_escalation_guard.py` block above — all three `FILL IN`
bodies must be completed. Build the fixture as a real temporary git worktree.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt --feature-id FEAT-618`)
2. **Read the spec** §3 Module 2.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-confirm `policy.py:773-780` and `select.py:185-191`.
5. **Update status** in `sdd/tasks/index/tests-test-wheel-layout-tech-debt.json` → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** the Validation Commands. Prefix with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit the code** — stage only this task's files.
9. **Close** with `scripts/sdd/close_task.sh TASK-3909 tests-test-wheel-layout-tech-debt verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
