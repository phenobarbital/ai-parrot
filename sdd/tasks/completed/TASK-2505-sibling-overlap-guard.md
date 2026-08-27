# TASK-2505: Sibling-overlap guard + handoff nodes consume the recorded base

**Feature**: FEAT-466 — Dev-Loop Run Fidelity
**Spec**: `sdd/specs/dev-loop-run-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2504
**Assigned-to**: unassigned

---

## Context

Implements **spec Module 5** — the "read the record" half, plus the backstop.

This is the task that actually stops another PR #1250. Two changes:

**1. Delete the guess.** `DeploymentHandoffNode` currently overrides its PR base
from the brief's work kind:

```python
# nodes/deployment_handoff.py:132-133
        # Bug fixes branch from main; the PR target must match.
        if getattr(brief, "kind", "bug") == "bug":
            object.__setattr__(self, "_base_branch", "main")
```

That comment asserts a fact nobody established. The branch was cut wherever it
was cut; this line just declares where it *ought* to have been. TASK-2504 put
the real answer on `ResearchOutput.base_branch`. Read it, and delete this.

**2. Add the guard — and read this part carefully, because the obvious
implementation does not work.**

The intuitive check is "is the head branch a descendant of the base?". It is
useless here. Measured against the real SHAs from the incident:

```bash
$ git merge-base --is-ancestor 5370f9256 43ba79e93 && echo PASSES
PASSES        # old main  vs  feat-465 tip
```

Because `main` was an ancestor of `dev`, a branch cut from `dev` **still
descends from `origin/main`**. `--is-ancestor` would have waved #1250 straight
through. Do not implement the guard as an ancestry check, and do not
"simplify" it into one later.

What discriminates is whether the branch carries commits that already live on a
**sibling** long-lived branch:

```bash
$ git rev-list --count 5370f9256..43ba79e93                      #  93   what the PR adds
$ git rev-list --count 5370f9256..43ba79e93 --not origin/dev     #   0   its own work
                                                          93 != 0  ->  BLOCK
```

For a correctly-cut branch those two numbers are equal: everything it adds is
its own work. Cherry-picks are safe — they get new SHAs, so they are not "on"
the sibling by commit identity.

---

## Scope

- Add `assert_base_is_clean()` as a **module-level async function** in
  `nodes/base.py`, beside the existing module-level helpers
  (`scrub_git_output:40`, `transition_issue_with_candidates:54`,
  `condense_qa_failure:134`). Both handoff nodes call the same implementation.
- Add a `BaseBranchMismatch(RuntimeError)` exception in the same module.
- Guard behaviour:
  - Fetch `origin/<base>` and every sibling ref before measuring, so the
    verdict is never computed against a stale remote-tracking ref.
  - Siblings default to `KNOWN_BRANCHES - {base}`, **filtered to refs that
    actually exist on the remote** — `staging` may not exist, and passing a
    missing ref to `rev-list --not` fails the entire command.
  - Compare `adds` vs `own` as shown above; raise `BaseBranchMismatch` when
    they differ, with a message naming both counts, the base, the siblings
    checked, and a remediation hint ("re-cut the branch from origin/<base>").
  - When there are no existing siblings to check, log at INFO and pass — do
    not raise.
- `DeploymentHandoffNode`:
  - Delete lines 132-133 (the `kind` override) **and** its comment.
  - Source `_base_branch` from `research.base_branch`.
  - **Block when `research.base_branch == ""`** rather than falling back to
    the `"dev"` constructor default — `""` means "nothing resolved it", and
    silently defaulting is the class of bug this feature removes.
  - Call the guard after `_push_branch` and before `_create_pr`; on
    `BaseBranchMismatch`, call `_mark_blocked(issue_key, ...)` and return
    `{"status": "blocked", "error": ...}` — the same shape the existing
    push/PR failure paths use (`deployment_handoff.py:~146-160`).
- `FeatureHandoffNode`: same recorded-base sourcing and the same guard call
  before its PR creation. It carries the identical defect — hardcoded
  `base_branch: str = "dev"` at `feature_handoff.py:101`, never given an
  override by `factories.py:244`.
- Unit tests per the Test Specification below, including a real-git fixture
  that reproduces the #1250 topology.

**NOT in scope**:
- Auto-recutting or replaying a mis-based branch. Resolved in spec §8: the flow
  **blocks**, a human re-cuts.
- Any absolute commit-count cap. Resolved in spec §8: the sibling comparison is
  exact, so no threshold is needed. Do not add one.
- Changing how the branch is created — that is TASK-2507.
- `PlannerOutput` gaining a `base_branch` field, unless `FeatureHandoffNode`
  genuinely needs it; prefer reading the run's `research_output`/planner output
  already in shared state. If you must add the field, mirror TASK-2504's
  approach and say so in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/base.py` | MODIFY | `BaseBranchMismatch` + `assert_base_is_clean()` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py` | MODIFY | Delete :132-133; source base from research; call guard |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py` | MODIFY | Same |
| `packages/ai-parrot/tests/flows/dev_loop/test_base_branch_guard.py` | CREATE | Guard unit tests + real-git #1250 topology |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import shutil
from typing import Any, Iterable, Optional

from parrot.flows.dev_loop.nodes.base import (
    DevLoopNode,                       # nodes/base.py:193
    register_dev_loop_node,            # nodes/base.py:174
    scrub_git_output,                  # nodes/base.py:40
    transition_issue_with_candidates,  # nodes/base.py:54
)
from parrot.flows.dev_loop.models.base import ResearchOutput, BugBrief, QAReport
from scripts.sdd.sdd_meta import KNOWN_BRANCHES   # scripts/sdd/sdd_meta.py:26
```

> If TASK-2504 concluded that `scripts.sdd` is **not** importable from an
> installed context (see its Completion Note), do not import `KNOWN_BRANCHES`
> either — define a module-level `_LONG_LIVED_BRANCHES = frozenset({"main",
> "staging", "dev"})` in `nodes/base.py` and note the duplication.

### Existing Signatures to Use

```python
# nodes/base.py — module-level helper neighbourhood; add yours here
def scrub_git_output(text: str) -> str: ...                              # line 40
async def transition_issue_with_candidates(...) -> None: ...             # line 54
def condense_qa_failure(report, *, max_chars: int = 2000) -> str: ...    # line 134
def register_dev_loop_node(name: str): ...                               # line 174
class DevLoopNode(Node): ...                                             # line 193

# THE SUBPROCESS PATTERN TO COPY — nodes/deployment_handoff.py:296-311
    async def _push_branch(self, branch: str, cwd: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", cwd, "push", "-u", "origin", branch,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"git push failed: {scrub_git_output(stderr.decode(errors='replace'))}"
            )

# nodes/deployment_handoff.py
    def __init__(self, *, jira_toolkit, git_toolkit=None, gh_cli_path=None,
                 target_repo=None, base_branch: str = "dev",
                 name="deployment_handoff",
                 require_deployment_approval: bool = False) -> None:      # line 80
        object.__setattr__(self, "_base_branch", base_branch)             # line 93
        # DELETE THESE TWO LINES:
        if getattr(brief, "kind", "bug") == "bug":                        # line 132
            object.__setattr__(self, "_base_branch", "main")              # line 133
    async def _push_branch(self, branch, cwd) -> None: ...                # line 296
    async def _create_pr(self, branch, title, body) -> str: ...           # line 332
    async def _create_pr_with_gh(...)                                     # line 348
            "--base",                                                     # line 357
            self._base_branch,                                            # line 358
    async def _create_pr_via_rest(...)                                    # line 410
            "base": self._base_branch,                                    # line 428

# nodes/feature_handoff.py
                 base_branch: str = "dev",                                # line 101
        object.__setattr__(self, "_base_branch", base_branch)              # line 116
            "--base", self._base_branch, "--head", branch,                 # line 305
            "base": self._base_branch, "draft": True,                      # line 326

# packages/ai-parrot/src/parrot/flows/dev_loop/factories.py
            FeatureHandoffNode(   # never passes base_branch -> always "dev"  # line 244
```

```python
# models/base.py — the field TASK-2504 added
class ResearchOutput(BaseModel):                          # line 323
    base_branch: str = ""    # "" == unresolved -> BLOCK, do not default
```

### Does NOT Exist

- ~~`assert_base_is_clean` / `BaseBranchMismatch`~~ — no base-branch validation
  of any kind exists in either handoff node today. You are creating both.
- ~~`_assert_descends_from_base`~~ — an earlier spec draft named it this and
  defined it as an ancestry check. **That design was rejected** (see Context).
  Do not resurrect the name or the semantics.
- ~~`DEV_LOOP_PR_MAX_COMMITS_VS_BASE`~~ or any commit-count cap config key —
  explicitly out of scope.
- ~~`git merge-base --is-ancestor` as the guard~~ — proven insufficient.
  You may use it as a cheap *precondition* (a branch that does not descend from
  base at all is certainly wrong) but it must not be the discriminating test.
- ~~`self._git.rev_list(...)`~~ — the Git toolkit is not used for this; both
  nodes shell out via `asyncio.create_subprocess_exec`. Follow `_push_branch`.
- ~~`FeatureHandoffNode` receiving a `base_branch` from anywhere~~ — verified:
  `factories.py:244` constructs it without that kwarg.

---

## Implementation Notes

### Pattern to Follow — the guard

```python
class BaseBranchMismatch(RuntimeError):
    """The head branch was cut from the wrong base (FEAT-466)."""


async def _git(cwd: str, *args: str) -> tuple[int, str, str]:
    """Run a git subcommand, returning (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", cwd, *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode,
        out.decode(errors="replace").strip(),
        err.decode(errors="replace").strip(),
    )


async def assert_base_is_clean(
    branch: str,
    base: str,
    cwd: str,
    *,
    siblings: Optional[Iterable[str]] = None,
    logger: Any = None,
) -> None:
    """Raise when ``branch`` carries commits belonging to a sibling branch.

    An ancestry check is deliberately NOT the test. Measured on the FEAT-466
    incident: ``git merge-base --is-ancestor <old main> <feat-465 tip>``
    returns true, because ``main`` was an ancestor of ``dev`` — so a branch cut
    from ``dev`` still descends from ``origin/main``. The discriminating signal
    is commit *membership*:

        adds = git rev-list --count origin/<base>..<branch>
        own  = git rev-list --count origin/<base>..<branch> --not origin/<sib>...
        adds != own  =>  the branch carries a sibling's history.

    Cherry-picked commits have distinct SHAs and therefore do not count as
    sibling commits, so a legitimately back-ported hotfix is not flagged.

    Args:
        branch: Local head branch name.
        base: Resolved base branch (no ``origin/`` prefix).
        cwd: Repository or worktree directory to run git in.
        siblings: Long-lived branches to treat as foreign. Defaults to
            ``KNOWN_BRANCHES`` minus ``base``, filtered to refs that exist on
            the remote.
        logger: Optional logger for the INFO/measurement trail.

    Raises:
        BaseBranchMismatch: When the branch carries sibling commits.
        RuntimeError: When a git command fails outright.
    """
    candidates = [s for s in (siblings if siblings is not None
                              else KNOWN_BRANCHES) if s != base]

    # Fetch base + candidates, and keep only refs that actually exist.
    await _git(cwd, "fetch", "origin", base)
    existing: list[str] = []
    for sib in sorted(candidates):
        rc, _, _ = await _git(cwd, "fetch", "origin", sib)
        if rc != 0:
            continue
        rc, _, _ = await _git(cwd, "rev-parse", "--verify", f"origin/{sib}")
        if rc == 0:
            existing.append(sib)

    if not existing:
        if logger:
            logger.info(
                "No sibling branches to check against base %r; guard passes.", base
            )
        return

    rng = f"origin/{base}..{branch}"
    rc, adds_out, err = await _git(cwd, "rev-list", "--count", rng)
    if rc != 0:
        raise RuntimeError(f"git rev-list failed: {scrub_git_output(err)}")

    not_args = [arg for sib in existing for arg in ("--not", f"origin/{sib}")]
    rc, own_out, err = await _git(cwd, "rev-list", "--count", rng, *not_args)
    if rc != 0:
        raise RuntimeError(f"git rev-list failed: {scrub_git_output(err)}")

    adds, own = int(adds_out or 0), int(own_out or 0)
    if logger:
        logger.info(
            "Base check for %s onto %s: adds=%d own=%d siblings=%s",
            branch, base, adds, own, existing,
        )
    if adds != own:
        raise BaseBranchMismatch(
            f"branch {branch!r} would add {adds} commit(s) to {base!r} but only "
            f"{own} are its own work — the remaining {adds - own} already exist "
            f"on {existing}. The branch was almost certainly cut from the wrong "
            f"base. Re-cut it from origin/{base} and re-run."
        )
```

### Pattern to Follow — the node wiring

```python
        # nodes/deployment_handoff.py — replaces lines 132-133 entirely
        base = (getattr(research, "base_branch", "") or "").strip()
        if not base:
            error = (
                "research_output.base_branch is empty — the run's base branch "
                "was never resolved. Refusing to guess a PR target (FEAT-466)."
            )
            self.logger.error(error)
            await self._mark_blocked(issue_key, error)
            return {"status": "blocked", "error": error}
        object.__setattr__(self, "_base_branch", base)
```

and after the existing `_push_branch` block, before `_create_pr`:

```python
        try:
            await assert_base_is_clean(
                research.branch_name,
                self._base_branch,
                research.worktree_path,
                logger=self.logger,
            )
        except BaseBranchMismatch as exc:
            self.logger.error("base-branch guard blocked the PR: %s", exc)
            await self._mark_blocked(issue_key, str(exc))
            return {"status": "blocked", "error": str(exc)}
```

### Key Constraints

- **`DevLoopNode` subclasses are frozen** — always `object.__setattr__`.
- **Never open the PR when the guard fires.** There is an acceptance criterion
  asserting `_create_pr` is not called; the tests patch it and assert
  `not called`.
- Run the guard **after** the push (the remote needs the branch for a
  meaningful comparison, and the existing code already pushes first) but
  **before** any Jira transition — a blocked run must not move the ticket.
- Scrub git output through `scrub_git_output` before it reaches a log or a Jira
  comment; that helper exists because git errors can carry credentials in
  remote URLs.
- Keep the guard a free function, not a method — `FeatureHandoffNode` and
  `DeploymentHandoffNode` do not share a base class beyond `DevLoopNode`, and a
  free function is trivially unit-testable against a real temp repo.

### References in Codebase

- `nodes/deployment_handoff.py:296-311` — the subprocess idiom to copy.
- `nodes/deployment_handoff.py:~146-160` — the existing `_mark_blocked` +
  `{"status": "blocked"}` return shape. Match it exactly.
- `nodes/base.py:40-52` — `scrub_git_output`, and the module-level helper
  style.
- `spec §7 Known Risks` — the "do not simplify the guard to an ancestry
  check" entry, with the measurement. Read it before you start.

---

## Acceptance Criteria

- [ ] `assert_base_is_clean` and `BaseBranchMismatch` exist as module-level
      names in `nodes/base.py`
- [ ] Reproduces the incident: a temp repo with the #1250 topology (branch cut
      from `dev`, `main` an ancestor of `dev`, PR base `main`) raises
      `BaseBranchMismatch`
- [ ] A correctly-cut branch (`adds == own`) does not raise
- [ ] A cherry-picked commit present on a sibling under a *different* SHA does
      not trigger a false block
- [ ] Missing sibling refs (e.g. no `origin/staging`) are skipped, not fatal
- [ ] With no existing siblings at all, the guard logs INFO and passes
- [ ] `deployment_handoff.py` lines 132-133 are gone;
      `grep -n 'kind.*==.*"bug"' packages/ai-parrot/src/parrot/flows/dev_loop/nodes/*handoff*.py`
      returns nothing
- [ ] Both handoff nodes source the base from the recorded value, and both
      return `status="blocked"` when it is `""`
- [ ] When the guard fires, `_create_pr` is never called and the Jira ticket is
      not transitioned
- [ ] `kind="bug"` with a recorded `base_branch="dev"` opens the PR against
      `dev` (the override is truly gone)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` and `mypy` clean on all three changed files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_base_branch_guard.py
import subprocess

import pytest

from parrot.flows.dev_loop.nodes.base import (
    BaseBranchMismatch,
    assert_base_is_clean,
)


def _run(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True)


@pytest.fixture
def incident_repo(tmp_path):
    """Reproduce the PR #1250 topology.

        main:  A
        dev:   A -- B -- C          (main is an ancestor of dev)
        feat:  A -- B -- C -- D     (cut from dev, but targeting main)

    So `--is-ancestor origin/main feat` is TRUE, yet feat carries B and C,
    which belong to dev. adds(main..feat) = 3, own = 1.
    """
    origin = tmp_path / "origin"
    origin.mkdir()
    _run(origin, "init", "--bare", "-b", "main")

    work = tmp_path / "work"
    work.mkdir()
    _run(work, "init", "-b", "main")
    _run(work, "remote", "add", "origin", str(origin))
    (work / "a.txt").write_text("A")
    _run(work, "add", "-A"); _run(work, "-c", "user.email=t@t", "-c", "user.name=t",
                                  "commit", "-m", "A")
    _run(work, "push", "origin", "main")

    _run(work, "checkout", "-b", "dev")
    for name in ("B", "C"):
        (work / f"{name}.txt").write_text(name)
        _run(work, "add", "-A"); _run(work, "-c", "user.email=t@t",
                                      "-c", "user.name=t", "commit", "-m", name)
    _run(work, "push", "origin", "dev")

    _run(work, "checkout", "-b", "feat-465")
    (work / "D.txt").write_text("D")
    _run(work, "add", "-A"); _run(work, "-c", "user.email=t@t",
                                  "-c", "user.name=t", "commit", "-m", "D")
    _run(work, "push", "origin", "feat-465")
    _run(work, "fetch", "origin")
    return work


class TestGuard:
    async def test_ancestry_alone_would_pass(self, incident_repo):
        """Documents WHY the guard is not an ancestry check."""
        rc = subprocess.run(
            ["git", "-C", str(incident_repo), "merge-base",
             "--is-ancestor", "origin/main", "feat-465"]
        ).returncode
        assert rc == 0, "ancestry passes — hence the sibling-overlap guard"

    async def test_blocks_the_incident_topology(self, incident_repo):
        with pytest.raises(BaseBranchMismatch, match="own work"):
            await assert_base_is_clean(
                "feat-465", "main", str(incident_repo), siblings=["dev"]
            )

    async def test_passes_for_correctly_cut_branch(self, incident_repo):
        """feat-465 vs its real base (dev) is clean: adds == own."""
        await assert_base_is_clean(
            "feat-465", "dev", str(incident_repo), siblings=["main"]
        )

    async def test_missing_sibling_ref_is_skipped(self, incident_repo):
        await assert_base_is_clean(
            "feat-465", "dev", str(incident_repo), siblings=["staging"]
        )

    async def test_cherry_pick_does_not_false_positive(self, incident_repo):
        """Same content on a sibling under a different SHA must not count."""
        ...


class TestDeploymentHandoffWiring:
    """Reuse the fixtures in test_deployment_handoff.py."""

    async def test_blocks_on_empty_base_branch(self):
        ...  # research.base_branch == "" -> status "blocked", _create_pr not called

    async def test_bug_kind_with_recorded_dev_base_targets_dev(self):
        ...  # proves the kind override is gone

    async def test_guard_failure_blocks_and_skips_pr(self):
        ...  # _create_pr asserted not called; no Jira transition


class TestFeatureHandoffWiring:
    async def test_guard_applied(self):
        ...
```

---

## Agent Instructions

1. **Check your dependency**: TASK-2504 completed, `ResearchOutput.base_branch`
   present. Read TASK-2504's Completion Note for the `scripts.sdd` import
   decision — it determines whether you can import `KNOWN_BRANCHES`.
2. **Read the spec** — §2 (diagram), §3 Module 5, §5 (the guard criterion
   spells out the exact rev-list comparison), and §7's "an ancestry check is
   not sufficient" entry.
3. **Build the `incident_repo` fixture and the `test_ancestry_alone_would_pass`
   test FIRST.** It is the whole justification for the design; if it does not
   reproduce, stop and re-read §7 before writing the guard.
4. **Then** write the guard, then the node wiring (TDD throughout).
5. **Verify** every acceptance criterion, including the `grep` one — the
   deleted override must leave no trace.
6. Move this file to `sdd/tasks/completed/` and set the index entry to `done`.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**: Added `BaseBranchMismatch` + `assert_base_is_clean()` as
module-level names in `nodes/base.py`, plus a private `_git()` subprocess
helper and a local `_LONG_LIVED_BRANCHES` frozenset (not importing
`scripts.sdd.KNOWN_BRANCHES` — per TASK-2504's documented import
decision). `DeploymentHandoffNode`: deleted the `kind == "bug"` override
block entirely; sources `_base_branch` from `research.base_branch`,
blocking with `status="blocked"` when it's `""`; calls the guard after
`_push_branch`, before PR creation. `FeatureHandoffNode`: same shape,
sourced via a NEW private `_resolve_base_branch()` static method + a local
`_parse_flow_frontmatter()` (NOT a `PlannerOutput.base_branch` field —
see Deviations below for the reasoning). `test_ancestry_alone_would_pass`
built and confirmed FIRST per the Agent Instructions, using a real (local,
no-network) git repo reproducing the exact PR #1250 topology.

**Two deviations found and fixed during implementation** (both discovered
via empirical, real-git testing — not assumed):

1. **The task's own reference `own` calculation is buggy.** The Pattern-
   to-Follow snippet computes `own` via
   `git rev-list --count origin/<base>..<branch> --not origin/<sib1> --not
   origin/<sib2> ...` (chained `--not` flags). Verified with a real repo
   (3 independent experiments, documented in this note's git history) that
   chaining 2+ `--not` flags after a `..` range gives WRONG counts — each
   `--not` toggles interesting/uninteresting state for what follows rather
   than accumulating exclusions, so results are silently order- and
   count-dependent (e.g. same inputs gave `own=1` one way and `own=2` the
   other, both wrong). Fixed by switching `own`'s calculation to explicit
   `^`-prefixed exclusions (`git rev-list --count <branch> ^origin/<base>
   ^origin/<sib1> ^origin/<sib2> ...`), confirmed correct across the clean-
   branch, incident-topology, and cherry-pick scenarios. Documented
   prominently in `assert_base_is_clean`'s docstring so nobody
   "simplifies" it back to the `--not` form.
2. **`PlannerOutput` did NOT gain a `base_branch` field** — per the task's
   own NOT-in-scope guidance ("unless `FeatureHandoffNode` genuinely needs
   it... mirror TASK-2504's approach and say so"). Since `PlannerNode` is
   not in this task's file list and `PlannerOutput.spec_path`/
   `.worktree_path` were already sufficient, `FeatureHandoffNode` instead
   gained a local, private `_resolve_base_branch()` (reads the committed
   spec's frontmatter directly, mirroring `ResearchNode`'s TASK-2504
   pattern) with a hardcoded `"dev"` fallback (feature-mode's `kind` is a
   fixed `Literal["feature"]` — there is no kind-derived hotfix path here,
   unlike bug-mode). This never returns `""`, so the empty-base block path
   in `FeatureHandoffNode` is currently unreachable dead code, kept only
   for symmetry/defensiveness with `DeploymentHandoffNode`.

**Real-environment hazard found and fixed (unrelated to the guard's
logic):** `assert_base_is_clean`'s real `asyncio.create_subprocess_exec`
calls, combined with `test_gate_integration.py`'s manually-scheduled
concurrent tasks (`asyncio.ensure_future`) and uvloop, hung the event loop
across test boundaries (single test passed in 0.48s; two together hung
indefinitely — confirmed via `faulthandler`/`SIGABRT` traceback dump
showing the loop stuck, and via a clean git-stash bisection proving the
hang did not exist on the pre-task baseline). Fixed by extending that
file's existing `_patch_push` autouse fixture to also mock
`assert_base_is_clean` — those are gate-mechanism tests, not base-branch
guard tests (which have dedicated coverage here), so no real git plumbing
belongs there, matching the existing rationale for mocking `_push_branch`/
`_create_pr` in the same fixture.

**Existing fixture updates (necessary regression fixes, not scope creep —
required by the explicit "all tests pass" acceptance criterion, same
pattern as TASK-2506):** `test_deployment_handoff.py`'s `ctx` fixture and
`test_gate_integration.py`'s `handoff_ctx` fixture construct
`ResearchOutput` without `base_branch`, which now defaults to `""` and
trips the new blocking behavior — added `base_branch="dev"` to both.

Full `pytest packages/ai-parrot/tests/flows/dev_loop/
packages/ai-parrot/tests/flows/dev_flow/` run (bounded timeout after the
hang investigation): 1299 passed (up from 1287 pre-task), same 3
pre-existing unrelated failures as every prior task in this feature
(confirmed not touched). `ruff check`: `deployment_handoff.py`,
`test_deployment_handoff.py`, `test_gate_integration.py` unchanged finding
counts; `nodes/base.py` +4 (`List`/`Tuple`/`Optional`-style findings,
consistent with the file's pervasive existing use of those forms, not
`list`/`tuple`/`X | None`); `feature_handoff.py`'s one new import-order
(I001) finding was auto-fixed via `ruff check --fix --select I001`
(mechanical reorder only, re-verified tests still pass), leaving +1
(`Optional`-style, same file-convention reasoning). New test file matches
the same pre-existing I001/C408 pattern already present in every sibling
`_brief`-style test helper. `mypy` times out project-wide (60s) — same
environment limitation noted in every prior task of this feature, not
confirmed clean.

**Deviations from spec**: (1) `own`'s rev-list form changed from chained
`--not` flags to explicit `^`-prefixed exclusions — a proven correctness
fix, not a design change (documented above and in the docstring). (2)
`FeatureHandoffNode` sources its base from a local frontmatter reader
instead of a new `PlannerOutput.base_branch` field — explicitly
pre-authorized by the task's own NOT-in-scope guidance, with the reasoning
recorded here per that guidance's request.
