# TASK-4445: `plan_tests` contract mode and bounded fallback mode

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4444
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview + §3 Module 3, §5 AC4–AC6 (design research S1: contract presence is an explicit selector
mode). Today `plan_tests` (select.py:132) always unions declared ∪ directory mirror ∪ import impact ∪ core
escalation. FEAT-699 replaces that with two explicit modes, and NO mode ever escalates to a whole suite.

---

## Scope

Rewrite the body of `plan_tests` (keep its name; add `contract: TestContract | None = None`):

| tier | contract mode (`contract is not None`) | fallback mode (`contract is None`) |
|---|---|---|
| task | declared ∪ file-mirror | declared ∪ file-mirror |
| merge | declared ∪ contract ∪ file-mirror | declared ∪ file-mirror ∪ depth-1 importers (file-level) |
| feature | declared ∪ contract ∪ file-mirror | declared ∪ file-mirror ∪ depth-1 importers (file-level) |

- Contract operands get `TestTarget(reason="contract")`; missing-on-disk operands are dropped with a note
  (`contract operand missing on disk, skipped: <op>`) — never broadened.
- Import impact (fallback only): `impacted_tests(index, changed, worktree=, depth=1)`; when a distribution's
  count exceeds `policy.impact_cap`, keep the first `impact_cap` paths (sorted) and add the note
  `<dist>: <n> impacted tests exceed cap <cap>; kept <cap>, rest covered by nightly` — NEVER a suite.
- Core detection: still computed (when the index is available) so `ScopePlan.core_hits` stays informative,
  but it adds NO target; add the note `core change (<paths>) — covered by nightly`.
- `escalated`, `skipped_escalations`, `cap_hits`, `cap_impacted` are always empty now; the FEAT-604
  ledger (`pending_escalations`) is no longer consulted by `plan_tests` (keep `context.py` untouched — the
  CLI/supervisor ledger-recording branches simply never fire because no target has reason core/escalated).
- Fallback mode adds the note `no test contract declared — bounded fallback (own tests + direct importers)`.
- Pass `contract=` and `mode=` to `build_plan` (TASK-4444 kwargs).
- `models.py`: add `"contract"` to the `TestTargetModel.reason` Literal and `mode`/`cached` to `ScopePlanModel`.
- `__init__.py`: export `TestContract`, `GreenCacheEntry`, `BaselineVerdict`, `parse_spec_contract`,
  `contract_from_index_header`, `pytest_file_targets`.
- Update existing tests in `test_select.py` / `test_cap_escalation_ledger.py` / `test_foreign_escalation_guard.py`
  / `test_core_calibration.py` whose assertions encode suite escalation (hard cut — no deprecation shim).
  Add `test_select_contract_mode.py`.

**NOT in scope**: green cache (TASK-4447), callers (TASK-4450/4451), `context.py` changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | Two modes, no escalation |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py` | MODIFY | `contract` reason; `mode`/`cached` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` | MODIFY | New exports |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py` | CREATE | Mode tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py` | MODIFY | Re-baseline escalation assertions |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py` | MODIFY | Re-baseline: cap ⇒ note, not suite |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_foreign_escalation_guard.py` | MODIFY | Re-baseline |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py` | MODIFY | Re-baseline only if it asserts plan escalation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# select.py today (lines 11-17):
from .context import pending_escalations            # REMOVE the use (and the import) in this task
from .contract import is_broad_pytest
from .datatypes import CoreHit, ScopePlan, TestTarget          # + TestContract (TASK-4440)
from .impact import ImportIndex, detect_core, impacted_tests, module_name_for
from .mirror import distribution_of, pytest_targets            # → pytest_file_targets (TASK-4444)
from .planner import build_plan
from .policy import TIERS, ScopePolicy
```

### Existing Signatures to Use
```python
# test_scope/select.py
def changed_files(worktree: Path, base_ref: str) -> list[str]:   # line 23 (unchanged)
def _suite_for(distribution, worktree) -> str | None:           # line 68 (becomes unused → delete)
def _declared_targets(declared, notes, *, worktree) -> list[str]:  # line 100 (unchanged)
def _dist(path) / _dist_or_none(path)                            # lines 119 / 124
def plan_tests(*, worktree, changed_files, tier, declared=(), policy=None) -> ScopePlan:  # line 132
# test_scope/impact.py
class ImportIndex: load_or_build(cls, worktree) -> ImportIndex   # line 112 / 172
def impacted_tests(index, changed, *, worktree, depth) -> list[str]:  # line 234
def detect_core(index, changed, *, policy) -> list[CoreHit]:      # line 264
# test_scope/models.py
class TestTargetModel: reason: Literal["declared","mirror","import","core","escalated"]  # line 18
class ScopePlanModel(BaseModel): ... from_plan(cls, plan) classmethod                    # lines 39 / 52
# test_scope/planner.py (after TASK-4444)
def build_plan(targets, *, tier, worktree, policy, ..., contract=None, mode="fallback") -> ScopePlan
```

### Does NOT Exist
- ~~suite escalation in any FEAT-699 plan~~ — removed by design (spec §8 resolved: "contract replaces escalation")
- ~~`plan_tests(..., cache=...)`~~ — caching is a post-plan filter (TASK-4447), not a `plan_tests` kwarg

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_foreign_escalation_guard.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#_declared_targets",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#impacted_tests",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#detect_core",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/models.py#ScopePlanModel"
  ]
}
```

---

## Implementation Notes

- Keep the `is_git` / `ImportIndex.load_or_build` guards and their notes (select.py:160-182) — fallback mode
  needs the index; contract mode needs it only for the informative core note (skip building it in
  contract mode when `changed_files` has no package source file, to save time).
- Contract operands apply at merge AND feature tier only (task tier stays declared ∪ file-mirror in both modes).
- Remember the shared `.venv` caveat: run tests with `PYTHONPATH=packages/ai-parrot/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the body of `plan_tests` per the Scope table — *why*: S1 explicit modes; no suite ever.
2. Update `models.py` and `__init__.py` — *why*: `--json` CLI output and by-path consumers.
3. Re-baseline the escalation tests, then write `test_select_contract_mode.py`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def plan_tests(' select.py)
# REPLACE `def plan_tests(` … end of function (verified: select.py:132-292) with:
def plan_tests(
    *,
    worktree: Path,
    changed_files: Sequence[str],
    tier: str,
    declared: Sequence[Sequence[str]] = (),
    contract: TestContract | None = None,
    policy: ScopePolicy | None = None,
) -> ScopePlan:
    """FEAT-699 tier entry point. contract mode: declared∪contract∪file-mirror (merge/feature), no impact,
    no escalation. fallback mode: declared∪file-mirror∪depth-1 file-level importers, capped ⇒ note.
    Mirror never returns a directory; no mode ever escalates to a whole suite."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")
    policy = policy or ScopePolicy()
    mode = "contract" if contract is not None else "fallback"
    notes: list[str] = []
    targets = [
        TestTarget(path=p, distribution=_dist(p), reason="declared")
        for p in _declared_targets(declared, notes, worktree=worktree)
    ]
    targets += [
        TestTarget(path=p, distribution=_dist(p), reason="mirror")
        for p in pytest_file_targets(list(changed_files), str(worktree))
    ]
    hits: list[CoreHit] = []
    # FILL IN: (1) tier != "task" and contract → add existing contract operands (reason="contract"), note missing;
    #          (2) tier != "task": build index (keep is_git/OSError guards + notes); fallback → impacted_tests
    #              depth=1, per-dist cap truncation + note; core → detect_core for core_hits + nightly note;
    #          (3) fallback note — bounded by the Scope table and "NEVER a suite"
    return build_plan(
        targets, tier=tier, worktree=worktree, policy=policy, core_hits=hits, notes=notes, contract=contract, mode=mode
    )
```

### `models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'reason: Literal\["declared", "mirror", "import", "core", "escalated"\]' models.py)
# REPLACE (models.py:18):
    reason: Literal["declared", "contract", "mirror", "import", "core", "escalated"]
# FILL IN: add `mode: str = "fallback"` and `cached: list[str] = []` to ScopePlanModel and copy them in from_plan
```

### `__init__.py` (MODIFY)
```python
# FILL IN: extend the three import lines (__init__.py:7-10) and __all__ with:
#   TestContract, GreenCacheEntry, BaselineVerdict, parse_spec_contract, contract_from_index_header, pytest_file_targets
```

### FILL IN checklist
- [ ] `plan_tests` body (3 sub-steps above)
- [ ] remove now-unused `_suite_for`, `hashlib`, `MappingProxyType`, `pending_escalations` imports (ruff F401)
- [ ] models + exports
- [ ] re-baseline 4 existing test modules; every removed assertion replaced by its FEAT-699 equivalent (note text)

---

## Acceptance Criteria

- [ ] Contract mode, merge tier, with a `CORE_PATHS` change: zero `import` targets, `escalated == ()`, a "covered by nightly" note (spec §5).
- [ ] Fallback mode with > cap importers: exactly `impact_cap` import targets for that dist + note, no suite path in any argv.
- [ ] No plan in any mode/tier contains a target equal to `packages/<dist>/tests` or `tests`.
- [ ] Task tier ignores the contract in both modes.
- [ ] `select_tests --json` still validates (`ScopePlanModel`); `test_models.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_foreign_escalation_guard.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_models.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py -q`

---

## Test Specification

```python
# test_select_contract_mode.py
def test_plan_contract_mode_no_escalation(fixture_repo): ...
def test_plan_fallback_bounded(fixture_repo): ...
def test_task_tier_ignores_contract(fixture_repo): ...
def test_missing_contract_operand_is_noted_not_broadened(fixture_repo): ...
# FILL IN: fixture_repo = git-initialised tmp tree with packages/a/src/pkg/x/foo.py, packages/a/tests/x/test_foo.py, ...
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4445 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
