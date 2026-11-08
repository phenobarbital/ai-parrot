# TASK-5297: Re-attach an orphaned brief branch in the feature launcher

**Feature**: FEAT-837 — Brief Worktrees Survive the Worktree-Root Migration
**Spec**: `sdd/specs/dev-loop-feature-launcher-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1b8289182630`

---

## Context

`issue:1b8289182630`: after the brief worktree `hotfix-NAV-7762-…` vanished,
its branch survived, but `parrot sdd launch worker NAV-7762` failed with
`could not uniquely resolve feature` because `_resolve_briefs()` only scans
existing worktrees. Recovery needed a manual `git worktree add`. This task
implements spec §3 Module 2 (goal G3; AC3, AC4, AC5).

---

## Scope

- Add `_reattach_brief_branch(primary: Path, key: str) -> list[FeatureRef]` to
  `feature_launcher.py`.
- Call it from `resolve_feature()` when `_resolve_briefs()` finds nothing.
- Update the two comments that say a brief worktree is never created.
- Add tests in `test_sdd_launch.py`.

**NOT in scope**: `ensure_worktree`, `parrot/sdd/config.py` (TASK-5296),
importing anything outside the standard library into the launcher.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | `_reattach_brief_branch` + wiring |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | re-attach tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# feature_launcher.py already imports (lines 8-26): argparse, dataclass, json, os, Path, re, shutil,
# subprocess, sys, time, Mapping, Sequence, native_claude_sandbox, worktree_environment.
# Add NO import — everything needed is already there.
import parrot.flows.dev_loop.feature_launcher as launcher  # how test_sdd_launch.py imports it
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py
@dataclass(frozen=True)
class FeatureRef:  # line 30
    feature_id: str; slug: str; spec: str; index: str
    worktree: str | None = None  # line 37 — comment says "(never created here)"
class LaunchError(Exception):  # line 50; __init__(self, exit_code: int, message: str)
def _run(argv: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]  # line 58; raises LaunchError(1) on OSError
def _require(result) -> subprocess.CompletedProcess[str]  # line 74; non-zero → LaunchError(1, stderr)
def resolve_feature(primary: Path, key: str) -> FeatureRef  # line 115
    #   line 134-135:  if not matches:
    #                      matches = _resolve_briefs(primary, key)
    #   line 136-137:  if len(matches) != 1: raise LaunchError(2, f"could not uniquely resolve feature {key!r}")
def _worktree_paths(primary: Path) -> list[Path]  # line 144
def _resolve_briefs(primary: Path, key: str) -> list[FeatureRef]  # line 168; docstring line 171 "A brief lives only in its own worktree"

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_root.py — `python -m parrot.sdd.scripts.worktree_root --root <primary>`
#   prints the resolved worktree root + "\n", exit 0

# packages/ai-parrot/tests/sdd/test_sdd_launch.py helpers:
#   _result(argv, code=0, stdout="", stderr="") (line 41); _primary(tmp_path) (line 46, NOT a git repo);
#   _brief_worktree(tmp_path, slug="fix-thing", key=None, name="brief-wt") (line 82);
#   _list_worktrees(monkeypatch, *roots) (line 105) — fakes only `git worktree list`
```

### Does NOT Exist

- ~~`feature_launcher.worktree_root`~~ / any root resolver in the launcher — shell out to `parrot.sdd.scripts.worktree_root`.
- ~~`from parrot.sdd.config import ...`~~ in the launcher — forbidden (stdlib-only `python -S` script, AC5).
- ~~`ensure_worktree --recreate`~~ / reattach flag — does not exist.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#resolve_feature",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#_resolve_briefs",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#_run",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#_require"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **A failed `for-each-ref` means "no candidates"**, not an error: the existing
  test `test_resolve_feature_brief_missing_or_ambiguous_is_exit_2` resolves
  `"nope"` in a non-git `_primary` and must still get the exit-2
  "could not uniquely resolve" error.
- Every git/python call goes through `_run` (the test seam).
- Zero candidates must run no `worktree_root` and no `worktree add`.

---

## Implementation Blueprint

### Steps (in order)

1. Add `_reattach_brief_branch` right after `_resolve_briefs` — *why*: it reuses `_resolve_briefs` to build the ref.
2. Wire it into `resolve_feature` — *why*: only when no existing worktree holds the brief.
3. Update the two comments — *why*: they would now be false.
4. Write tests with a fake `_run` covering for-each-ref / worktree list / worktree_root / worktree add.

### `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '        matches = _resolve_briefs(primary, key)' feature_launcher.py)
# REPLACE lines 134-135 (verified: feature_launcher.py:134-135)
    if not matches:
        matches = _resolve_briefs(primary, key) or _reattach_brief_branch(primary, key)
```

```python
# AFTER — append below the end of `_resolve_briefs` (its `return matches`, before `def ensure_feature_worktree`)
def _reattach_brief_branch(primary: Path, key: str) -> list[FeatureRef]:
    """Re-attach a surviving ``hotfix-<key>-*`` / ``fix-<key>-*`` branch whose worktree is gone.

    Only a branch no worktree has checked out qualifies; it is added under the resolved worktree root and the
    brief is then resolved from it. Returns ``[]`` when there is no candidate.

    Raises:
        LaunchError: exit 2 for ambiguous candidates or an occupied destination; exit 1 when git fails.
    """
    pattern = re.compile(rf"^(?:hotfix|fix)-{re.escape(key)}-.+$", re.IGNORECASE)
    refs = _run(
        ["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin"], cwd=primary
    )
    if refs.returncode:
        return []
    local: set[str] = set()
    remote: set[str] = set()
    # FILL IN: split refs.stdout lines; strip "refs/heads/" into local, "refs/remotes/origin/" into remote
    #          (skip "HEAD"); keep only names matching `pattern`
    listing = _run(["git", "worktree", "list", "--porcelain"], cwd=primary)
    checked_out = {
        line.removeprefix("branch refs/heads/")
        for line in (listing.stdout.splitlines() if not listing.returncode else [])
        if line.startswith("branch refs/heads/")
    }
    candidates = sorted((local | remote) - checked_out)
    if not candidates:
        return []
    if len(candidates) > 1:
        raise LaunchError(2, f"ambiguous brief branches for {key!r}: {', '.join(candidates)}")
    branch = candidates[0]
    root = _require(
        _run([sys.executable, "-m", "parrot.sdd.scripts.worktree_root", "--root", str(primary)], cwd=primary)
    ).stdout.strip()
    destination = Path(root) / branch
    if os.path.lexists(destination):
        raise LaunchError(2, f"cannot re-attach {branch}: {destination} already exists")
    # FILL IN: local → ["git", "worktree", "add", str(destination), branch];
    #          origin-only → ["git", "worktree", "add", "--no-track", "-b", branch, str(destination), f"origin/{branch}"];
    #          _require(_run(argv, cwd=primary)) — bounded by AC3
    print(f"launch-worker: re-attached brief branch {branch} at {destination}", file=sys.stderr)
    return _resolve_briefs(primary, key)
```

**Why**: G3. Also change the comment at line 37 to
`# set for a brief: its worktree (re-attached from its branch when missing, never newly created)` and add to the
`_resolve_briefs` docstring: "When no worktree holds it, ``_reattach_brief_branch`` may re-attach its branch."

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)

```python
# AFTER — append after test_resolve_feature_prefers_feature_index_over_brief (verified: test_sdd_launch.py:150)
def _reattach_runner(monkeypatch, tmp_path, *, refs: list[str], checked_out: list[str], calls: list[list[str]]):
    """Fake _run: for-each-ref → refs; worktree list → primary + checked_out; worktree_root → tmp_path/'wt-root';
    worktree add → creates a brief worktree at the destination via _brief_worktree-like files."""
    # FILL IN: record every argv in calls; on `worktree add`, materialise sdd/briefs/<slug>.index.json under the
    #          destination and make later `worktree list` calls include it


def test_resolve_feature_reattaches_orphan_brief_branch(tmp_path, monkeypatch) -> None:
    """One un-checked-out local hotfix-<KEY>-* branch is re-attached under the worktree root and resolved."""
    # FILL IN: refs=["refs/heads/hotfix-NAV-7762-ecotank"], key "NAV-7762" → ref.is_brief,
    #          `git worktree add <root>/hotfix-NAV-7762-ecotank hotfix-NAV-7762-ecotank` in calls


def test_reattach_origin_only_branch_uses_no_track(tmp_path, monkeypatch) -> None:
    """An origin-only branch is created with --no-track -b from origin/<branch>."""
    # FILL IN


def test_reattach_ambiguous_or_blocked_is_exit_2(tmp_path, monkeypatch) -> None:
    """Two candidates, an existing destination, or an already checked-out branch → exit 2, no worktree add."""
    # FILL IN: three sub-cases; assert no argv containing "worktree", "add" in calls for each
```

### FILL IN checklist

- [ ] ref parsing in `_reattach_brief_branch` — bounded by "local preferred, origin dedup"
- [ ] `worktree add` argv choice — bounded by AC3
- [ ] `_reattach_runner` fake + three tests — bounded by AC3/AC4

---

## Acceptance Criteria

- [ ] AC3: one un-checked-out `hotfix-KEY-*`/`fix-KEY-*` branch is re-attached under the resolved root; brief ref returned.
- [ ] AC4: ambiguous / occupied destination / no candidate → exit 2 with no `worktree add`.
- [ ] AC5: no new import in `feature_launcher.py`.
- [ ] Existing `test_sdd_launch.py` tests still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

---

## Test Specification

See the blueprint test stubs above.

---

## Agent Instructions

Implement exactly the scope above inside the FEAT-837 worktree; run tests with
`PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note

**Completed by**: Claude (Opus 5.5) via /sdd-fix issue:1b8289182630 — 2026-11-07
**Commit**: e5e65957fe

- `_reattach_brief_branch()` added; `resolve_feature()` falls back to it when no worktree holds the brief.
  A failed `for-each-ref` (non-git primary) returns `[]`, so the existing "nope" test still gets exit 2.
- Local branch → `git worktree add <root>/<branch> <branch>`; origin-only → `--no-track -b`.
- Tests: re-attach local, origin-only, and ambiguous / occupied / checked-out / no-match (exit 2, no add).
  `test_sdd_launch.py`: 66 passed. ruff + black clean; `python -S` import still stdlib-only.
