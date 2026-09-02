# TASK-2735: Git-verified triage evidence in `QANode._run_finding_triage`

**Feature**: FEAT-497 — QA Gate: Verified Triage Evidence & Diff-Scoped Lint
**Spec**: `sdd/specs/qa-gate-evidence-and-diff-scoped-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (goals G1 + G2). `QANode._run_finding_triage` currently
returns `list(report.files_modified)` — a field the triage LLM fills in and
nobody checks against git. That claimed list (a) triggers a full re-run of
the deterministic QA gate and (b) is the *only* evidence
`_confirm_has_evidence` accepts for a CONFIRM disposition, so the check
validates the worker's claim against the worker's own claim. On dev-flow
`run-49039bac` the worker claimed 13 files, git saw none of them, and the
gate re-ran for ~8 minutes over an unchanged tree.

This task makes git the authority: snapshot the worktree's git state before
the triage dispatch, recompute after, and use the **delta** (not an absolute
diff against the base branch — development has already committed by then)
as the return value and the evidence set.

The spec's §3 reference implementation is **normative**: write it as given,
deviating only where the Codebase Contract below proves it wrong, and record
any deviation in the Completion Note.

---

## Scope

- Add `FrozenSet` to the existing `typing` import line in `qa.py` (keep the
  alphabetical order already used there).
- Add `QANode._git_state(worktree_path) -> Tuple[str, FrozenSet[str]]`
  (`@staticmethod`, async) — returns `(HEAD sha, dirty paths)` via
  `asyncio.create_subprocess_exec`, degrading to `("", frozenset())` on any
  git failure. Body verbatim from spec §3 Module 1.
- Add `QANode._paths_touched_since(worktree_path, before) -> List[str]`
  (`@classmethod`, async) — newly-dirty paths plus every path in commits added
  between `before` and now. Body verbatim from spec §3 Module 1.
- Place both immediately after `_get_changed_files` (whose body ends with
  `return []`) and before `@staticmethod def _scope_lint_to_files`.
- In `_run_finding_triage`:
  - capture `before_state = await self._git_state(worktree_path)` immediately
    before the first `report = await _dispatch_once()`;
  - replace `files_modified_set = set(report.files_modified)` with the
    git-derived computation from spec §3 (compute `actual_modified`, log a
    `self.logger.warning` listing claimed-but-unverified paths, then
    `files_modified_set = set(actual_modified)`);
  - replace the return with `return notes, list(actual_modified), escalation_passed`.
- Update the two existing tests in `test_qa_triage.py` that rely on a claimed
  `files_modified=["a.py"]` against a non-existent worktree path (see
  Implementation Notes → Existing tests that WILL break).
- Write the new unit + integration tests listed in Test Specification.

**NOT in scope**:
- Anything in `scripts/sdd/lint_new.py` or the lint-command rewrite
  (TASK-2736, TASK-2737).
- Changing `_confirm_has_evidence`'s signature or body — it already takes the
  evidence set as a parameter; only what is passed in changes.
- Changing `TriageReport` (its `files_modified` keeps its shape; it just stops
  being the authority).
- Any new configuration knob in `parrot/conf.py` (G5).
- The call sites at `qa.py:287-296` and `qa.py:314-326` — they consume the
  returned list transparently and need no edit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | `FrozenSet` import; add `_git_state`, `_paths_touched_since`; wire into `_run_finding_triage` |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py` | MODIFY | Patch `_paths_touched_since` in the two tests that rely on claimed evidence against a fake worktree path |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_triage_evidence.py` | CREATE | Unit tests for the two helpers (real tmp git repo) + the two §4 integration tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (verified 2026-09-02 on `dev` @ `565e96561`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py — ALL already present, do NOT re-add:
import asyncio                                                # qa.py:22
import os                                                     # qa.py:23
import re                                                     # qa.py:24
import shlex                                                  # qa.py:25
from typing import Any, Dict, List, Optional, Tuple, Union    # qa.py:27  ← add FrozenSet here

# For the tests (verified in packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py:14-18):
from unittest.mock import AsyncMock, MagicMock
import pytest
from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, QAReport, ResearchOutput
from parrot.flows.dev_loop.models import AdversarialFinding, CodeReviewVerdict, TriageReport
from parrot.flows.dev_loop.nodes.qa import QANode
```

`FrozenSet` is **NOT** currently imported in `qa.py`. `Tuple` **IS** (it
types `_run_finding_triage`'s return). After the edit line 27 must read:
`from typing import Any, Dict, FrozenSet, List, Optional, Tuple, Union`.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
class QANode(DevLoopNode):
    def __init__(self, *, dispatcher, ..., lint_command: Optional[str] = None)   # line 133-137

    @staticmethod
    async def _get_changed_files(worktree_path: str) -> List[str]:   # line 681-708
        # Uses asyncio.create_subprocess_exec("git", ...) with cwd=worktree_path,
        # stdout/stderr=asyncio.subprocess.PIPE, `await proc.communicate()`,
        # returns [] on any error. COPY THIS SUBPROCESS PATTERN. Body ends `return []` at line 708.

    @staticmethod
    def _scope_lint_to_files(command: str, files: List[str]) -> str:   # line 710-730
        # The new helpers go BETWEEN line 708 and line 710.

    async def _run_finding_triage(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
        findings: List[AdversarialFinding],
    ) -> Tuple[List[str], List[str], bool]:                    # line 923-929
        worktree_path = research.worktree_path                 # line 946
        async def _dispatch_once() -> TriageReport: ...        # line 963 (inner closure)
        report = await _dispatch_once()                        # line 986 ← insert `before_state = ...` on the line BEFORE
        # retry path: `report = await _dispatch_once()` again at line 993 — leave it
        files_modified_set = set(report.files_modified)        # line 1001 ← REPLACE
        # loop over findings, line 1012:
        elif resolved.disposition == "confirm" and not self._confirm_has_evidence(resolved, files_modified_set):
        return notes, list(report.files_modified), escalation_passed   # line 1053 ← REPLACE

    @staticmethod
    def _confirm_has_evidence(resolved: AdversarialFinding, files_modified: set) -> bool:   # line 1056 — UNCHANGED

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class AdversarialFinding(CodeReviewFinding):                     # line 679
    disposition: Optional[Literal["confirm", "reject", "escalate"]] = None   # line 683
    # also: finding_id, triage_reason, file, message (inherited)

class TriageReport(BaseModel):                                   # line 719
    findings: List[AdversarialFinding]
    files_modified: List[str] = Field(default_factory=list)      # line 723 — keeps its shape

# Existing call sites that consume the return value (NO edit needed):
#   qa.py:287  triage_notes, triage_files_modified, escalation_passed = await self._run_finding_triage(...)
#   qa.py:290-292  merges triage_files_modified into files_modified
#   qa.py:301-326  `if files_modified:` → second `_run_deterministic_qa` call (the expensive re-run)
```

The `self.logger` attribute is available on `QANode` (used throughout, e.g.
`self.logger.warning(...)` at `qa.py:988`).

### Does NOT Exist
- ~~`QANode._git_changed_files`~~ — that name belongs to **`DevelopmentNode`**
  (`nodes/development.py`), not `QANode`. `QANode`'s helper is
  `_get_changed_files` and takes ONE argument. Do NOT import `DevelopmentNode`
  into `qa.py` to reuse `_reconcile_files_changed`/`_git_changed_files`: its
  semantics (absolute diff vs. base) are the WRONG semantics here — this task
  needs a delta across the dispatch.
- ~~`TriageReport.verified_files`~~ / ~~`files_verified`~~ / ~~`actual_files`~~ —
  the model has only `findings` and `files_modified`. Do not add a field.
- ~~`conf.DEV_LOOP_TRIAGE_VERIFY_GIT`~~ or any similar knob — G5: no new config.
- ~~`subprocess.run(...)` inside `qa.py`~~ — blocks the event loop; use
  `asyncio.create_subprocess_exec` exactly like `_get_changed_files`.
- ~~`git diff --name-only before..after` via `GitPython`~~ — GitPython is not a
  dependency; shell out to `git`.
- ~~`asyncio_mode = auto`~~ — the dev_loop tests decorate each coroutine test
  with `@pytest.mark.asyncio` explicitly (see `test_qa_triage.py`). Do the same.

---

## Implementation Notes

### Pattern to Follow
The spec §3 Module 1 code block is the implementation. Copy it. The subprocess
shape it uses is the one `_get_changed_files` already uses at `qa.py:689-705`.

### Existing tests that WILL break (and how to fix them)
`packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py` builds its
`ResearchOutput` with `worktree_path="/abs/.claude/worktrees/feat-130-fix"`
— a path that does not exist. After this task, `_git_state` on that path
degrades to `("", frozenset())`, so `_paths_touched_since` returns `[]`, so
a `TriageReport(files_modified=["a.py"])` claim is **dropped**. Two tests
assert on the old behaviour:

- `test_triage_confirm_triggers_rerun` (line 55) — expects 3 dispatches.
- `test_confirm_with_fix_evidence_stays_confirmed` (line 125) — expects 3
  dispatches and no escalation note.

Fix: in both, `monkeypatch.setattr(QANode, "_paths_touched_since",
AsyncMock(return_value=["a.py"]))` (a classmethod patched at class level
with an `AsyncMock` is fine — the call site is `await self._paths_touched_since(worktree_path, before_state)`;
`AsyncMock` accepts any args). Add `monkeypatch` to their signatures. Their
docstrings should say the evidence now comes from git, not the claim.
`test_confirm_without_fix_evidence_fails_closed_to_escalate` already claims
`files_modified=[]` and keeps passing unchanged. Run the whole file after
the change:
`pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py -v`.

### Testing the helpers against a real repo
Unit tests for `_git_state` / `_paths_touched_since` need a real git repo:
build one with `subprocess.run` in `tmp_path` (`git init -q`, set
`user.email`/`user.name`, write a file, `git add -A`, `git commit -qm`).
Then, between the `before` snapshot and the `after` call, mutate the repo
(edit a tracked file → dirty path; `git commit` → committed path; leave a
file dirty *before* the snapshot → must NOT appear). Pass `str(tmp_path)`
as `worktree_path`.

For the two §4 **integration** tests, reuse the `ctx`/`_advisory_reviewer`/
`_finding` fixture style from `test_qa_triage.py` but set
`worktree_path=str(tmp_path)` pointing at a real repo:
- *skips the rerun*: the fake dispatcher returns a `TriageReport` claiming
  `["a.py"]` but touches nothing → `_run_deterministic_qa` awaited exactly
  once (wrap it with `AsyncMock(wraps=...)` or count `dispatcher.dispatch`
  awaits: deterministic + triage == 2).
- *really commits*: the dispatcher's `side_effect` callable for the triage
  call performs a `git commit` in the tmp repo before returning the report →
  awaited twice (3 dispatch awaits).

### Key Constraints
- Async throughout; never `subprocess.run` inside `qa.py`.
- Degrade, never raise: every git failure resolves to "no evidence", which
  fails the gate closed rather than fabricating a pass.
- `self.logger.warning` for the unverified-claim message; never `print`.
- Google-style docstrings + strict type hints on both new helpers (the spec
  text already provides them).
- `git status --porcelain` rename lines read `R  old -> new`; keep the
  post-rename path (the spec's `split(" -> ")[-1]`).
- After the edit, `grep -n "report.files_modified" qa.py` must show ONLY the
  claim-vs-git comparison line (plus the pre-existing comment at ~line 1045,
  which should be reworded to say the fix surfaces via git-observed changes).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:681-708` — subprocess pattern to copy.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` — `_reconcile_files_changed` (the "git wins" precedent on the development side; read for posture only, do not import).
- `packages/ai-parrot/tests/flows/dev_loop/test_qa_triage.py` — fixture style for `QANode.execute` tests.
- `tests/sdd_scripts/test_check_id_collisions.py` — `tmp_path` + `subprocess` repo-fixture style.

---

## Acceptance Criteria

- [ ] `_git_state` and `_paths_touched_since` exist on `QANode` with the spec's signatures, placed between `_get_changed_files` and `_scope_lint_to_files`.
- [ ] `_run_finding_triage` returns the git-derived list; `grep -n "report.files_modified" packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` shows only the claim-vs-git comparison.
- [ ] A claimed-but-unverified path produces a `WARNING` log line and is dropped.
- [ ] A non-git `worktree_path` yields `[]` with no exception.
- [ ] `TriageReport`, `QAReport`, and every node signature are unchanged.
- [ ] No new entry in `packages/ai-parrot/src/parrot/conf.py`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop -v` (includes the updated `test_qa_triage.py` and the new `test_qa_triage_evidence.py`).
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` introduces no new findings relative to the parent commit.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_qa_triage_evidence.py
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, QAReport, ResearchOutput
from parrot.flows.dev_loop.models import AdversarialFinding, CodeReviewVerdict, TriageReport
from parrot.flows.dev_loop.nodes.qa import QANode


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "dev")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "baseline")
    return tmp_path


# ---- unit: the helpers -------------------------------------------------

@pytest.mark.asyncio
async def test_git_failure_degrades_to_no_evidence(tmp_path):
    """Non-git worktree_path → [] and no exception."""
    before = await QANode._git_state(str(tmp_path / "nope"))
    assert before == ("", frozenset())
    assert await QANode._paths_touched_since(str(tmp_path / "nope"), before) == []


@pytest.mark.asyncio
async def test_uncommitted_edit_during_triage_counts_as_evidence(repo):
    before = await QANode._git_state(str(repo))
    (repo / "a.py").write_text("x = 2\n")
    assert await QANode._paths_touched_since(str(repo), before) == ["a.py"]


@pytest.mark.asyncio
async def test_git_visible_changes_are_reported_even_if_unclaimed(repo):
    """A commit added during the dispatch is evidence, claim or no claim."""
    before = await QANode._git_state(str(repo))
    (repo / "b.py").write_text("y = 1\n")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "triage fix")
    assert await QANode._paths_touched_since(str(repo), before) == ["b.py"]


@pytest.mark.asyncio
async def test_pre_existing_dirty_file_is_not_evidence(repo):
    (repo / "a.py").write_text("x = 2\n")          # dirty BEFORE the snapshot
    before = await QANode._git_state(str(repo))
    assert await QANode._paths_touched_since(str(repo), before) == []


# ---- integration: QANode.execute ---------------------------------------
# Build `ctx` like test_qa_triage.py but with worktree_path=str(repo).

@pytest.mark.asyncio
async def test_claimed_but_invisible_files_are_dropped(repo, caplog, ...):
    """Worker claims 13 paths, git shows none → files_modified [] + WARNING logged."""
    ...

@pytest.mark.asyncio
async def test_confirm_without_git_evidence_escalates(repo, ...):
    """CONFIRM naming a file git never saw → note contains 'Escalated for human review'."""
    ...

@pytest.mark.asyncio
async def test_triage_claim_without_git_evidence_skips_the_qa_rerun(repo, ...):
    """Triage claims files it never wrote → dispatch awaited 2x (deterministic + triage), not 3x."""
    ...

@pytest.mark.asyncio
async def test_triage_that_really_commits_triggers_the_rerun(repo, ...):
    """The fake dispatcher's triage side-effect commits a file → dispatch awaited 3x."""
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context — §3 Module 1 is the implementation.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/qa-gate-evidence-and-diff-scoped-lint.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2735-git-verified-triage-evidence.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-09-02
**Notes**: Implemented `_git_state` and `_paths_touched_since` verbatim from
spec §3 Module 1, added `FrozenSet` to the `typing` import, and wired the
git-derived evidence into `_run_finding_triage` (before-snapshot, unverified
warning, `files_modified_set`/return value). Updated the two existing
`test_qa_triage.py` tests that relied on a claimed-but-unverifiable evidence
path (monkeypatched `_paths_touched_since`). Also had to make the same fix
to `test_adversarial_e2e.py::test_e2e_adversarial_review_triage` — not
listed in this task's Files to Modify table, but it uses the same
`worktree_path=str(tmp_path)` (non-repo) pattern and broke for the identical
reason; the task's own AC requires the whole `tests/flows/dev_loop` suite to
pass, so it had to be fixed here. Added
`test_qa_triage_evidence.py` with the unit tests for both helpers plus the
two §4 integration tests. Full `pytest packages/ai-parrot/tests/flows/dev_loop -v`
run: 1468 passed, 3 pre-existing failures in `test_recovery_lifecycle.py`
confirmed unrelated (same failures reproduce on a stash of this task's diff).

**Deviations from spec**: none in the implementation itself. One AC —
"ruff check on the two touched files reports no new findings relative to
the parent commit" — could not be fully verified inside this task because
`scripts/sdd/lint_new.py` (its own verification tool) is TASK-2736's
deliverable. Manual inspection: our one-line edit to the `typing` import
(adding `FrozenSet`) causes ruff's `UP035` findings for the *pre-existing*
`Dict`/`List`/`Tuple` names on that same line to also intersect a
git-changed line, since diff-line attribution operates on whole line
numbers, not sub-line spans. This is an inherent, spec-acknowledged
trade-off of diff-line attribution vs. baseline-subtraction (§2, Open
Questions) — not a defect introduced here. Re-verified after TASK-2736/2737
landed; see FEAT-497 feature-level completion summary for the final,
whole-diff `lint_new.py` result.
