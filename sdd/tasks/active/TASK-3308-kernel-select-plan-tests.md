# TASK-3308: Test-scope kernel — `plan_tests` tier orchestration + `changed_files`

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3305, TASK-3306, TASK-3307
**Assigned-to**: unassigned

---

## Context

Implements the spec's tier entry point (§2 "New Public Interfaces", §3 Module 1 `plan_tests` /
`changed_files` skeleton, Tiers table, G2/G7/G7b/G9, AC9/AC9b/AC9c/AC11/AC11b). It composes the
pieces built by the dependency tasks — mirror (3304), policy + planner (3305), context/ledger (3306),
impact + core detector (3307) — into one deterministic function per tier:

| Tier | Selection |
|---|---|
| `task` | declared ∪ mirror — **never escalates** |
| `merge` | mirror ∪ impact ∪ core escalation ∪ impacted-test cap escalation |
| `feature` | declared (all tasks) ∪ mirror ∪ core escalation |

Core escalations are deduplicated by the ledger (`pending_escalations`): a distribution whose core files
still have the same blob hashes as its last green escalated run is listed in `skipped_escalations`.

The plan decided that `plan_tests`/`changed_files` live in `test_scope/select.py` and are re-exported from
`test_scope/__init__.py` (this is the ONLY other task allowed to edit `__init__.py`).

---

## Scope

- Create `test_scope/select.py` with `plan_tests(...)` and `changed_files(...)` (signatures fixed by spec §3 Module 1).
- Re-export both from `test_scope/__init__.py`.
- Package-suite target of an escalated distribution = `packages/<dist>/tests` (or `tests` for `root`), only if it exists.
- Degrade gracefully when the worktree is not a git repo or the index cannot be built: no impact / no core
  detection, add a note, still return the mirror/declared plan (QANode unit tests use plain `tmp_path` trees).
- Write `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py` using tmp git repos.

**NOT in scope**: writing the ledger after a run (CLI TASK-3310 / QANode TASK-3311), guard logic (TASK-3309),
Pydantic models (TASK-3310), editing `policy.py` constants (3317/3318).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | CREATE | `plan_tests`, `changed_files` |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py` | CREATE | Tier behaviour tests on tmp git repos |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` | MODIFY | Re-export `plan_tests`, `changed_files` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# stdlib only (kernel core — AC3)
import subprocess
from pathlib import Path
from typing import Sequence
```

### Created by dependency tasks (verify on disk before use)
```python
# TASK-3304 test_scope/datatypes.py
class TestTarget: path: str; distribution: str; reason: str   # "declared"|"mirror"|"import"|"core"|"escalated"
class ScopePlan: tier; invocations; escalated; core_hits; skipped_escalations; notes
class CoreHit: path; module; fanin; forced; distributions
# TASK-3304 test_scope/mirror.py
def pytest_targets(files: Sequence[str], worktree_path: str) -> list[str]
def distribution_of(path: str) -> str            # ValueError for non package/tests paths
# TASK-3304 test_scope/contract.py
def is_broad_pytest(argv: Sequence[str]) -> bool
# TASK-3305 test_scope/policy.py
TIERS: tuple[str, ...] = ("task", "merge", "feature")
class ScopePolicy: impact_cap; impact_depth; core_fanin_threshold; core_paths; xdist_safe; marker_expression
# TASK-3305 test_scope/planner.py
def build_plan(targets: Sequence[TestTarget], *, tier: str, worktree: Path, policy: ScopePolicy,
               escalated: Sequence[str] = (), core_hits: Sequence[CoreHit] = (),
               skipped_escalations: Sequence[str] = (), notes: Sequence[str] = ()) -> ScopePlan
# TASK-3306 test_scope/context.py
def pending_escalations(worktree: Path, hits: Sequence[CoreHit]) -> tuple[list[str], list[str]]
# TASK-3307 test_scope/impact.py
class ImportIndex: by_module; src_importers; module_dist; skipped  (+ build / load_or_build)
def impacted_tests(index, changed, *, worktree, depth) -> list[str]
def detect_core(index, changed, *, policy) -> list[CoreHit]
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:724 — reference for the diff command shape
async def _get_changed_files(worktree_path: str) -> List[str]:
    # git diff --name-only --diff-filter=d {upstream}...HEAD -- *.py   (qa.py:733-740)
```
`changed_files` differs deliberately: it takes an explicit `base_ref`, includes non-`.py` paths, and unions
uncommitted + untracked files (`git status --porcelain --untracked-files=all`), synchronously.

### Does NOT Exist
- ~~`test_scope.plan_tests` / `test_scope.changed_files`~~ — created by THIS task
- ~~`ScopePolicy.tier`~~ — tier is a `plan_tests` argument, not a policy field
- ~~ledger writes in `plan_tests`~~ — planning is read-only; recording happens after a run (3310/3311)
- ~~an async variant~~ — the kernel is sync; async callers use `asyncio.to_thread`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._get_changed_files"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Pure composition: gather `TestTarget`s per selector with their `reason`, then hand everything to `build_plan`.
- Declared commands: take the non-flag operands of each declared `pytest` argv as `declared` targets
  (skip any broad argv via `is_broad_pytest`, add a note).

### Key Constraints
- **Task tier never escalates and never builds the import index** (budget < 60 s, G3).
- Feature tier: **no import-impact** (spec 0.3 Tiers table) — only mirror ∪ declared ∪ core escalation.
- Escalated package-suite targets replace finer targets of the same distribution (planner prunes nested).
- Ledger dedupe applies to **core** escalations only; cap escalations are not ledgered.
- Unknown tier → `ValueError`.
- stdlib only; relative imports.

### References in Codebase
- Spec §2 Tiers table and items 2b/2c — authoritative selection rules

---

## Implementation Blueprint

### Steps (in order)
1. Create `select.py` with `changed_files` — *why*: every tier starts from the same changed-file set.
2. Implement `plan_tests` skeleton: validate tier, build declared + mirror targets — *why*: shared by all tiers.
3. Add merge-tier impact + cap escalation and merge/feature core escalation with ledger dedupe — *why*: G7/G7b/AC9c.
4. Re-export from `__init__.py` — *why*: consumers import `test_scope.plan_tests`.
5. Write `test_select.py` — *why*: AC9/9b/9c/11b are tier-level behaviours.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` (CREATE)
```python
"""Tier entry point for the test-scope kernel (FEAT-563)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from .context import pending_escalations
from .contract import is_broad_pytest
from .datatypes import CoreHit, ScopePlan, TestTarget
from .impact import ImportIndex, detect_core, impacted_tests
from .mirror import distribution_of, pytest_targets
from .planner import build_plan
from .policy import TIERS, ScopePolicy


def changed_files(worktree: Path, base_ref: str) -> list[str]:
    """`git diff --name-only --diff-filter=d <base>...HEAD` ∪ uncommitted/untracked paths; [] on git failure."""
    # FILL IN: two subprocess.run calls (diff + status --porcelain --untracked-files=all), dedupe preserving order — bounded by spec M1 skeleton
    raise NotImplementedError


def _suite_for(distribution: str, worktree: Path) -> str | None:
    """Package-suite path of a distribution (`tests` for root), or None when it does not exist."""
    rel = "tests" if distribution == "root" else f"packages/{distribution}/tests"
    return rel if (worktree / rel).is_dir() else None


def _declared_targets(declared: Sequence[Sequence[str]], notes: list[str]) -> list[str]:
    """Path operands of declared pytest argvs; broad ones are dropped with a note."""
    # FILL IN: skip argv whose program is not pytest / python -m pytest; skip is_broad_pytest(argv) (note it); keep non-flag operands — bounded by G5
    raise NotImplementedError


def plan_tests(
    *,
    worktree: Path,
    changed_files: Sequence[str],
    tier: str,
    declared: Sequence[Sequence[str]] = (),
    policy: ScopePolicy | None = None,
) -> ScopePlan:
    """Tier entry point: task=declared∪mirror (no escalation); merge=mirror∪impact∪core (cap→escalate);
    feature=declared∪mirror∪core; core escalations deduped by the ledger."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")
    policy = policy or ScopePolicy()
    notes: list[str] = []
    targets = [TestTarget(path=p, distribution=_dist(p), reason="declared") for p in _declared_targets(declared, notes)]
    targets += [TestTarget(path=p, distribution=_dist(p), reason="mirror")
                for p in pytest_targets(list(changed_files), str(worktree))]
    escalated: list[str] = []
    hits: list[CoreHit] = []
    skipped: list[str] = []
    if tier != "task":
        # FILL IN: index = ImportIndex.load_or_build(worktree) inside try (failure → note, skip impact/core);
        #   merge: impacted_tests(...depth=policy.impact_depth) as reason "import"; per-dist count > policy.impact_cap → escalate (reason "escalated");
        #   merge+feature: hits = detect_core(...); to_run, skipped = pending_escalations(worktree, hits); for each dist in to_run add _suite_for (reason "core")
        #   — bounded by spec Tiers table, AC9/AC9b/AC9c
        pass
    return build_plan(targets, tier=tier, worktree=worktree, policy=policy, escalated=escalated,
                      core_hits=hits, skipped_escalations=skipped, notes=notes)
```
**Why this shape**: the signature is fixed by the spec skeleton (keyword-only). `_dist` is a local wrapper
around `distribution_of` (FILL IN below) so a declared node id such as `tests/x.py::t` still resolves.
Task tier short-circuits before any index work to keep the < 60 s budget.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py` (MODIFY)
```python
# occurrences: FILL IN (verified: grep -c '^from \.' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/__init__.py)
# FILL IN: disambiguate — the file is created by TASK-3304; append AFTER its last `from .` import line:
from .select import changed_files, plan_tests
# and add "changed_files", "plan_tests" to __all__ if TASK-3304 defined one.
```
**Why**: the plan fixes `__init__.py` ownership to TASK-3304 (create) and this task (extend) only.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py` (CREATE)
```python
"""Tier tests for test_scope.plan_tests (FEAT-563 TASK-3308)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import changed_files, plan_tests
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """git repo: dist a (pa/base.py imported by dist b), tests per dist, root tests."""
    files = {
        "packages/a/src/pa/base.py": "X = 1\n",
        "packages/a/src/pa/leaf.py": "Y = 2\n",
        "packages/a/tests/test_leaf.py": "import pa.leaf\n",
        "packages/b/src/pb/use.py": "from pa.base import X\n",
        "packages/b/tests/test_use.py": "import pb.use\n",
        "tests/test_root.py": "\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return tmp_path
```

### FILL IN checklist
- [ ] `select.py::changed_files` — diff ∪ status; bounded by spec M1 skeleton
- [ ] `select.py::_declared_targets` — operands of non-broad declared pytest argvs; bounded by G5
- [ ] `select.py::_dist` helper — strip `::node` and call `distribution_of`; non-mappable → skip with note
- [ ] `select.py::plan_tests` merge/feature branch — impact, cap, core, ledger dedupe; bounded by Tiers table, AC9/9b/9c
- [ ] `__init__.py` re-export — anchor disambiguation; bounded by plan ownership rule
- [ ] `test_select.py` — bodies in Test Specification

---

## Acceptance Criteria

- [ ] Task tier: declared ∪ mirror only; a core change produces no escalation (`test_task_tier_never_escalates`)
- [ ] Merge tier: mirror ∪ impacted tests; over-cap distribution escalated to its suite (AC9)
- [ ] Merge + feature tiers: core change escalates every importing distribution (AC9b logic)
- [ ] Ledger green with identical blobs → distribution under `skipped_escalations`, not planned (AC9c)
- [ ] Feature tier with no core hit selects mirror ∪ declared only — no impact targets (AC11b)
- [ ] No invocation spans two distributions (AC11, via `build_plan`)
- [ ] Non-git worktree → plan still returned with a note (QANode unit-test compatibility)
- [ ] `ruff check` clean on `select.py`

---

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`

---

## Test Specification

```python
def test_task_tier_never_escalates(repo):
    plan = plan_tests(worktree=repo, changed_files=["packages/a/src/pa/base.py"], tier="task",
                      policy=ScopePolicy(core_fanin_threshold=1))
    assert plan.escalated == () and plan.core_hits == ()


def test_core_escalates_every_importing_distribution(repo):
    plan = plan_tests(worktree=repo, changed_files=["packages/a/src/pa/base.py"], tier="merge",
                      policy=ScopePolicy(core_fanin_threshold=1))
    paths = {t.path for inv in plan.invocations for t in inv.targets}
    assert {"packages/a/tests", "packages/b/tests"} <= paths


def test_feature_tier_no_impact_without_core(repo):
    plan = plan_tests(worktree=repo, changed_files=["packages/a/src/pa/leaf.py"], tier="feature",
                      policy=ScopePolicy(core_fanin_threshold=999))
    assert all(t.reason in {"mirror", "declared"} for inv in plan.invocations for t in inv.targets)


def test_ledger_skips_green_same_content(repo):
    ...  # FILL IN: record_green_escalation(repo, ["a","b"], ["packages/a/src/pa/base.py"]) then merge plan → skipped_escalations == ("a","b")


def test_cap_escalates_to_package_suite(repo):
    ...  # FILL IN: ScopePolicy(impact_cap=0) on merge tier → "b" (or "a") in plan.escalated


def test_non_git_worktree_degrades_with_note(tmp_path):
    ...  # FILL IN: plain tmp tree, merge tier → plan returned, a note mentions the index


def test_changed_files_includes_untracked(repo):
    (repo / "packages/a/src/pa/new.py").write_text("")
    assert "packages/a/src/pa/new.py" in changed_files(repo, "HEAD")
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
7. **Move this file** to `tasks/completed/TASK-3308-kernel-select-plan-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
