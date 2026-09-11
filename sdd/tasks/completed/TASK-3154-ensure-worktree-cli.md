# TASK-3154: `ensure_worktree.py` — idempotent worktree provisioning CLI

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3153
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Five markdown files each hand-roll their own variant of
"create the worktree" — and they disagree. `sdd-worker` §3 is the only one that
is idempotent (`git worktree list | grep … || git worktree add … HEAD`), and it
is also the one that silently drops the FEAT-466 hotfix rule. This task replaces
all five with one command.

It is the dependency of every markdown task in this feature (TASK-3155 through
TASK-3158), so land it before them: once those files start naming
`scripts.sdd.ensure_worktree`, the script must already exist.

---

## Scope

- Create `scripts/sdd/ensure_worktree.py`: `EnsureWorktreeError`, `ensure()`,
  `main()`, with `--json` output (spec §8, resolved 2026-09-11).
- Create `tests/sdd_scripts/test_ensure_worktree.py` with a real temporary git
  repo fixture.

**NOT in scope**: editing any `.claude/**` file or `CLAUDE.md` (TASK-3155 to
TASK-3159); removing, pruning or renaming any existing worktree or branch.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/ensure_worktree.py` | CREATE | Provisioning CLI |
| `tests/sdd_scripts/test_ensure_worktree.py` | CREATE | Unit + integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from scripts.sdd.sdd_meta import (          # verified: scripts/sdd/sdd_meta.py
    FlowMeta,                                # line 41
    WorktreePlan,                            # added by TASK-3153
    plan_worktree,                           # added by TASK-3153
    resolve_flow,                            # line 104
    WORKTREE_ROOT,                           # added by TASK-3153
)
```

### Existing Signatures to Use
```python
# scripts/sdd/sdd_meta.py
class FlowMeta(BaseModel):                            # line 41
    type: Literal["feature", "hotfix"]                # line 44
    base_branch: str                                  # line 45

def resolve_flow(*, kind=None, doc_path=None,
                 type_override=None,
                 base_branch_override=None) -> FlowMeta: ...   # line 104

# added by TASK-3153
class WorktreePlan(BaseModel):
    name: str
    path: str       # repo-relative, ".claude/worktrees/<name>"
    base_ref: str   # "origin/<base_branch>"

def plan_worktree(meta, *, slug, feature_id=None, jira_key=None) -> WorktreePlan: ...
```

The per-spec index header is the CLI's practical input source and carries the
flow metadata (verified: `sdd/tasks/index/token-budget-bedrock.json`):
```json
{"feature": "token-budget-bedrock", "feature_id": "FEAT-550",
 "spec": "sdd/specs/token-budget-bedrock.spec.md",
 "type": "feature", "base_branch": "dev"}
```

### Does NOT Exist
- ~~`scripts/sdd/ensure_worktree.py`~~ — this task creates it
- ~~an async helper / `aiohttp` in `scripts/sdd/`~~ — these scripts are plain
  synchronous CLIs (see `reserve_ids.py`); do NOT make this one async
- ~~`SubWorktreeManager` creates the feature worktree~~ — it creates *per-worker
  sub-worktrees* under an existing feature worktree
  (`packages/ai-parrot/src/parrot/flows/dev_loop/worktree_manager.py:78`, arg
  `base_worktree` = "the feature's primary worktree"). Do not import or extend it.
- ~~`.worktrees/_active.json`~~ — no SDD command reads or writes it; do not
  create it

---

## Implementation Notes

### Key Constraints
- **Never destructive.** No `git worktree remove`, no `git branch -D`, no
  `reset --hard`, no `checkout` of a local branch. Provision only.
- **Never touches local branches.** It fetches, then branches directly off the
  remote ref. That is what makes it safe to run from inside another worktree,
  and it avoids the "reset --hard ate my commits" failure this repo has hit.
- Idempotent: calling it twice must exit 0 twice, print the same path, and leave
  exactly one branch.
- Refuse rather than guess: a path occupied by a different branch, or an
  existing branch with no worktree, is an error with an actionable message.
- Exit codes: `0` success (created or reused), `1` any `EnsureWorktreeError`.
- Stdout is the machine interface: the bare path, or one JSON object with
  `--json`. Everything else goes to stderr.

### References in Codebase
- `scripts/sdd/reserve_ids.py` — the house style for a git-touching SDD CLI
  (subprocess usage, error reporting, `main(argv)` shape)
- `.claude/agents/sdd-worker.md:194-195` — the create-or-reuse idiom being replaced

---

## Implementation Blueprint

### Steps (in order)
1. Write the module with `ensure()` first, `main()` after — *why*: `ensure()` is
   what the tests exercise directly; `main()` is a thin argparse wrapper.
2. Implement the six steps of `ensure()` in the documented order — *why*: reuse
   must be detected *before* any fetch, so running inside the target worktree is
   a cheap no-op.
3. Build the git fixture, then write the tests — *why*: every behaviour here is
   about real git state; mocks would prove nothing.

### `scripts/sdd/ensure_worktree.py` (CREATE)
```python
"""Idempotent feature/hotfix worktree provisioning for SDD commands (FEAT-552).

Replaces the hand-rolled ``git worktree add`` blocks that used to live in
``/sdd-task``, ``/sdd-start``, ``sdd-worker``, ``sdd-planner``,
``sdd-research`` and ``sdd-autopilot``. Naming and base ref come from
``scripts.sdd.sdd_meta.plan_worktree`` — never built here.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from scripts.sdd.sdd_meta import FlowMeta, WorktreePlan, plan_worktree, resolve_flow

logger = logging.getLogger(__name__)


class EnsureWorktreeError(RuntimeError):
    """Raised when the worktree cannot be provisioned (CLI exit code 1)."""


def _git(*args: str, cwd: Path) -> str:
    """Run a git command, returning stdout; raise EnsureWorktreeError on failure."""
    # FILL IN: subprocess.run(["git", *args], cwd=cwd, capture_output=True,
    #   text=True, check=False); on returncode != 0 raise EnsureWorktreeError
    #   including the command and stderr — bounded by "refuse rather than guess"
    raise NotImplementedError


def ensure(
    plan: WorktreePlan,
    *,
    repo_root: Path,
    sync: bool = True,
    require_paths: Sequence[str] = (),
    dry_run: bool = False,
) -> tuple[Path, bool]:
    """Create the worktree if absent, reuse it if present, and verify it.

    Steps, in order:
      1. Reuse — if ``git worktree list --porcelain`` already lists a worktree
         whose path basename is ``plan.name``, confirm its checked-out branch
         is ``plan.name`` and return it. A path holding a DIFFERENT branch is
         an error, never a silent reuse.
      2. Sync (skipped when ``sync`` is False) — ``git fetch origin
         <base_branch>``. No local branch is checked out; no local commit moves.
      3. Refuse when a branch named ``plan.name`` exists but is checked out
         nowhere — the operator decides (reuse it, or pick another slug).
      4. Create — ``git worktree add -b <name> <path> <base_ref>``.
      5. Verify — every ``require_paths`` entry must exist inside the worktree.
         A miss means the base does not carry the task artifacts yet.
      6. Return ``(absolute_path, created)``.

    Args:
        plan: The naming/base-ref decision from ``plan_worktree``.
        repo_root: Absolute path to the main clone.
        sync: Fetch ``origin/<base_branch>`` before creating.
        require_paths: Repo-relative paths that must exist in the worktree.
        dry_run: Resolve and report without running any mutating git command.

    Returns:
        ``(path, created)`` — ``created`` is False when an existing worktree
        was reused.

    Raises:
        EnsureWorktreeError: On any refusal above, or a failing git command.
    """
    # FILL IN: the six steps above, in order — bounded by the docstring and by
    #   tests/sdd_scripts/test_ensure_worktree.py. Step 5 must remove nothing
    #   on failure beyond the worktree this call itself created (AC-5).
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Prints the worktree path to stdout; 0 on success.

    With ``--json``, prints one object instead —
    ``{"name": …, "path": …, "base_ref": …, "created": bool}`` — so
    ``sdd-planner``/``sdd-research`` can lift ``worktree_path`` straight into
    their ``PlannerOutput``/``ResearchOutput`` contracts (spec §8).
    """
    # FILL IN: argparse with --slug (required), --feature-id, --jira-key,
    #   --spec, --index, --base-branch, --type, --no-sync, --dry-run, --json;
    #   resolve_flow(type_override=…, base_branch_override=…) -> plan_worktree
    #   -> ensure(require_paths=[p for p in (spec, index) if p]); print and
    #   return 0, or print the EnsureWorktreeError to stderr and return 1 —
    #   bounded by AC-6/AC-7
    raise NotImplementedError


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```
**Why this shape**: `ensure()` returns `(path, created)` because `--json` must
report `created` and the human path must not. Steps are numbered in the
docstring because their *order* is the contract: reuse before fetch keeps the
common `/sdd-start`-inside-the-worktree case free of network I/O. `_git` is a
single choke point so every git failure becomes one error type. Do not change
the function names or the flag names — TASK-3155 to TASK-3158 write them into
five markdown files.

### `tests/sdd_scripts/test_ensure_worktree.py` (CREATE)
```python
"""Tests for ``scripts.sdd.ensure_worktree`` — FEAT-552 / TASK-3154."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure, main
from scripts.sdd.sdd_meta import FlowMeta, plan_worktree

SLUG = "demo-feature"
FEATURE_ID = "FEAT-999"


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """A clone with an `origin` remote, a `dev` branch, and the SDD artifacts.

    Shape: `origin.git` (bare) <- `work` (the clone under test). `work` has
    sdd/specs/demo-feature.spec.md and sdd/tasks/index/demo-feature.json
    committed on `dev` and pushed, so `origin/dev` carries them.
    """
    # FILL IN: git init --bare origin.git; git init work; user.email/user.name;
    #   write the two sdd files; commit; git branch -M dev; remote add origin;
    #   push -u origin dev — bounded by "require_paths must be satisfiable"


def _plan(branch: str = "dev"):
    return plan_worktree(
        FlowMeta(type="feature", base_branch=branch), slug=SLUG, feature_id=FEATURE_ID
    )


def test_ensure_creates_worktree_when_absent(tmp_git_repo: Path) -> None:
    """First call creates the branch and the directory and reports created=True."""
    path, created = ensure(_plan(), repo_root=tmp_git_repo)
    assert created is True
    assert path.is_dir()
    assert path.name == f"feat-{FEATURE_ID}-{SLUG}"


def test_ensure_is_idempotent(tmp_git_repo: Path) -> None:
    """Second call reuses: same path, created=False, still exactly one branch."""
    first, _ = ensure(_plan(), repo_root=tmp_git_repo)
    second, created = ensure(_plan(), repo_root=tmp_git_repo)
    assert second == first and created is False
    # FILL IN: assert `git branch --list feat-FEAT-999-demo-feature` yields one line


def test_ensure_rejects_path_with_foreign_branch(tmp_git_repo: Path) -> None:
    """A worktree at the target path on another branch is an error, not a reuse."""
    # FILL IN: create the worktree, then force its branch elsewhere, then
    #   pytest.raises(EnsureWorktreeError) — bounded by step 1 of ensure()


def test_ensure_rejects_existing_unchecked_branch(tmp_git_repo: Path) -> None:
    """A leftover branch with no worktree must be reported, not reused blindly."""
    # FILL IN: git branch feat-FEAT-999-demo-feature, then pytest.raises with a
    #   message naming the branch — bounded by step 3


def test_ensure_requires_paths_visible(tmp_git_repo: Path) -> None:
    """Branching from a base that lacks the task artifacts must fail loudly."""
    # FILL IN: require_paths=["sdd/tasks/index/absent.json"]; assert it raises
    #   and that the half-created worktree is not left behind — bounded by step 5


def test_ensure_dry_run_mutates_nothing(tmp_git_repo: Path) -> None:
    """--dry-run resolves and reports; `git worktree list` is unchanged."""
    # FILL IN: capture worktree list before/after, assert equal


def test_ensure_json_output_shape(tmp_git_repo: Path, capsys, monkeypatch) -> None:
    """--json emits one object with name/path/base_ref/created."""
    # FILL IN: monkeypatch.chdir(tmp_git_repo); main([...,"--json"]) twice;
    #   json.loads each stdout; assert keys and created True then False
```
**Why**: every test drives real git in a throwaway repo — the behaviours under
test (reuse, refusal, base ref) exist only as git state. `tmp_git_repo` builds a
bare `origin` because `base_ref` is `origin/dev`; a fixture without a remote
cannot exercise the real code path.

### FILL IN checklist
- [ ] `ensure_worktree.py::_git` — subprocess call + error wrapping; bounded by "one choke point for git failures"
- [ ] `ensure_worktree.py::ensure` — the six documented steps in order; bounded by AC-1..AC-5
- [ ] `ensure_worktree.py::main` — argparse surface and output modes; bounded by AC-6/AC-7 and the flag names quoted above
- [ ] `test_ensure_worktree.py::tmp_git_repo` — the bare-origin + clone fixture
- [ ] six stubbed test bodies; bounded by their docstrings and spec §4

---

## Acceptance Criteria

- [ ] AC-1 `ensure()` creates `.claude/worktrees/<plan.name>` on a branch of the same name, from `origin/<base_branch>`
- [ ] AC-2 A second identical call exits 0, returns the same path with `created=False`, and leaves exactly one matching branch
- [ ] AC-3 A target path holding a different branch raises `EnsureWorktreeError` and mutates nothing
- [ ] AC-4 An existing branch with no worktree raises `EnsureWorktreeError` whose message names the branch
- [ ] AC-5 A `require_paths` entry missing from the worktree raises, and no half-created worktree is left behind
- [ ] AC-6 `python -m scripts.sdd.ensure_worktree --help` exits 0; a run without `--json` prints the bare path on stdout and nothing else
- [ ] AC-7 `--json` prints one parseable object with `name`, `path`, `base_ref`, `created`
- [ ] AC-8 `--dry-run` leaves `git worktree list` unchanged
- [ ] AC-9 The module contains no `git worktree remove`, `git branch -D`, `reset --hard`, or `checkout` of a local branch: `grep -nE "worktree remove|branch -D|reset --hard" scripts/sdd/ensure_worktree.py` returns nothing
- [ ] All tests pass: `pytest tests/sdd_scripts/test_ensure_worktree.py -v`
- [ ] No linting errors: `ruff check scripts/sdd/ensure_worktree.py tests/sdd_scripts/test_ensure_worktree.py`

---

## Test Specification

See the blueprint block for `tests/sdd_scripts/test_ensure_worktree.py` — seven
tests plus the `tmp_git_repo` fixture. Names are fixed by spec §4.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 2, §7 Known Risks)
2. **Check dependencies** — TASK-3153 must be in `sdd/tasks/completed/`; confirm
   `plan_worktree` and `WorktreePlan` import cleanly before writing anything
3. **Verify the Codebase Contract**
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3154-ensure-worktree-cli.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker orchestrator (FEAT-549 pool) + sdd-worker fixup
**Date**: 2026-09-11
**Notes**: Implemented `ensure()`, `EnsureWorktreeError`, and `main()`/CLI in
`scripts/sdd/ensure_worktree.py` with `tests/sdd_scripts/test_ensure_worktree.py`;
all 7 tests pass. AC-1 through AC-8 verified (help exits 0, bare-path and
`--json` stdout shapes checked live, `--dry-run` leaves `git worktree list`
unchanged). AC-9 initially FAILED on merge — the cleanup-on-failed-verification
branch had a comment that quoted the forbidden git-command substrings in
prose (explaining what NOT to do), which the literal grep matched even
though the actual code only calls a plain non-forced branch delete on a
branch it just created. Fixed by rewording the comment only, no behavior
change; re-verified AC-9 grep returns nothing, tests still 7/7, ruff clean.

**Deviations from spec**: none (the AC-9 fix touched only the file already
listed for this task)

Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 1
(merged first try) · Duration: 43.01s · Tokens: 287432 in / 5714 out
(+ sdd-worker direct fixup for AC-9 comment reword, untimed)
