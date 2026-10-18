# TASK-4447: Content-addressed green cache across merges

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4445, TASK-4446
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, §5 AC "second merge-tier run skips unchanged green files" (design research S5/S6/S7).
On FEAT-698 the same `flows/dev_loop` tests ran 15 times, once per merge, against unchanged code. This
module records per-target green evidence and drops cached-and-unchanged targets from later plans.

---

## Scope

Create `test_scope/green_cache.py` (stdlib only):

- `CACHE_FILENAME = "parrot-test-scope-green.json"` stored in the per-worktree git dir
  (`context.worktree_git_dir`), next to the FEAT-604 escalation ledger.
- `CACHE_SCHEMA = 1`; `SELECTOR_VERSION = "feat-699.1"` (bump to invalidate every cache on selector changes).
- `cache_namespace(*, feature_id, base_ref, contract_digest) -> str` — sha256 of those + schema + selector version.
- `execution_manifest(worktree, target) -> dict[str, str] | None` — the inputs that decide a target's
  outcome, as `{label: blob}`: the target file blob; every `conftest.py` from the target's directory up to
  the repo root; the repo-root `pyproject.toml` and the owning `packages/<dist>/pyproject.toml`;
  the blobs of the source modules the test file imports at depth ≤ 1 (from `ImportIndex.by_module`,
  resolved to `packages/*/src/<module path>.py` or `/__init__.py`); plus `"python": "<major>.<minor>"`
  and `"markers": <the invocation's -m expression>`. Any unresolvable input ⇒ `None` (= cache miss, S6).
- `target_key(manifest) -> str` — sha256 of the sorted manifest JSON.
- `filter_cached(worktree, plan, *, namespace, index=None) -> ScopePlan` — returns a plan rebuilt via
  `planner.build_plan` from the surviving targets, with `cached=<dropped target paths>` and a note
  `green cache: skipped <n> unchanged target(s)`. A target is dropped ONLY when its stored key equals its
  current key. Targets with reason `contract` in a marker sweep (directory operand) are never cached.
- `record_green(worktree, *, namespace, plan, nodes, baseline_reds=()) -> None` — for each planned file or
  node target: green iff every reported node belonging to it (nodeid == target or startswith `target + "::"`)
  is `passed`/`skipped`, or is listed in `baseline_reds`, AND at least one node belongs to it AND the
  suite had `unmapped == 0` (fail closed, S5). Writes entries under the namespace; lock-protected
  read-modify-write with `fcntl.flock` on `<cache>.lock` (same pattern as `report.append_suite`, S7).
  A namespace mismatch (different feature/base/contract) replaces the whole store.
- `invalidate(worktree) -> None` — delete the store (used by tests and by `--fresh` callers if needed).
- Tests in new `test_green_cache.py`.

**NOT in scope**: wiring into callers (TASK-4450/4451). Recording for a red run is simply "don't record";
an existing entry for a target that is now red must be REMOVED by `record_green` (re-arm).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` | CREATE | Cache store + filter + record |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .context import _atomic_write_json, _blob, worktree_git_dir   # context.py:31 / :74 / :21
from .datatypes import GreenCacheEntry, ScopePlan, TestTarget      # GreenCacheEntry from TASK-4440
from .impact import ImportIndex                                    # impact.py:112
from .planner import build_plan                                    # planner.py:46 (contract/mode kwargs from TASK-4444)
from .policy import ScopePolicy                                    # policy.py:82
```

### Existing Signatures to Use
```python
# context.py
def worktree_git_dir(worktree: Path) -> Path | None:                 # line 21
def _atomic_write_json(path: Path, payload: object) -> None:         # line 31
def _blob(worktree: Path, path: str) -> str | None:                  # line 74 (git hash-object)
# impact.py
class ImportIndex: by_module: dict[str, set[str]]  # module (and every prefix) -> test files importing it (line 115)
                   module_dist: dict[str, str]     # real source modules only (line 117)
    @classmethod load_or_build(cls, worktree) -> ImportIndex  # line 172
# report.py (lock idiom to copy)
#   lines 202-228: lock_path = path.with_suffix(".json.lock"); fcntl.flock(..., LOCK_EX) ... LOCK_UN
# datatypes.ScopePlan: invocations[*].targets (TestTarget path/distribution/reason), notes, mode, cached
# report.SuiteResult (TASK-4446): nodes: tuple[(nodeid, status)], unmapped: int
```

### Does NOT Exist
- ~~`green_cache.py`~~ — created here
- ~~an "imports of test file X" lookup on ImportIndex~~ — derive it by scanning `by_module` for entries
  containing X and keeping keys present in `module_dist` (prefix keys are not real modules)
- ~~caching at directory granularity~~ — never

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#worktree_git_dir",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#_atomic_write_json",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/context.py#_blob",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py#ImportIndex",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#build_plan"
  ]
}
```

---

## Implementation Notes

- `_blob` hashes WORKING-TREE content (uncommitted edits count) — exactly right for a cache key.
- `filter_cached` must preserve `plan.mode`, `plan.notes`, `plan.core_hits` and pass the same `contract`
  object; the caller therefore passes `contract=` too — add a keyword `contract: TestContract | None = None`
  and `policy: ScopePolicy | None = None` to `filter_cached`.
- Store shape: `{"schema": 1, "namespace": "...", "entries": {target: {"key": ..., "recorded_at": ...}}}`.
  Unreadable/malformed store ⇒ treat as empty (never crash planning).
- Performance: build `ImportIndex` once per call (accept an optional pre-built `index`).

---

## Implementation Blueprint

### Steps (in order)
1. Write the module skeleton below — *why*: fixed names other tasks call.
2. Fill manifest/key/filter/record — *why*: S5/S6/S7 fail-closed rules.
3. Tests: hit, miss on test edit, miss on conftest edit, miss on pyproject edit, miss on imported source edit,
   miss on marker change, unmapped ⇒ not recorded, red ⇒ entry removed, namespace change ⇒ reset,
   two concurrent `record_green` processes (multiprocessing) lose no entries.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` (CREATE)
```python
"""Content-addressed green cache across merges within one feature (FEAT-699, spec §3 Module 4).

Stdlib-only. Stored in the per-worktree git dir next to the FEAT-604 escalation ledger. Every unknown or
unresolvable input is a cache MISS — the cache may only ever skip work it can prove unchanged.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from .context import _atomic_write_json, _blob, worktree_git_dir
from .datatypes import GreenCacheEntry, ScopePlan, TestContract, TestTarget
from .impact import ImportIndex
from .planner import build_plan
from .policy import ScopePolicy

try:  # POSIX only
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

CACHE_FILENAME: str = "parrot-test-scope-green.json"
CACHE_SCHEMA: int = 1
SELECTOR_VERSION: str = "feat-699.1"


def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str:
    """Namespace for one feature/base/contract; any change invalidates the whole store."""
    raw = json.dumps([CACHE_SCHEMA, SELECTOR_VERSION, feature_id, base_ref, contract_digest])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def execution_manifest(
    worktree: Path, target: str, *, marker_expression: str, index: ImportIndex
) -> dict[str, str] | None:
    """Inputs deciding ``target``'s outcome as ``{label: blob}``; None when any input is unresolvable."""
    # FILL IN: per Scope bullet — target blob, conftest chain, pyprojects, depth-1 imported source blobs,
    #          python x.y, markers; any _blob None ⇒ return None
    raise NotImplementedError


def target_key(manifest: Mapping[str, str]) -> str:
    """sha256 of the sorted manifest."""
    return hashlib.sha256(json.dumps(dict(manifest), sort_keys=True).encode("utf-8")).hexdigest()


def filter_cached(
    worktree: Path,
    plan: ScopePlan,
    *,
    namespace: str,
    contract: TestContract | None = None,
    policy: ScopePolicy | None = None,
    index: ImportIndex | None = None,
) -> ScopePlan:
    """Drop targets whose stored key equals their current key; rebuild the plan; report them in ``cached``."""
    # FILL IN — bounded by Implementation Notes (preserve mode/notes/core_hits; never cache directories)
    raise NotImplementedError


def record_green(
    worktree: Path,
    *,
    namespace: str,
    plan: ScopePlan,
    nodes: Sequence[tuple[str, str]],
    unmapped: int = 0,
    baseline_reds: Collection[str] = (),
    index: ImportIndex | None = None,
) -> None:
    """Record green targets / remove re-red ones, under an exclusive file lock. Never raises."""
    # FILL IN — bounded by Scope "green iff ..." rule and the report.append_suite lock idiom
    raise NotImplementedError


def invalidate(worktree: Path) -> None:
    """Delete the store (no-op outside git or when absent)."""
    git_dir = worktree_git_dir(worktree)
    if git_dir is not None:
        (git_dir / CACHE_FILENAME).unlink(missing_ok=True)
```

### FILL IN checklist
- [ ] `execution_manifest`
- [ ] `filter_cached`
- [ ] `record_green` incl. lock + namespace reset + red removal
- [ ] tests (10 behaviours in Step 3)

---

## Acceptance Criteria

- [ ] Second identical plan after `record_green` of an all-passed run → target appears in `plan.cached`, not in any argv.
- [ ] Editing the test file, a conftest, a pyproject, or an imported source module ⇒ miss.
- [ ] `unmapped > 0` ⇒ nothing recorded; a node failing (not in `baseline_reds`) ⇒ entry removed.
- [ ] Concurrent writers lose no entries (multiprocessing test).
- [ ] `test_stdlib_only.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
# test_green_cache.py — use a git-initialised tmp repo fixture (git init, commit) so _blob/worktree_git_dir work
def test_second_run_is_cached(git_repo): ...
def test_conftest_change_invalidates(git_repo): ...
def test_unmapped_nodes_never_recorded(git_repo): ...
def test_concurrent_record_green(git_repo): ...
# FILL IN bodies
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4447 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
