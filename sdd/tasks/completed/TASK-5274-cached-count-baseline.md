# TASK-5274: Union cached count; baseline imports from its own checkout and never prunes globally

**Feature**: FEAT-830 — test-scope report fixes
**Spec**: `sdd/specs/test-scope-report-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:bfb29d4ffe49`

---

## Context

Spec §1 items 3, 4a, 4b / Modules 3 and 4 (baseline part).
- The supervisor appends the same `plan.cached` to every task record (background.py:632-644) and
  `report.render_markdown` sums `len(record.cached)` (report.py:556), so N tasks report N× the cached targets.
- `baseline._classify_group` sets `PYTHONPATH` to one distribution's `src` (baseline.py:165); every other
  distribution then imports from the main checkout's editable install instead of the baseline commit.
- `remove_baseline_checkout` runs a repository-global `git worktree prune` (baseline.py:131), which can drop the
  admin data of another session's worktree whose directory is momentarily missing.

---

## Scope

- Count distinct cached targets in `render_markdown`.
- Add `_baseline_pythonpath(checkout, src_dist)` and use it in `_classify_group`.
- Remove the `git worktree prune` call from `remove_baseline_checkout`.
- Tests for all three.

**NOT in scope**: `append_cached`'s per-task call pattern in background.py (unchanged); the report record schema;
the foreign-repo baseline layout (`issue:dee91130fa06`, open).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | union cached count |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | MODIFY | PYTHONPATH helper; drop prune |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | MODIFY | union count test |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py` | MODIFY | PYTHONPATH + no-prune tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import report  # verified: tests/flows/dev_loop/test_scope/test_report.py:11
from parrot.flows.dev_loop.test_scope import baseline  # verified: tests/flows/dev_loop/test_scope/test_baseline.py:9
import os  # verified: test_scope/baseline.py:12 (already imported)
from pathlib import Path  # verified: test_scope/baseline.py:18 (already imported)
```

### Existing Signatures to Use
```python
# test_scope/report.py
def render_markdown(records, order, *, final_head, rerun, rerun_skip_reason) -> str:  # line 491
#   cached = sum(len(record.cached) for record in records.values())   # line 556
#   rows.extend(["", f"cached (skipped, unchanged since green): {cached} target(s)"])  # line 557
# TaskTestRecord.cached: tuple[str, ...]  # line 69

# test_scope/baseline.py
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:  # line 74
def remove_baseline_checkout(worktree: Path, path: Path) -> None:  # line 125
#   proc = _git(worktree, "worktree", "remove", "--force", str(path))  # line 128
#   _git(worktree, "worktree", "prune")                                # line 131 — remove
def _classify_group(checkout: Path, dist: str, nodeids: list[str], timeout_s: int, tmp_dir: Path) -> dict[str, BaselineVerdict]:  # line 140
#   src_dist = "ai-parrot" if dist == "root" else dist                 # line 144
#   env["PYTHONPATH"] = str(checkout / "packages" / src_dist / "src")  # line 165

# tests/flows/dev_loop/test_scope/test_report.py
def _result(suite="core", **changes):  # line 26
def _record(task_id: str, result, head="final", cached=()):  # line 268
# existing assertion to keep green: "cached (skipped, unchanged since green): 2 target(s)"  # line 386
```

### Does NOT Exist
- ~~`baseline._baseline_pythonpath`~~ — this task creates it.
- ~~`report.count_cached`~~ — no such helper; inline the union.
- ~~`git worktree prune <path>`~~ — prune takes no path; there is no scoped prune.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#render_markdown",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py#remove_baseline_checkout",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py#_classify_group"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Stdlib only. `remove_baseline_checkout` must still never raise.
- PYTHONPATH order is deterministic: the target distribution first, then the rest sorted by path.
- Only include `packages/*/src` directories that exist in the checkout.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the cached sum with a union — *why*: per-task duplication must not inflate the count (AC-5).
2. Add `_baseline_pythonpath` above `_classify_group` and use it at line 165 — *why*: the baseline must import
   every distribution from the baseline commit (AC-6).
3. Delete the prune line — *why*: `worktree remove --force` already drops the admin entry; a global prune touches
   other sessions' worktrees (AC-6).
4. Write the tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    cached = sum(len(record.cached) for record in records.values())' report.py)
# REPLACE line 556 with:
    cached = len(set().union(*(record.cached for record in records.values())))
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        _git(worktree, "worktree", "prune")' baseline.py)
# DELETE line 131 (`        _git(worktree, "worktree", "prune")`) — nothing replaces it.

# occurrences: 1 (verified: grep -c 'def _classify_group(' baseline.py)
# BEFORE — insert above `def _classify_group(` (verified: baseline.py:140)
def _baseline_pythonpath(checkout: Path, src_dist: str) -> str:
    """Return a PYTHONPATH that imports every distribution from ``checkout``.

    Args:
        checkout: Root of the baseline checkout.
        src_dist: Distribution whose tests run (its ``src`` goes first).

    Returns:
        ``checkout/packages/<src_dist>/src`` followed by every other existing ``checkout/packages/*/src``
        (sorted), joined with ``os.pathsep``.
    """
    # FILL IN: first = checkout / "packages" / src_dist / "src"; others = sorted existing
    # (checkout / "packages").glob("*/src") dirs != first; return os.pathsep.join(str(p) for p in [first, *others])
    # — bounded by AC-6 (first entry always the target dist, even if it does not exist yet)


# occurrences: 1 (verified: grep -c '    env["PYTHONPATH"] = str(checkout / "packages" / src_dist / "src")' baseline.py)
# REPLACE line 165 with:
    env["PYTHONPATH"] = _baseline_pythonpath(checkout, src_dist)
```

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` (MODIFY — append)
```python
def test_render_cached_count_is_a_union_across_tasks():
    result = _result(passed=1, status="ok")
    cached = ("tests/test_one.py", "tests/test_two.py")
    records = {"TASK-1": _record("TASK-1", result, cached=cached), "TASK-2": _record("TASK-2", result, cached=cached)}
    output = report.render_markdown(records, ["TASK-1", "TASK-2"], final_head="final", rerun=None, rerun_skip_reason=None)
    assert "cached (skipped, unchanged since green): 2 target(s)" in output
```
FILL IN: adjust `_result(...)` kwargs to what the helper accepts (see test_report.py:26) — bounded by AC-5.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py` (MODIFY — append)
```python
def test_baseline_pythonpath_lists_every_checkout_src(tmp_path):
    for dist in ("ai-parrot", "ai-parrot-tools", "ai-parrot-server"):
        (tmp_path / "packages" / dist / "src").mkdir(parents=True)
    parts = baseline._baseline_pythonpath(tmp_path, "ai-parrot-tools").split(os.pathsep)
    # FILL IN: assert parts[0] is the ai-parrot-tools src and the other two follow in sorted order — AC-6


def test_remove_baseline_checkout_never_prunes(monkeypatch, tmp_path):
    calls = []

    def fake_git(cwd, *args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", "boom")

    monkeypatch.setattr(baseline, "_git", fake_git)
    baseline.remove_baseline_checkout(tmp_path, tmp_path / "baseline-x")
    # FILL IN: assert no recorded call has args[:2] == ("worktree", "prune") and the remove call happened — AC-6
```
(add `import os` at the top of test_baseline.py if absent — `subprocess` is already imported at line 3.)

### FILL IN checklist
- [ ] `_baseline_pythonpath` body — AC-6
- [ ] `test_baseline_pythonpath_lists_every_checkout_src` assertions — AC-6
- [ ] `test_remove_baseline_checkout_never_prunes` assertions — AC-6
- [ ] `_result` kwargs in the report test — AC-5

---

## Acceptance Criteria

- [ ] AC-5 Two records sharing two cached targets render `2 target(s)`.
- [ ] AC-6 `_classify_group`'s PYTHONPATH starts with the target dist's `src` and lists every other existing
      `packages/*/src`; `remove_baseline_checkout` never runs `git worktree prune`.
- [ ] Existing `test_report.py` and `test_baseline.py` tests stay green; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py -q`

---

## Test Specification

See the Blueprint test blocks above.

---

## Agent Instructions

1. Work in `feat-FEAT-830-test-scope-report-fixes`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
2. Verify the anchors (`grep -c`) before editing.
3. Implement from the Blueprint, complete every `FILL IN`, run the Validation Commands.
4. Commit only the listed files; close with `parrot sdd task close TASK-5274 test-scope-report-fixes verified`.

---

## Completion Note

**Completed by**: Claude Opus 5.5 (/sdd-fix session, actor agent:sdd-fix:c0b83d30)
**Date**: 2026-11-07
**Notes**: `render_markdown` counts the union of cached targets; `_baseline_pythonpath` puts the target dist's `src` first, then every other existing `packages/*/src` of the baseline checkout (Path order); the global `git worktree prune` was removed from `remove_baseline_checkout`. Validation Commands pass (58 tests), ruff clean.

**Deviations from spec**: none
