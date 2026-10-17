# TASK-4426: `ensure_worktree` drops and verifies the auto-upstream

**Feature**: FEAT-698 — /sdd-brief One-Command Brief Flow for Hotfixes and Single-Issue Fixes
**Spec**: `sdd/specs/sdd-brief-hotfix-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, design-research S6. `git worktree add -b X <path>
origin/<base>` makes `X` track `origin/<base>` (git's default
`branch.autoSetupMerge`). For a hotfix brief that base is `origin/main`, so a
bare `git push` from the fresh worktree targets **main** — the exact thing
the feature's anti-goals forbid. The hazard is documented in
`.claude/rules/worktree-management.md` and in auto-memory, but
`ensure_worktree.py` never enforces it. This task makes every worktree
`ensure()` *creates* come out with no upstream, and proves it.

---

## Scope

- Add `_clear_upstream(plan, target_path)` to `scripts/sdd/ensure_worktree.py`
  and call it right after `_create_worktree(...)` in `ensure()`.
- It unsets the upstream when one is configured and then asserts
  `@{upstream}` no longer resolves; any failure raises `EnsureWorktreeError`
  and discards the new worktree (same cleanup as a failed verification).
- Add tests to `tests/sdd_scripts/test_ensure_worktree.py`.

**NOT in scope**: the `--brief-key` CLI (TASK-4427, same file — runs after
this one); re-mutating a **reused** worktree (Step 1 reuse path must stay
read-only — an operator may have set an upstream on purpose).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/ensure_worktree.py` | MODIFY | `_clear_upstream` + call site |
| `tests/sdd_scripts/test_ensure_worktree.py` | MODIFY | upstream-absence tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure, main  # verified: scripts/sdd/ensure_worktree.py:25,48,225
from scripts.sdd.sdd_meta import FlowMeta, plan_worktree                  # verified: tests/sdd_scripts/test_ensure_worktree.py:12
```

### Existing Signatures to Use
```python
# scripts/sdd/ensure_worktree.py
class EnsureWorktreeError(RuntimeError)                                      # line 25
def _git(*args: str, cwd: Path) -> str                                       # line 29 — raises EnsureWorktreeError on rc != 0
def ensure(plan, *, repo_root, sync=True, require_paths=(), dry_run=False) -> tuple[Path, bool]  # line 48
    #   Step 4 call site:  `    _create_worktree(plan, target_path, repo_root=repo_root)`  # line 110
    #   Step 5 failure path calls _discard_new_worktree(plan, target_path, repo_root=repo_root)  # line 115
def _create_worktree(plan, target_path, *, repo_root) -> None                 # line 189
def _discard_new_worktree(plan, target_path, *, repo_root) -> None            # line 204

# tests/sdd_scripts/test_ensure_worktree.py
@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path        # line 18 — clone with origin + pushed `dev`
def _plan(branch: str = "dev")                  # line 56 — feature plan FEAT-999/demo-feature
```

### Does NOT Exist
- ~~any `--unset-upstream` call in `ensure_worktree.py`~~ — this task adds the first.
- ~~`ensure(..., keep_upstream=...)`~~ — do not add a flag; there is no legitimate caller that wants the base branch as upstream.
- ~~`git worktree add --no-track`~~ — do not switch to it: the reuse/refusal steps and the existing tests assume today's `worktree add -b` invocation; unset-after is the reviewed design.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/ensure_worktree.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_ensure_worktree.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/ensure_worktree.py#ensure",
    "sym:scripts/sdd/ensure_worktree.py#_create_worktree",
    "sym:scripts/sdd/ensure_worktree.py#_discard_new_worktree"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Probe with a plain `subprocess.run([...], check=False)` — **not** `_git()`,
  because "no upstream" is a non-zero exit of `git rev-parse @{upstream}` and
  `_git` would raise on it.
- Run the probes with `cwd=target_path` (the new worktree), not `repo_root`.
- Never touch the reuse path (Step 1 returns before Step 4).

---

## Implementation Blueprint

### Steps (in order)
1. Add `_clear_upstream` below `_create_worktree` — *why*: keeps creation helpers together.
2. Insert the call right after the Step 4 call site — *why*: the assertion must hold before Step 5 verification and before any caller sees the path.
3. Add the tests — *why*: AC-1/AC-2 are the safety property.

### `scripts/sdd/ensure_worktree.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    _create_worktree(plan, target_path, repo_root=repo_root)' scripts/sdd/ensure_worktree.py)
# AFTER — insert below `    _create_worktree(plan, target_path, repo_root=repo_root)` (verified: scripts/sdd/ensure_worktree.py:110)
    try:
        _clear_upstream(plan, target_path)
    except EnsureWorktreeError:
        _discard_new_worktree(plan, target_path, repo_root=repo_root)
        raise
```
```python
# AFTER — insert below the end of `def _create_worktree(...)` (verified: scripts/sdd/ensure_worktree.py:189-201)
_UPSTREAM_PROBE = ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")


def _clear_upstream(plan: WorktreePlan, target_path: Path) -> None:
    """Drop the upstream ``git worktree add -b`` sets and prove it is gone.

    ``worktree add -b <name> <path> origin/<base>`` makes ``<name>`` track
    ``origin/<base>``; for a hotfix that is ``origin/main``, so a bare
    ``git push`` would target main.

    Raises:
        EnsureWorktreeError: the upstream could not be unset or still resolves.
    """
    # FILL IN: probe = subprocess.run(["git", *_UPSTREAM_PROBE], cwd=target_path, capture_output=True,
    #          text=True, check=False); when rc == 0 -> _git("branch", "--unset-upstream", cwd=target_path);
    #          re-probe and raise EnsureWorktreeError naming plan.name if rc == 0 still — bounded by AC-1/AC-3
    raise NotImplementedError
```
**Why**: unset-then-verify (rather than trusting the unset's exit code) is
design-research S6's "assert `@{upstream}` is absent". Discarding on failure
reuses the existing verified cleanup instead of leaving a half-safe worktree.

### `tests/sdd_scripts/test_ensure_worktree.py` (MODIFY)
```python
# APPEND at end of file
def _upstream(worktree: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        cwd=worktree, capture_output=True, text=True, check=False,
    )


def test_created_worktree_has_no_upstream(tmp_git_repo: Path) -> None:
    """A fresh worktree from origin/<base> must not track it (FEAT-698 S6)."""
    path, created = ensure(_plan(), repo_root=tmp_git_repo)
    assert created is True
    assert _upstream(path).returncode != 0

# FILL IN: test_reused_worktree_upstream_untouched — set an upstream on the reused branch by hand,
#          call ensure() again, assert it still resolves (AC-2)
# FILL IN: test_clear_upstream_failure_discards_worktree — monkeypatch _clear_upstream to raise,
#          assert EnsureWorktreeError and that the path no longer exists (AC-3)
```

### FILL IN checklist
- [ ] `_clear_upstream` body — bounded by AC-1/AC-3
- [ ] reuse-path test — AC-2
- [ ] failure/discard test — AC-3

---

## Acceptance Criteria

- [ ] AC-1: a worktree created by `ensure()` from `origin/dev` has no upstream (`git rev-parse @{upstream}` fails inside it).
- [ ] AC-2: a reused worktree's existing upstream is left exactly as it was.
- [ ] AC-3: if the upstream cannot be cleared, `ensure()` raises `EnsureWorktreeError` and the new worktree directory and branch are discarded.
- [ ] All pre-existing tests in `test_ensure_worktree.py` still pass.
- [ ] `ruff check scripts/sdd/ensure_worktree.py tests/sdd_scripts/test_ensure_worktree.py` clean.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`

---

## Test Specification

See the MODIFY block above: `test_created_worktree_has_no_upstream`,
`test_reused_worktree_upstream_untouched`,
`test_clear_upstream_failure_discards_worktree`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-brief-hotfix-flow --feature-id FEAT-698`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-brief-hotfix-flow.json`
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands from the worktree root
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4426 sdd-brief-hotfix-flow verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
