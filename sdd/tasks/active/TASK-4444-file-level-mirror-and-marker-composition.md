# TASK-4444: File-level mirror and per-invocation marker composition

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4440
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (building blocks), §5 AC "Mirror returns only files" and "contract operand under
integration/e2e runs". Measured on FEAT-698: the directory walk-up (`deepest_existing_dir`) turned one
changed file into the whole `tests/flows/dev_loop` directory (2,562 tests). And `planner.py:42` injects
`-m "not e2e and not real_llm and not integration"` unconditionally, so a contract-declared integration
test would be silently deselected (design research S4).

---

## Scope

- `mirror.py`: add `pytest_file_target_for(path, worktree_path)` and `pytest_file_targets(files, worktree_path)`.
  A changed `packages/<d>/src/<pkg>/<a>/<b>/foo.py` maps to the FIRST existing of
  `packages/<d>/tests/<a>/<b>/test_foo.py`, then `packages/<d>/tests/<a>/test_foo.py`, then
  `packages/<d>/tests/test_foo.py`; a changed test file maps to itself if it exists; anything else → None.
  NEVER return a directory. Keep `pytest_targets`/`pytest_target_for`/`deepest_existing_dir` unchanged —
  `nodes/qa.py:643-659` (QANode) still uses them.
- `planner.py`: add `OVERRIDE_MARKER_EXPRESSION = "not real_llm"` and
  `marker_expression_for(targets, *, contract, policy) -> str`; make `build_plan` accept
  `contract: TestContract | None = None` and `mode: str = "fallback"` and, per distribution, split
  targets whose `reason == "contract"` into their OWN invocation using the override expression (so
  integration/e2e contract operands run while mirror/declared targets in the same distribution keep the
  agent exclusions). Contract `markers` add one more invocation per distribution that owns contract
  targets: `-m "(<m1> or <m2>) and not real_llm"` over that distribution's tests root.
- Add `"contract"` to `_REASON_PRIORITY` (rank right after `declared`).
- Tests: `test_mirror.py` and `test_planner.py`.

**NOT in scope**: `plan_tests` itself (TASK-4445), `models.py` (TASK-4445), callers' `suite_name` (TASK-4446).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py` | MODIFY | File-level resolution functions |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | Marker composition, contract invocation split, `build_plan` kwargs |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py` | MODIFY | File-level tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` | MODIFY | Marker/split tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .datatypes import CoreHit, PytestInvocation, ScopePlan, TestContract, TestTarget  # TestContract from TASK-4440
from .mirror import prune_nested                     # planner.py:9
from .policy import AGENT_FLAGS, TIERS, ScopePolicy  # planner.py:10
```

### Existing Signatures to Use
```python
# test_scope/mirror.py
def pytest_targets(files, worktree_path) -> list[str]:           # line 10  (KEEP — QANode uses it)
def pytest_target_for(path, worktree_path) -> str | None:        # line 38  (KEEP)
def deepest_existing_dir(tests_root, subdirs, worktree_path) -> str:  # line 84 (KEEP)
def prune_nested(targets: set[str]) -> list[str]:                # line 104
def distribution_of(path: str) -> str:                           # line 116

# test_scope/planner.py
PER_DIST_EXTRA_ARGS = ("--confcutdir", "{worktree}")             # line 13
_REASON_PRIORITY = {"declared": 0, "core": 1, "escalated": 2, "import": 3, "mirror": 4}  # line 17
def _invocation(distribution, targets, *, worktree, policy) -> PytestInvocation:  # line 25
#   line 42: argv = ("pytest", *AGENT_FLAGS, "-m", policy.marker_expression, *xdist, *extra, *kept_paths)
def build_plan(targets, *, tier, worktree, policy, escalated=(), core_hits=(), skipped_escalations=(),
               cap_hits=None, cap_impacted=None, notes=()) -> ScopePlan:  # line 46

# test_scope/policy.py
AGENT_MARKER_EXPRESSION: str = "not e2e and not real_llm and not integration"  # line 7
class ScopePolicy: marker_expression: str = AGENT_MARKER_EXPRESSION            # line 82 / 100
```

### Does NOT Exist
- ~~`pytest_file_target_for`, `pytest_file_targets`, `marker_expression_for`, `OVERRIDE_MARKER_EXPRESSION`~~ — created here
- ~~a `"contract"` TestTarget reason~~ — added here (planner) and in `models.py` by TASK-4445

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py#pytest_target_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py#prune_nested",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#build_plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#_invocation"
  ]
}
```

---

## Implementation Notes

- The override invocation for a distribution is built by `_invocation(..., marker_expression=OVERRIDE_MARKER_EXPRESSION)`
  — add a keyword `marker_expression: str | None = None` to `_invocation` (None ⇒ `policy.marker_expression`).
- Ordering of `invocations`: sorted by distribution, then the default invocation before the contract-override
  one, then the marker sweep — deterministic, so plans diff cleanly.
- A path selected both as `contract` and as `mirror`/`declared` goes to the override invocation only
  (dedupe across the two groups; the more permissive run covers it).
- `prune_nested` must run per group (a contract node id under a mirror file is pruned within its own group only).

---

## Implementation Blueprint

### Steps (in order)
1. Add the two file-level functions to `mirror.py` — *why*: tier planning must never get a directory (AC).
2. Add `marker_expression_for` + `OVERRIDE_MARKER_EXPRESSION`, the `_invocation` kwarg, and the group split
   in `build_plan` — *why*: contract operands opt into integration/e2e, never real_llm (kickoff decision).
3. Extend `test_mirror.py` / `test_planner.py`.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def deepest_existing_dir' mirror.py)
# BEFORE — insert above `def deepest_existing_dir(tests_root: str, subdirs: tuple[str, ...], worktree_path: str) -> str:` (verified: mirror.py:84)
def pytest_file_targets(files: Sequence[str], worktree_path: str) -> list[str]:
    """FEAT-699 file-level mirror: changed files → existing test FILES only, sorted, de-duplicated."""
    return sorted({t for path in files if (t := pytest_file_target_for(path, worktree_path))})


def pytest_file_target_for(path: str, worktree_path: str) -> str | None:
    """Resolve one changed path to an existing ``test_<name>.py`` (never a directory), or None.

    A changed test module maps to itself; ``packages/<d>/src/<pkg>/<a>/<b>/foo.py`` tries
    ``tests/<a>/<b>/test_foo.py``, then each shallower ``tests/.../test_foo.py`` up to ``tests/test_foo.py``.
    """
    # FILL IN: implement the lookup order above; repo-root `tests/...` changed file → itself when it exists;
    #          non-.py sources, __init__.py and deleted files → None — bounded by "NEVER return a directory"
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_REASON_PRIORITY: dict\[str, int\] =' planner.py)
# REPLACE the `_REASON_PRIORITY` line (verified: planner.py:17) with:
_REASON_PRIORITY: dict[str, int] = {"declared": 0, "contract": 1, "core": 2, "escalated": 3, "import": 4, "mirror": 5}
OVERRIDE_MARKER_EXPRESSION: str = "not real_llm"  # FEAT-699: explicit contract operands opt into integration/e2e


def marker_expression_for(
    targets: Sequence[TestTarget], *, contract: TestContract | None, policy: ScopePolicy
) -> str:
    """``OVERRIDE_MARKER_EXPRESSION`` when every target is a contract operand, else the policy expression."""
    if contract is not None and targets and all(t.reason == "contract" for t in targets):
        return OVERRIDE_MARKER_EXPRESSION
    return policy.marker_expression
```
```python
# occurrences: 1 (verified: grep -c 'argv = ("pytest", \*AGENT_FLAGS, "-m", policy.marker_expression' planner.py)
# REPLACE line 42 (verified: planner.py:42) — and add `marker_expression: str | None = None` to _invocation's kwargs:
    expression = marker_expression or policy.marker_expression
    argv = ("pytest", *AGENT_FLAGS, "-m", expression, *xdist, *extra, *kept_paths)
```
```python
# build_plan (verified: planner.py:46): add kwargs `contract: TestContract | None = None, mode: str = "fallback"`;
# FILL IN: per distribution, split groups[dist] into (default, contract) lists (contract wins on duplicate
#          paths); emit default invocation (if any), then contract invocation with
#          marker_expression_for(contract_targets, contract=contract, policy=policy), then — when
#          contract.markers and the dist owns contract targets — a marker-sweep invocation over the dist tests
#          root with `-m "(<m1> or ...) and not real_llm"`; pass mode=mode into ScopePlan(...)
#          — bounded by Implementation Notes ordering/dedupe rules
```

### FILL IN checklist
- [ ] `pytest_file_target_for` lookup order
- [ ] `build_plan` group split, ordering, marker sweep, `mode` passthrough
- [ ] tests: file-only mirror (dir never returned), deleted file → None, override invocation argv carries `-m "not real_llm"`, mirror target in same dist keeps the agent expression, marker sweep argv

---

## Acceptance Criteria

- [ ] `pytest_file_targets` never returns a directory (asserted over a fixture tree with only dirs).
- [ ] A `contract`-reason target lands in its own invocation with `-m "not real_llm"`; a `mirror` target in the same distribution keeps `AGENT_MARKER_EXPRESSION`.
- [ ] Existing `test_mirror.py`/`test_planner.py` tests unchanged and passing (old functions untouched).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
# test_planner.py (append)
def test_contract_targets_get_override_invocation(tmp_path):
    """build_plan with one contract and one mirror target in the same dist → 2 invocations, second -m 'not real_llm'."""
    # FILL IN
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4444 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
