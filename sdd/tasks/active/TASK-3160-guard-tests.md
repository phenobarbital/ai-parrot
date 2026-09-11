# TASK-3160: Guard tests that keep worktree creation where it belongs

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3155, TASK-3156, TASK-3157, TASK-3158, TASK-3159
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8, remainder. TASK-3153 and TASK-3154 carry their own unit tests.
What is left is the part no unit test can cover: the *convention*. Nothing today
stops someone from pasting `git worktree add` back into `/sdd-task`, or from
reintroducing `feat-<id>-<slug>` in a new agent — which is exactly how this repo
ended up with two templates and 13 stale worktrees.

This task makes the convention executable. It runs last, because every assertion
it makes is false until TASK-3155 to TASK-3159 have landed.

---

## Scope

- Create `tests/sdd_scripts/test_command_contracts.py` with the three
  convention tests from spec §4.

**NOT in scope**: editing any command or agent (if a test fails, the bug is in
the earlier task, and it goes back there); auditing or removing existing
worktrees (spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/sdd_scripts/test_command_contracts.py` | CREATE | Three convention guards |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
from pathlib import Path
import pytest
```
Repo-root resolution follows the existing sibling (verified:
`tests/sdd_scripts/test_command_twin_parity.py:19`):
```python
_REPO_ROOT = Path(__file__).resolve().parents[2]
```

### Existing Signatures to Use
```
tests/sdd_scripts/                       # the suite this file joins
  test_command_twin_parity.py:19  _REPO_ROOT = Path(__file__).resolve().parents[2]
  test_command_twin_parity.py:21  _TWINNED = ("sdd-spec", "sdd-task")
  test_command_twin_parity.py:62  @pytest.mark.parametrize("name", _TWINNED)
```
Files under test, and who is expected to create a worktree after FEAT-552:

| File | May contain `git worktree add`? | Must name `ensure_worktree`? |
|---|---|---|
| `.claude/commands/sdd-task.md` | no | no |
| `.claude/commands/sdd-start.md` | no | yes |
| `.claude/agents/sdd-worker.md` | no | yes |
| `.claude/agents/sdd-planner.md` | no | yes |
| `.claude/agents/sdd-research.md` | no | yes |
| `.claude/agents/sdd-autopilot.md` | no | yes |
| `CLAUDE.md` | (examples only — excluded from the ban) | yes |

### Does NOT Exist
- ~~`tests/sdd_scripts/test_command_contracts.py`~~ — this task creates it
- ~~a pytest plugin that lints markdown in this repo~~ — plain `read_text()` +
  `in` checks, like `test_command_twin_parity.py`
- ~~`.claude/worktrees/` being absent~~ — it exists and holds live worktrees
  whose copies of these files are stale by design; any glob MUST exclude it or
  the tests will fail on unrelated historical checkouts

---

## Implementation Notes

### Key Constraints
- Skip, do not fail, when a target file is missing — the suite also runs against
  checkouts where `.claude/` is absent (the sibling parity test does exactly
  this with `pytest.skip`).
- Never walk into `.claude/worktrees/`. Those are separate checkouts of older
  branches; they legitimately contain the old text.
- Assert on substrings, not line numbers — line numbers move.
- Keep the test names from spec §4; they are referenced by the spec's test table.

---

## Implementation Blueprint

### Steps (in order)
1. Write the three tests — *why*: each maps to one acceptance criterion of the
   feature that would otherwise be verified once, by hand, and never again.
2. Run the full `tests/sdd_scripts/` suite — *why*: this file is the last gate;
   if an earlier task drifted, this is where it surfaces.

### `tests/sdd_scripts/test_command_contracts.py` (CREATE)
```python
"""Convention guards for SDD worktree ownership — FEAT-552 / TASK-3160.

Worktree creation belongs to whoever writes code in the worktree
(`/sdd-start`, `sdd-worker`) and to the dev-loop orchestrators that plan and
dispatch in one run (`sdd-planner`, `sdd-research`, `sdd-autopilot`). Planning
alone (`/sdd-task`) creates none. All of them go through
`scripts.sdd.ensure_worktree`, so exactly one naming rule exists.

These tests keep that true. `.claude/worktrees/` is never inspected: those are
separate checkouts of older branches and legitimately hold the old text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Files that must not hand-roll a worktree, and whether they must instead
#: name the shared CLI.
_CREATORS: dict[str, bool] = {
    ".claude/commands/sdd-task.md": False,
    ".claude/commands/sdd-start.md": True,
    ".claude/agents/sdd-worker.md": True,
    ".claude/agents/sdd-planner.md": True,
    ".claude/agents/sdd-research.md": True,
    ".claude/agents/sdd-autopilot.md": True,
}

_LEGACY_TEMPLATE = "feat-<id>-<slug>"


def _read(rel: str) -> str:
    path = _REPO_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} missing at this checkout")
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", sorted(_CREATORS))
def test_no_command_hand_rolls_a_worktree(rel: str) -> None:
    """No SDD command or agent runs `git worktree add` itself (FEAT-552)."""
    assert "git worktree add" not in _read(rel), (
        f"{rel} hand-rolls a worktree; call "
        "`python -m scripts.sdd.ensure_worktree` instead"
    )


@pytest.mark.parametrize(
    "rel", sorted(r for r, needs_cli in _CREATORS.items() if needs_cli)
)
def test_every_creator_calls_ensure_worktree(rel: str) -> None:
    """Each lane that provisions a worktree goes through the shared CLI."""
    # FILL IN: assert "scripts.sdd.ensure_worktree" in _read(rel), with a
    #   message naming the file — bounded by the table in this task's
    #   Codebase Contract


def test_no_legacy_naming_template_remains() -> None:
    """`feat-<id>-<slug>` is gone: one template, owned by plan_worktree."""
    # FILL IN: walk _REPO_ROOT / ".claude" for *.md, skipping any path with
    #   "worktrees" in its parts, plus CLAUDE.md; collect files containing
    #   _LEGACY_TEMPLATE; assert the collection is empty and name the offenders
    #   — bounded by "never walk into .claude/worktrees/"
```
**Why this shape**: one dict drives both parametrized tests, so adding a future
creator means adding one line, not a new test. `/sdd-task` is in the same dict
with `False` precisely so that a reader sees it is *deliberately* not a creator
rather than merely absent.

### FILL IN checklist
- [ ] `test_every_creator_calls_ensure_worktree` body; bounded by the Codebase
      Contract table
- [ ] `test_no_legacy_naming_template_remains` body; bounded by the
      "never walk into .claude/worktrees/" constraint

---

## Acceptance Criteria

- [ ] `pytest tests/sdd_scripts/test_command_contracts.py -v` passes, with the six + one parametrized cases actually running (not skipped) in this checkout
- [ ] Reintroducing `git worktree add` into `.claude/commands/sdd-task.md` makes `test_no_command_hand_rolls_a_worktree` fail (verify once, then revert)
- [ ] The tests never read anything under `.claude/worktrees/`
- [ ] Full suite green: `pytest tests/sdd_scripts/ -q`
- [ ] Feature-wide: `pytest tests/sdd_scripts/ packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q` passes
- [ ] No linting errors: `ruff check tests/sdd_scripts/test_command_contracts.py`

---

## Test Specification

The file itself is the test specification — see the blueprint block.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 8, §4)
2. **Check dependencies** — TASK-3155 through TASK-3159 must all be in
   `sdd/tasks/completed/`. If any is not, STOP: these assertions are false until
   they land, and "fixing" them here would hide the real gap.
3. **Verify the Codebase Contract**
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** all acceptance criteria — including the deliberate-failure check
7. **Move this file** to `sdd/tasks/completed/TASK-3160-guard-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
