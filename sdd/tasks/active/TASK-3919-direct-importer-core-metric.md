# TASK-3919: Direct-importer `source_fanin` + recalibrated core threshold

**Feature**: FEAT-620 — Direct-Importer Core Detection for the Merge-Tier Gate
**Spec**: `sdd/specs/test-scope-impact-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2 M1 and M2. Resolves the core of `issue:7f2f3d4d7828`
(`discovered_from: spec:FEAT-618`).

`source_fanin()` walks `src_importers` transitively with no depth bound, so a
leaf module imported by one in-package hub inherits that hub's entire upstream
closure. Measured on `dev` at `76a7d7b22`: the self-contained leaf
`parrot/outputs/a2ui/linked/dsl.py` scores **1041** while the genuine core
module `parrot/clients/base.py` scores **1024** — the leaf ranks *higher*. The
metric saturates at ~1024–1041 for every `ai-parrot` module, so
`core_fanin_threshold = 50` discriminates nothing and every merge-tier plan
escalates all 26 distributions.

Direct importers separate cleanly: `dsl.py` = 2, `impact.py` = 1, vs
`clients/base.py` = 35, `bots/abstract.py` = 31, `tools/abstract.py` = 151.

M1 and M2 are ONE task deliberately: shipping the new metric against the old
threshold of 50 would leave only 12 modules core (0.4%) — a false-negative
regression on the gate. The two constants must move together.

---

## Scope

- Rewrite `source_fanin()` to return the count of modules importing `module`
  **directly** (alias-expanded via `module_aliases`, as today) and their
  distributions. Remove the BFS.
- Update the `# FEAT-563 fix, TASK-3318 S4 finding` comment in
  `ImportIndex.build` so it no longer justifies itself by the transitive BFS;
  **keep** the exact-target edge behaviour it describes.
- Change `DEFAULT_CORE_FANIN_THRESHOLD` from `50` to `30`, with a comment
  citing the measurement and its date.
- Add a synthetic regression test proving hub fan-in is not inherited (AC6).
- Add a real-index separation test pinning the four known hubs as core and
  `dsl.py` as not-core (AC2).

**NOT in scope**: `CORE_PATHS` (TASK-3920 — it is the other escalation path and
a separate 724-entry diff); documentation (TASK-3921); anything in
`context.py`, `select.py`, the cap path, or `impacted_tests()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py` | MODIFY | `source_fanin` → direct importers; update the stale BFS rationale comment |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | `DEFAULT_CORE_FANIN_THRESHOLD` 50 → 30 |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py` | MODIFY | Add the hub-inheritance regression test |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py` | CREATE | Real-index separation test (AC2) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.impact import (  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py
    ImportIndex,          # :111
    detect_core,          # :263
    module_aliases,       # :40
    module_name_for,      # :25
    source_fanin,         # :244
)
from parrot.flows.dev_loop.test_scope.policy import (  # verified: .../test_scope/policy.py
    CORE_PATHS,                      # :12
    DEFAULT_CORE_FANIN_THRESHOLD,    # :11
    ScopePolicy,                     # :777 (dataclass)
)
from parrot.flows.dev_loop.test_scope.datatypes import CoreHit  # verified: .../test_scope/datatypes.py:29
from parrot.flows.dev_loop.test_scope.mirror import distribution_of  # verified: imported at impact.py:18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py:244
def source_fanin(index: ImportIndex, module: str) -> tuple[int, frozenset[str]]:
    """Transitive count of source modules importing `module`, and their distributions (incl. the module's own)."""

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py:263
def detect_core(index: ImportIndex, changed: Sequence[str], *, policy: ScopePolicy) -> list[CoreHit]:
    # body: fanin, dists = source_fanin(index, module)          # :270
    #       forced = path in policy.core_paths                   # :271
    #       if forced or fanin >= policy.core_fanin_threshold:   # :272

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py:111
@dataclass
class ImportIndex:
    by_module: dict[str, set[str]]      # :114
    src_importers: dict[str, set[str]]  # :115  target module -> set of importing modules
    module_dist: dict[str, str]         # :116  module -> distribution name
    skipped: list[str]                  # :117
    @classmethod
    def build(cls, worktree: Path) -> "ImportIndex": ...   # :120

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py:40
def module_aliases(module: str) -> tuple[str, ...]:
    """Return `module` plus its meta_path alias (`parrot.tools.x` <-> `parrot_tools.x`)."""

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py:29
@dataclass(frozen=True)
class CoreHit:
    path: str
    module: str
    fanin: int
    forced: bool
    distributions: tuple[str, ...]
```

### Does NOT Exist
- ~~`ScopePolicy.escalate_foreign_dists`~~ — added by FEAT-618 TASK-3909 on an
  UNMERGED branch. It is **not on `dev`**. Do not reference it.
- ~~`ScopePolicy.core_fanin_depth`~~ / ~~`core_fanin_mode`~~ — no such knob;
  this task does not add one, it changes the metric itself.
- ~~`impact.py` `_expand_modules` reuse for core detection~~ — that helper
  serves `impacted_tests` only; do not call it from `source_fanin`.
- ~~`index.src_importers` containing ancestor-prefix edges~~ — it holds exact
  targets only (see the comment at `impact.py:140-151`). Do not add prefixes.
- ~~`packages/ai-parrot/build/lib.linux-x86_64-cpython-312/...`~~ — a stale
  build artifact tree that mirrors these files. **Never edit it.**

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#source_fanin",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#detect_core",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#ImportIndex",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#module_aliases",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/datatypes.py#CoreHit",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py#ScopePolicy"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `test_scope` is **stdlib-only** (see the `impact.py` module docstring). Do not
  import `pydantic`, `aiohttp`, or anything from `parrot.*` outside this package.
- The return type `tuple[int, frozenset[str]]` is **unchanged**. Only the
  meaning of the int changes. `detect_core`, `CoreHit.fanin` and `CoreHitModel`
  keep their shapes — no signature churn.
- `detect_core` already unions the module's own distribution
  (`dists | {own}` at `impact.py:276`), so `source_fanin` must NOT add it.
  Under the current BFS, `dists` excludes `module` itself because `seen` is
  seeded with it; preserve that: a module is not its own importer.
- Cycle safety becomes structural — with no traversal there is no revisit. Do
  not keep a `seen`/`visited` set; `test_source_fanin_is_cycle_safe` must pass
  on the simpler code.

### Why the existing tests already pass
Verified against the `_tree` fixture in `test_impact.py:23`:
- `test_core_detected_by_source_fanin_not_test_count` — `pa.base` is imported
  directly by `pa.impl` and `pb.use` ⇒ fanin 2, dists `{a, b}`; the test's
  `core_fanin_threshold=2` still fires and `distributions == ("a", "b")` holds.
- `test_source_fanin_is_cycle_safe` — `pc.m1` is imported directly by `pc.m2`
  ⇒ fanin 1, dists `{c}`; its existing asserts are unchanged.
Do not edit either test.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py:213` —
  `_expand_modules`, the depth-bounded walk used by `impacted_tests`; it is the
  shape NOT to copy (it is for tests, not core detection).

---

## Implementation Blueprint

### Steps (in order)
1. Replace the body of `source_fanin` with a direct-importer lookup — *why*: the
   transitive walk is the defect; a direct count is a ~15x separation on measured data.
2. Update the stale BFS rationale comment in `ImportIndex.build` — *why*: it now
   justifies a walk that no longer exists, but the exact-target edge rule it
   enforces is still correct and must not be changed by a later reader.
3. Change `DEFAULT_CORE_FANIN_THRESHOLD` to 30 with its measurement cited — *why*:
   50 was calibrated against the saturated metric and would leave only 12 modules core.
4. Add the hub-inheritance regression test — *why*: AC6; this is the exact bug,
   and a synthetic fixture pins it independently of the real repo's shape.
5. Add the real-index separation test — *why*: AC2; the synthetic test cannot
   catch a regression that only shows up at repo scale.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def source_fanin(index: ImportIndex, module: str) -> tuple[int, frozenset[str]]:' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py)
# REPLACE the whole function at impact.py:244-260 (verified: impact.py:244)
def source_fanin(index: ImportIndex, module: str) -> tuple[int, frozenset[str]]:
    """Count of source modules importing `module` DIRECTLY, and their distributions.

    Direct, not transitive (FEAT-620). A transitive walk inherits the upstream
    closure of any hub the module happens to be imported by, which saturates:
    measured on dev@76a7d7b22 the self-contained leaf
    `parrot/outputs/a2ui/linked/dsl.py` scored 1041 against `parrot/clients/base.py`'s
    1024. Direct importers separate those cases by ~15x (2 vs 35).

    The module's own distribution is NOT included — `detect_core` unions it.
    """
    importers: set[str] = set()
    for alias in module_aliases(module):
        importers |= index.src_importers.get(alias, set())
    importers.discard(module)  # a module is never its own importer, even via an alias edge
    dists = frozenset(index.module_dist[m] for m in importers if m in index.module_dist)
    return len(importers), dists
```
**Why this shape**: `module_aliases` expansion is kept verbatim from the old
body — the `parrot.tools.<x>` ↔ `parrot_tools.<x>` meta_path redirect means both
names carry real edges and dropping either under-counts the tools hubs (measured:
`parrot.tools.abstract` and `parrot_tools.abstract` each show 151). `discard(module)`
replaces the old `seen = {module}` seeding, which is what kept a module out of its
own fan-in. The return type and the exclusion of the own-distribution are fixed by
`detect_core`'s `dists | {own}` at line 276 — do not change either.

```python
# occurrences: 1 (verified: grep -c 'module to a number close to the total file count' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py)
# REPLACE the trailing two lines of the comment block at impact.py:149-151, which read:
#     # namespace), which then inflates `source_fanin`'s transitive BFS for almost any
#     # module to a number close to the total file count. `source_fanin` must only
#     # follow exact import edges.
# with:
                # namespace). `source_fanin` is a DIRECT count since FEAT-620, but exact-target
                # edges are still required: ancestor-prefix edges would make every satellite
                # package a direct importer of the bare `parrot` namespace. Keep this as-is.
```
**Why**: the rationale named the BFS that FEAT-620 removes, so a later reader
could conclude the exact-target rule is now vestigial and "simplify" it. It is
not vestigial — it is load-bearing for the direct count too.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'DEFAULT_CORE_FANIN_THRESHOLD: int = 50' packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py)
# REPLACE the line at policy.py:11 (verified: policy.py:11)
# FEAT-620: direct-importer count, recalibrated 2026-10-01 on dev@76a7d7b22 over 2688
# modules -- >=20 selects 45 modules (1.7%), >=30 selects 29 (1.1%), >=50 selects 12 (0.4%).
# 30 sits an order of magnitude above the measured leaves (1-2) and below every measured
# hub (clients/base.py 35, bots/abstract.py 31, tools/abstract.py 151, conf.py 174).
DEFAULT_CORE_FANIN_THRESHOLD: int = 30
```
**Why**: the old 50 was derived from the saturated transitive metric and is
meaningless against direct counts. The comment carries the calibration so the
next person does not have to re-measure to justify a change.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_source_fanin_is_cycle_safe(tmp_path):' packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py)
# AFTER -- append below the body of `def test_source_fanin_is_cycle_safe(tmp_path):` (verified: test_impact.py:70-78)


def test_source_fanin_does_not_inherit_hub_fanin(tmp_path):
    """A leaf imported only by a hub must not inherit the hub's fan-in (FEAT-620)."""
    _write(tmp_path, "packages/d/src/pd/__init__.py")
    _write(tmp_path, "packages/d/src/pd/leaf.py", "X = 1\n")
    _write(tmp_path, "packages/d/src/pd/hub.py", "from .leaf import X\n")
    # FILL IN: write 40 modules that each import `pd.hub` (and nothing else), so the
    # hub's direct fan-in is 40 -- bounded by AC6, which fixes both numbers below.
    index = ImportIndex.build(tmp_path)
    leaf_fanin, _ = source_fanin(index, "pd.leaf")
    hub_fanin, _ = source_fanin(index, "pd.hub")
    assert leaf_fanin == 1, "leaf is imported only by hub"
    assert hub_fanin == 40, "hub keeps its own direct fan-in"
```
**Why**: this is the defect stated as a property — under the old BFS `leaf_fanin`
would be 41 (the hub plus its 40 importers). Asserting both numbers in one test
prevents a "fix" that simply caps everything to a small value.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py` (CREATE)
```python
"""Real-index core-detection separation (FEAT-620, spec AC2).

Builds an ImportIndex over the actual checkout, so a regression that only
appears at repo scale -- the saturation that issue:7f2f3d4d7828 reported --
cannot pass the synthetic fixtures in test_impact.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.impact import ImportIndex, detect_core
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy

REPO_ROOT = Path(__file__).resolve().parents[6]

HUBS = (
    "packages/ai-parrot/src/parrot/conf.py",
    "packages/ai-parrot/src/parrot/clients/base.py",
    "packages/ai-parrot/src/parrot/bots/abstract.py",
    "packages/ai-parrot/src/parrot/tools/abstract.py",
)
LEAVES = (
    "packages/ai-parrot/src/parrot/outputs/a2ui/linked/dsl.py",
    "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py",
)


@pytest.fixture(scope="module")
def repo_index() -> ImportIndex:
    # FILL IN: skip the module when REPO_ROOT does not look like the workspace
    # (no `packages/ai-parrot/src`) -- bounded by: this test must not fail in a
    # wheel-only install, where the source tree is absent.
    return ImportIndex.build(REPO_ROOT)


def test_known_hubs_are_core_by_fanin(repo_index):
    """Each measured hub clears the shipped default threshold on fan-in alone."""
    policy = ScopePolicy(core_paths=())  # exclude the forced path: fan-in must stand alone
    # FILL IN: assert every HUBS entry yields a hit with forced is False
    # -- bounded by AC2 and AC4.


def test_self_contained_leaves_are_not_core(repo_index):
    """A leaf module must not escalate under the shipped default policy."""
    policy = ScopePolicy(core_paths=())
    # FILL IN: assert detect_core returns no hit for any LEAVES entry
    # -- bounded by AC2. Note impact.py itself is a leaf (1 direct importer).
```
**Why this shape**: `core_paths=()` is deliberate — AC2 is about the *fan-in*
path, and leaving `CORE_PATHS` in would mask it (`clients/base.py` and
`bots/abstract.py` are both forced entries today, and TASK-3920 has not yet
pruned the list). `scope="module"` on the fixture matters: `ImportIndex.build`
parses ~2700 files, so rebuilding per test roughly doubles the runtime.
`parents[6]` resolves `tests/flows/dev_loop/test_scope/<file>` up to the repo
root — verify it rather than trusting the count.

### FILL IN checklist
- [ ] `test_impact.py::test_source_fanin_does_not_inherit_hub_fanin` — generate the 40
      hub importers; bounded by AC6 (leaf 1, hub 40).
- [ ] `test_core_calibration.py::repo_index` — the skip condition for a non-workspace
      checkout; bounded by: must not fail in a wheel-only install.
- [ ] `test_core_calibration.py::test_known_hubs_are_core_by_fanin` — assertion body;
      bounded by AC2/AC4 (hit present, `forced is False`).
- [ ] `test_core_calibration.py::test_self_contained_leaves_are_not_core` — assertion
      body; bounded by AC2 (no hit for either leaf).

---

## Acceptance Criteria

- [ ] AC1 — `source_fanin` counts direct importers only; no transitive hop remains.
- [ ] AC2 — on a real index with `core_paths=()`, the four HUBS are core and both
      LEAVES are not.
- [ ] AC3 — `DEFAULT_CORE_FANIN_THRESHOLD == 30`, measurement cited in a comment.
- [ ] AC6 — the hub-inheritance regression test passes (leaf 1, hub 40).
- [ ] AC7 — `test_source_fanin_is_cycle_safe` passes **unmodified**.
- [ ] `detect_core`, `CoreHit` and `CoreHitModel` signatures unchanged.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_core_calibration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_cap_escalation_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`

---

## Test Specification

Run with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed
against the main checkout, not this worktree).

`test_select.py` pins `core_fanin_threshold` explicitly at every call site
(values 1 and 999 — verified at `test_select.py:44,54,69,79,90,100`), so the
default change does not affect it. `test_supervisor_ledger.py` and
`test_cap_escalation_ledger.py` likewise pin 999. They are listed above as a
regression check, not because they are expected to change.

---

## Agent Instructions

Touch only the four files listed. Do not edit
`packages/ai-parrot/build/lib.linux-x86_64-cpython-312/...` — it is a stale
build artifact that mirrors these modules and is not importable source.

---

## Completion Note

*(fill in on completion)*
