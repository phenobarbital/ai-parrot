# TASK-4448: Baseline-aware verdict (`test_scope/baseline.py`)

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4446
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, §5 AC "gate verdict = new reds (+ unknowns) only" (design research S8). About 100 tests
are red on the `dev` baseline, so a raw red count tells reviewers nothing. On failure, ONLY the failed
node ids are re-run in a temporary detached checkout of `origin/<base_branch>`; cost scales with the number
of failures, never with the suite. The kickoff decision: temp detached checkout + compiled `.so` artifacts
copied from the main checkout; when that checkout cannot be made runnable, nodes are `unknown` = failure.
No such preparation mechanism exists in `worktree_environment.py`/`worktree_manager.py` today (verified, S8).

---

## Scope

Create `test_scope/baseline.py` (stdlib only):

- `class BaselineUnavailable(RuntimeError)`.
- `main_checkout_root(worktree) -> Path | None` — `git rev-parse --path-format=absolute --git-common-dir`,
  parent of that dir; None on failure.
- `prepare_baseline_checkout(*, worktree, base_ref, scratch) -> Path` — `git worktree add --detach <scratch>/baseline-<sha12> <base_ref>`
  (run from `worktree`); then copy every compiled artifact `packages/*/src/**/*.so` from the main checkout
  into the same relative path of the new checkout (skip ones already present). Raises `BaselineUnavailable`
  on any git failure, or when the main checkout has no `.so` for a path that the base tree contains a
  `.pyx` for (a missing extension would make imports fail and misreport).
- `remove_baseline_checkout(worktree, path) -> None` — `git worktree remove --force <path>` then
  `git worktree prune`; never raises (log warning).
- `classify_failures(*, worktree, base_ref, failed_nodeids, timeout_s, scratch=None) -> tuple[BaselineVerdict, ...]`:
  - empty input → `()`;
  - node whose file part does not exist in the baseline checkout → `new_red` with detail `test only on branch`;
  - otherwise run ONE pytest per distribution over the existing failed node ids inside the checkout:
    argv = `[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "junit_family=xunit1",
    f"--junitxml={tmp}", "--confcutdir", <checkout>, "-m", "not real_llm", *nodeids]`, `cwd=<checkout>`,
    env `PYTHONPATH=<checkout>/packages/<dist>/src` (root tests: `<checkout>/packages/ai-parrot/src`), `timeout=timeout_s`;
  - parse with `report.parse_junit` → node passed on base ⇒ `new_red`; failed/error on base ⇒ `baseline_red`;
    node missing from the base junit, timeout, or unmapped ⇒ `unknown` with detail;
  - `BaselineUnavailable` ⇒ every node `unknown` with the exception text as detail;
  - ALWAYS remove the checkout in `finally`.
- `gate_failed(verdicts) -> bool` — True iff any `new_red` or `unknown`.
- `summarize(verdicts) -> dict[str, int]` — counts per status.
- Tests `test_baseline.py` against a hermetic git repo whose base commit has one passing and one failing
  test, and a branch commit that breaks the passing one + adds a new failing file.

**NOT in scope**: callers (TASK-4450/4451); flaky retry (spec §8 open — v1 never emits `flaky`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | CREATE | Checkout prep + classification |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py` | CREATE | Hermetic git-repo tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .datatypes import BaselineVerdict           # TASK-4440
from .mirror import distribution_of              # mirror.py:116
from .report import parse_junit                  # report.py:111 (nodes/unmapped from TASK-4446)
```

### Existing Signatures to Use
```python
def distribution_of(path: str) -> str:  # "root" for tests/…, "<dist>" for packages/<dist>/…; ValueError otherwise
def parse_junit(junit_path, *, suite, argv, exit_code, duration_s, timed_out=False) -> SuiteResult
#   SuiteResult.nodes: tuple[(nodeid, "passed"|"failed"|"error"|"skipped")], .unmapped: int   (TASK-4446)
```
- Compiled artifacts present today in the main checkout: `packages/ai-parrot/src/parrot/utils/types.cpython-31{1,2,3}-x86_64-linux-gnu.so`.

### Does NOT Exist
- ~~a `.so`-copy helper in `parrot/flows/dev_loop/worktree_environment.py` or `worktree_manager.py`~~ — verified absent
- ~~`BaselineVerdict.status == "flaky"` emission~~ — reserved, never produced in v1

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py#distribution_of",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#parse_junit"
  ]
}
```

---

## Implementation Notes

- Synchronous module (subprocess) like the rest of the kernel; async callers wrap it in `asyncio.to_thread`.
- `scratch` default: `tempfile.mkdtemp(prefix="parrot-baseline-")` — never inside the repo; delete the temp
  junit dir afterwards with `shutil.rmtree(..., ignore_errors=True)` on the TEMP dir only.
- Never `uv sync`, never install — the checkout uses the already-active interpreter (`sys.executable`).
- Use `logging.getLogger(__name__)` for warnings; no `print`.
- Hermetic test: the `.pyx` rule must not trip — a repo with no `.pyx` files needs no `.so`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the skeleton below; 2. fill checkout prep + classification; 3. hermetic tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` (CREATE)
```python
"""Baseline-aware verdict: classify branch failures against origin/<base_branch> (FEAT-699, spec §3 M5).

Only failed node ids are re-run, inside a temporary detached checkout of the base ref with the compiled
extensions copied from the main checkout. Anything that cannot be proven is ``unknown`` — a failure.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .datatypes import BaselineVerdict
from .mirror import distribution_of
from .report import parse_junit

logger = logging.getLogger(__name__)


class BaselineUnavailable(RuntimeError):
    """The base ref cannot be checked out into a runnable tree."""


def main_checkout_root(worktree: Path) -> Path | None:
    """Root of the primary checkout that owns ``worktree``'s git common dir."""
    # FILL IN
    raise NotImplementedError


def prepare_baseline_checkout(*, worktree: Path, base_ref: str, scratch: Path) -> Path:
    """Detached ``git worktree add`` of ``base_ref`` + compiled ``.so`` copies. Raises BaselineUnavailable."""
    # FILL IN — bounded by Scope (pyx-without-so rule)
    raise NotImplementedError


def remove_baseline_checkout(worktree: Path, path: Path) -> None:
    """Best-effort removal of a checkout created by ``prepare_baseline_checkout``; never raises."""
    # FILL IN
    raise NotImplementedError


def classify_failures(
    *,
    worktree: Path,
    base_ref: str,
    failed_nodeids: Sequence[str],
    timeout_s: int,
    scratch: Path | None = None,
) -> tuple[BaselineVerdict, ...]:
    """Run ONLY ``failed_nodeids`` on the baseline; one verdict per input node id, input order kept."""
    # FILL IN — bounded by Scope classification rules; always remove the checkout in finally
    raise NotImplementedError


def gate_failed(verdicts: Sequence[BaselineVerdict]) -> bool:
    """True when any verdict is ``new_red`` or ``unknown``."""
    return any(v.status in ("new_red", "unknown") for v in verdicts)


def summarize(verdicts: Sequence[BaselineVerdict]) -> dict[str, int]:
    """Count verdicts per status (only statuses that occur)."""
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.status] = counts.get(verdict.status, 0) + 1
    return counts
```

### FILL IN checklist
- [ ] `main_checkout_root`, `prepare_baseline_checkout`, `remove_baseline_checkout`
- [ ] `classify_failures` per-dist grouping, env, timeout ⇒ unknown, branch-only ⇒ new_red
- [ ] hermetic tests: new_red, baseline_red, branch-only new_red, unbuildable (bad ref) ⇒ unknown, checkout always removed (`git worktree list` clean)

---

## Acceptance Criteria

- [ ] Hermetic repo: a test broken on the branch ⇒ `new_red`; a test red on base too ⇒ `baseline_red`.
- [ ] A node in a file that exists only on the branch ⇒ `new_red` (spec §4 `test_branch_only_test_on_baseline`).
- [ ] Bad `base_ref` ⇒ every node `unknown`, `gate_failed` True.
- [ ] After every call, `git worktree list` shows no leftover baseline checkout.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
# test_baseline.py
def test_new_red_vs_baseline_red(hermetic_repo): ...
def test_branch_only_file_is_new_red(hermetic_repo): ...
def test_unbuildable_base_is_unknown(hermetic_repo): ...
def test_checkout_always_removed(hermetic_repo): ...
# FILL IN: hermetic_repo = git init; base commit with tests/test_a.py (pass) + tests/test_b.py (fail);
#          create branch; break test_a; add tests/test_c.py (fail); return (repo, "base-sha")
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4448 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
