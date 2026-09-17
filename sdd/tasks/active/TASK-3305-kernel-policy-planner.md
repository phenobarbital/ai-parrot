# TASK-3305: Test-scope kernel — tier policy and per-distribution planner

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3304, TASK-3303
**Assigned-to**: unassigned

---

## Context

Second half of spec **Module 1**. `policy.py` holds every tunable of the test pyramid
(marker expression, agent flags, impact cap/depth, core fan-in threshold, `CORE_PATHS`, xdist
allowlist) as data, so budgets change without touching adapters (spec §2 Overview item 3).
`planner.py` turns a list of `TestTarget`s into a `ScopePlan` with **one `PytestInvocation` per
distribution** — never one invocation spanning distributions, because pytest config discovery
differs between the repo-root `pytest.ini` and each `packages/<dist>/pyproject.toml` (item 4,
AC11). The exact extra argv that keeps worktree-source precedence comes from spike S2
(TASK-3303, `artifacts/logs/feat-563-s2-conftest-rootdir.md`).

---

## Scope

- Create `test_scope/policy.py`: `AGENT_MARKER_EXPRESSION`, `AGENT_FLAGS`, `DEFAULT_IMPACT_CAP`,
  `DEFAULT_IMPACT_DEPTH`, `DEFAULT_CORE_FANIN_THRESHOLD`, `CORE_PATHS` (seed), `XDIST_SAFE_DISTRIBUTIONS`
  (empty), `TIERS`, frozen dataclass `ScopePolicy`.
- Create `test_scope/planner.py`: `PER_DIST_EXTRA_ARGS` (from the S2 log decision) and `build_plan`.
- Write `test_scope/test_planner.py`.

**NOT in scope**: editing `test_scope/__init__.py` (only TASK-3304 and TASK-3308 may); choosing targets
(mirror/impact/select — TASK-3304/3307/3308); filling `XDIST_SAFE_DISTRIBUTIONS` (TASK-3317) or the
final `CORE_PATHS` (TASK-3318).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | CREATE | Tier policy constants + `ScopePolicy` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | CREATE | `build_plan` per distribution |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` | CREATE | Planner/policy unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# Inside test_scope (relative, stdlib-only) — created by TASK-3304:
from .datatypes import CoreHit, PytestInvocation, ScopePlan, TestTarget   # test_scope/datatypes.py (TASK-3304)
from .mirror import distribution_of, prune_nested                          # test_scope/mirror.py (TASK-3304)
# Tests:
from parrot.flows.dev_loop.test_scope import TestTarget, ScopePlan          # test_scope/__init__.py (TASK-3304)
from parrot.flows.dev_loop.test_scope.planner import build_plan
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy, AGENT_FLAGS, AGENT_MARKER_EXPRESSION
```

### Existing Signatures to Use
```python
# test_scope/datatypes.py (TASK-3304) — spec §2 Data Models
@dataclass(frozen=True)
class TestTarget: path: str; distribution: str; reason: str
@dataclass(frozen=True)
class PytestInvocation: distribution: str; argv: tuple[str, ...]; targets: tuple[TestTarget, ...]
@dataclass(frozen=True)
class CoreHit: path: str; module: str; fanin: int; forced: bool; distributions: tuple[str, ...]
@dataclass(frozen=True)
class ScopePlan: tier: str; invocations: tuple[PytestInvocation, ...]; escalated: tuple[str, ...]; core_hits: tuple[CoreHit, ...]; skipped_escalations: tuple[str, ...]; notes: tuple[str, ...]

# test_scope/mirror.py (TASK-3304)
def distribution_of(path: str) -> str: ...        # "<dist>" | "root" | ValueError
def prune_nested(targets: set[str]) -> list[str]: ...

# Configuration facts (verified 2026-09-17)
pytest.ini                                  # repo root: markers integration, live, real_llm, slow (no e2e yet — TASK-3316)
packages/ai-parrot/pyproject.toml:997       # per-dist [tool.pytest.ini_options]
pyproject.toml:64                           # "pytest-xdist==3.3.1" pinned → "-n auto" available
artifacts/logs/feat-563-s2-conftest-rootdir.md   # created by TASK-3303: "PER_DIST_EXTRA_ARGS = (...)" decision line
```

### Does NOT Exist
- ~~`TS/__init__.py` exports of `ScopePolicy` / `build_plan`~~ — not added by this task; import from the submodules
- ~~an `e2e` marker registration~~ — `-m "not e2e …"` is still valid: unregistered names in `-m` expressions do not error (strict markers only checks decorators)
- ~~pytest-timeout~~ — do not add `--timeout`
- ~~a `planner.plan_tests`~~ — tier orchestration lives in `select.py` (TASK-3308)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Plain frozen dataclass + module constants (same stdlib style as `test_scope/datatypes.py`).

### Key Constraints
- Stdlib only, relative imports, Google docstrings, type hints (AC3).
- Deterministic output: invocations sorted by distribution name; targets inside an invocation sorted after pruning.
- argv layout (fixed): `("pytest", *AGENT_FLAGS, "-m", policy.marker_expression, *xdist, *extra, *target_paths)`
  where `xdist = ("-n", "auto")` only if `distribution in policy.xdist_safe` (AC10), and `extra` is
  `PER_DIST_EXTRA_ARGS` with `{worktree}` / `{dist_root}` substituted (`dist_root` = `packages/<dist>` or `.` for root).
- A target whose `reason` is `"escalated"`/`"core"` and whose path is the package tests root simply prunes the
  narrower targets of that distribution (it is a parent) — no special casing needed.
- Empty `targets` → `ScopePlan` with `invocations=()` (callers decide block/no-criterion).

### References in Codebase
- Spec §2 Overview items 3–4, §3 M1 skeleton (policy.py, planner.py), AC2, AC10, AC11
- `artifacts/logs/feat-563-s2-conftest-rootdir.md` — S2 decision

---

## Implementation Blueprint

### Steps (in order)
1. Read the S2 log decision line — *why*: `PER_DIST_EXTRA_ARGS` must be copied verbatim, not guessed.
2. Create `policy.py` with the constants exactly as below — *why*: TASK-3317/3318 edit only the two marked constants.
3. Create `planner.py` — *why*: single place that shapes argv (AC2, AC10, AC11).
4. Write and run `test_planner.py` — *why*: grouping/flags/xdist regressions are silent otherwise.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` (CREATE)
```python
"""Tier policy for the test-scope kernel (FEAT-563). Stdlib only — data, not logic."""
from __future__ import annotations

from dataclasses import dataclass

AGENT_MARKER_EXPRESSION: str = "not e2e and not real_llm and not integration"
AGENT_FLAGS: tuple[str, ...] = ("-q", "--tb=short", "-p", "no:cacheprovider", "-o", "log_cli=false")
DEFAULT_IMPACT_CAP: int = 150
DEFAULT_IMPACT_DEPTH: int = 1
DEFAULT_CORE_FANIN_THRESHOLD: int = 50
CORE_PATHS: tuple[str, ...] = (  # seed; final list written from spike S4 measurement (TASK-3318); always escalate
    "packages/ai-parrot/src/parrot/clients/base.py",  # 182 source importers (measured 2026-09-17)
    "packages/ai-parrot/src/parrot/bots/abstract.py",  # 146 source importers (measured 2026-09-17)
)
XDIST_SAFE_DISTRIBUTIONS: frozenset[str] = frozenset()  # filled by spike S3 (TASK-3317)
TIERS: tuple[str, ...] = ("task", "merge", "feature")


@dataclass(frozen=True)
class ScopePolicy:
    """Per-tier knobs; defaults are the module constants above."""

    impact_cap: int = DEFAULT_IMPACT_CAP
    impact_depth: int = DEFAULT_IMPACT_DEPTH
    core_fanin_threshold: int = DEFAULT_CORE_FANIN_THRESHOLD
    core_paths: tuple[str, ...] = CORE_PATHS
    xdist_safe: frozenset[str] = XDIST_SAFE_DISTRIBUTIONS
    marker_expression: str = AGENT_MARKER_EXPRESSION
```
**Why this shape**: values fixed by spec §3 M1 skeleton and §8 (threshold 50 confirmed). Keep each constant
on its own line — later tasks edit them by anchor.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` (CREATE)
```python
"""Group selected targets into one pytest invocation per distribution (FEAT-563 M1)."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .datatypes import CoreHit, PytestInvocation, ScopePlan, TestTarget
from .mirror import prune_nested
from .policy import AGENT_FLAGS, TIERS, ScopePolicy

# Decision from spike S2 (artifacts/logs/feat-563-s2-conftest-rootdir.md). Placeholders: {worktree}, {dist_root}.
PER_DIST_EXTRA_ARGS: tuple[str, ...] = ()  # FILL IN: copy the S2 log's PER_DIST_EXTRA_ARGS verbatim — bounded by R6


def _dist_root(distribution: str) -> str:
    """Repo-relative root of a distribution ('.' for the repo-root tests tree)."""
    return "." if distribution == "root" else f"packages/{distribution}"


def _invocation(distribution: str, targets: Sequence[TestTarget], *, worktree: Path, policy: ScopePolicy) -> PytestInvocation:
    """Build the argv for one distribution's pruned targets."""
    kept_paths = prune_nested({t.path for t in targets})
    kept = tuple(sorted((t for t in targets if t.path in kept_paths), key=lambda t: t.path))
    # FILL IN: dedupe `kept` by path (first reason wins, preferring "declared" > "core" > "escalated" > "import" > "mirror") — bounded by AC11
    xdist = ("-n", "auto") if distribution in policy.xdist_safe else ()
    extra = tuple(a.format(worktree=str(worktree), dist_root=_dist_root(distribution)) for a in PER_DIST_EXTRA_ARGS)
    argv = ("pytest", *AGENT_FLAGS, "-m", policy.marker_expression, *xdist, *extra, *kept_paths)
    return PytestInvocation(distribution=distribution, argv=argv, targets=kept)


def build_plan(
    targets: Sequence[TestTarget],
    *,
    tier: str,
    worktree: Path,
    policy: ScopePolicy,
    escalated: Sequence[str] = (),
    core_hits: Sequence[CoreHit] = (),
    skipped_escalations: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> ScopePlan:
    """Group by distribution, prune nested, add flags/markers/xdist → one PytestInvocation per group.

    Raises:
        ValueError: when ``tier`` is not one of ``TIERS``.
    """
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    groups: dict[str, list[TestTarget]] = {}
    for target in targets:
        groups.setdefault(target.distribution, []).append(target)
    invocations = tuple(
        _invocation(dist, groups[dist], worktree=worktree, policy=policy) for dist in sorted(groups)
    )
    return ScopePlan(
        tier=tier,
        invocations=invocations,
        escalated=tuple(sorted(set(escalated))),
        core_hits=tuple(core_hits),
        skipped_escalations=tuple(sorted(set(skipped_escalations))),
        notes=tuple(notes),
    )
```
**Why this shape**: `build_plan` signature fixed by spec §3 M1 (v0.3). The planner never selects — it only
shapes — so tier semantics stay in `select.py`.

### FILL IN checklist
- [ ] `planner.py::PER_DIST_EXTRA_ARGS` — verbatim from S2 log; bounded by R6
- [ ] `planner.py::_invocation` target dedupe by path with reason precedence; bounded by AC11
- [ ] Test bodies below

---

## Acceptance Criteria

- [ ] Every invocation argv starts with `pytest`, carries `AGENT_FLAGS` and `-m "not e2e and not real_llm and not integration"` (spec AC2)
- [ ] `-n auto` appears iff the distribution is in `policy.xdist_safe` (spec AC10)
- [ ] Targets in two distributions + root produce three invocations; no invocation spans distributions (spec AC11)
- [ ] Nested targets inside one distribution are pruned; output deterministic (sorted)
- [ ] Unknown tier raises `ValueError`
- [ ] `policy.py`/`planner.py` import with stdlib only (existing `test_stdlib_only.py` still passes)
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/` clean

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import TestTarget
from parrot.flows.dev_loop.test_scope.planner import build_plan
from parrot.flows.dev_loop.test_scope.policy import AGENT_FLAGS, AGENT_MARKER_EXPRESSION, ScopePolicy


def _t(path, dist, reason="mirror"):
    return TestTarget(path=path, distribution=dist, reason=reason)


def test_plan_groups_per_distribution(tmp_path: Path):
    plan = build_plan(
        [_t("packages/a/tests/x", "a"), _t("packages/b/tests/test_y.py", "b"), _t("tests/test_r.py", "root")],
        tier="merge", worktree=tmp_path, policy=ScopePolicy(),
    )
    assert [i.distribution for i in plan.invocations] == ["a", "b", "root"]
    for inv in plan.invocations:
        assert all(t.distribution == inv.distribution for t in inv.targets)


def test_plan_flags_and_marker_expression(tmp_path: Path):
    plan = build_plan([_t("packages/a/tests/x", "a")], tier="task", worktree=tmp_path, policy=ScopePolicy())
    argv = plan.invocations[0].argv
    assert argv[0] == "pytest"
    assert tuple(argv[1 : 1 + len(AGENT_FLAGS)]) == AGENT_FLAGS
    assert argv[argv.index("-m") + 1] == AGENT_MARKER_EXPRESSION


def test_xdist_only_for_allowlisted_dist(tmp_path: Path):
    policy = ScopePolicy(xdist_safe=frozenset({"a"}))
    plan = build_plan([_t("packages/a/tests/x", "a"), _t("packages/b/tests/y", "b")], tier="merge", worktree=tmp_path, policy=policy)
    by = {i.distribution: i.argv for i in plan.invocations}
    assert "-n" in by["a"] and "-n" not in by["b"]


def test_nested_targets_pruned(tmp_path: Path):
    plan = build_plan(
        [_t("packages/a/tests", "a", "escalated"), _t("packages/a/tests/flows/test_z.py", "a")],
        tier="feature", worktree=tmp_path, policy=ScopePolicy(),
    )
    assert plan.invocations[0].argv[-1] == "packages/a/tests"
    assert len(plan.invocations[0].targets) == 1


def test_empty_targets_and_unknown_tier(tmp_path: Path):
    assert build_plan([], tier="task", worktree=tmp_path, policy=ScopePolicy()).invocations == ()
    with pytest.raises(ValueError):
        build_plan([], tier="nightly", worktree=tmp_path, policy=ScopePolicy())
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
7. **Move this file** to `tasks/completed/TASK-3305-kernel-policy-planner.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
