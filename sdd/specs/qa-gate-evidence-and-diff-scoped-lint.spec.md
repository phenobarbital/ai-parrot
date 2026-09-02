---
type: feature
base_branch: dev
---

# Feature Specification: QA Gate — Verified Triage Evidence & Diff-Scoped Lint

**Feature ID**: FEAT-497
**Date**: 2026-09-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.28.0

> **Authoring note (deliberate deviation from `/sdd-spec` guardrails)**: this
> spec DOES carry implementation code, by explicit request. §3 gives a
> near-final reference implementation per module so the `sdd-worker` writes
> code instead of designing it. The reference implementations are
> **normative**: deviate only where the Codebase Contract in §6 proves them
> wrong, and say so in the task's completion note.

---

## 1. Motivation & Business Requirements

### Problem Statement

Observed on dev-flow `run-49039bac` (FEAT-494 — a 5-line addition to a model
catalog list). QA consumed ~22 minutes of a ~26-minute run and still failed.
Two independent defects in `QANode` account for it:

**A. The QA gate trusts the triage worker's self-report about which files it
modified.** `_run_finding_triage` returns `list(report.files_modified)`
(`qa.py:1053`) — a field the LLM fills in, never checked against git. That
value drives two decisions:

1. It triggers a **full re-run of the deterministic gate**
   (`qa.py:314-326`), which on that run cost ~8 minutes.
2. It is the *only* evidence `_confirm_has_evidence` (`qa.py:1056`) accepts
   for a CONFIRM disposition — so the "a CONFIRM must be backed by a real
   file change" check validates the worker's claim against the worker's own
   claim. The loop is closed; nothing external ever enters it.

On `run-49039bac` the worker reported 13 modified files (`nodes/qa.py`,
`nodes/development.py`, `conf.py`, `code_review.py`, `models/gemini.py`,
`.claude/agents/sdd-worker.md`, …). `git diff origin/dev...HEAD` in the
feature worktree shows **7 files, none of them those**. The gate re-ran in
full over a tree that had not changed.

Note the asymmetry this creates inside one node's blast radius:
`DevelopmentNode` already reconciles its agent's `files_changed` against git
(`development.py:_reconcile_files_changed`) precisely because coding agents
misreport — and that reconciliation is visible working in the same run's log.
The triage path never got the same treatment.

**B. Lint is scoped to changed *files*, so a touched file's pre-existing debt
becomes the feature's blocker.** `_scope_lint_to_files` (`qa.py:711`)
rewrites `ruff check .` into `ruff check <changed files>`, which correctly
stops unrelated modules from failing the gate — but still lints each changed
file *in full*. FEAT-494 added 5 lines to `catalog.py` and inherited that
file's 28 pre-existing `UP`-series findings plus an `I001`. The gate went
red, and the feedback router's retry brief instructed the worker to modernise
type annotations across a file the feature barely touched: work outside the
acceptance criteria, expanding the diff and the review surface.

### Goals

- G1 — The deterministic-QA re-run after triage fires only when the worktree
  **actually** changed, as determined by git, never by an agent's claim.
- G2 — A CONFIRM disposition is validated against git-observed changes, so
  `_confirm_has_evidence` stops being self-referential.
- G3 — The lint gate reports only findings the branch **introduced**;
  pre-existing findings in a touched file never fail a feature.
- G4 — A newly introduced finding still fails the gate, including the
  file-level kind (`I001` import sorting) whose reported line may itself be
  unchanged.
- G5 — No new configuration knob. Both behaviours are unconditional.

### Non-Goals (explicitly out of scope)

- The `feedback_router → development` retry no-op. Fixed separately as a
  hotfix on `dev` (`843fa0095`); this spec assumes it landed.
- Making `mypy` diff-aware. Only the `ruff` half of the lint command gains
  baseline awareness; the `mypy` half keeps today's file-scoped behaviour.
- Reducing the ideation/planner node runtimes (~7 min each on the same run).
  Real, but a separate concern with a separate cause.
- Retro-fixing `catalog.py`'s pre-existing `UP`/`I001` debt. Out of scope by
  construction — this feature exists so that debt stops blocking others.

---

## 2. Architectural Design

### Overview

Two independent, additive changes inside the QA gate. Neither adds a
configuration flag, a model, or a node.

**Change 1 — git-verified triage evidence.** `QANode._run_finding_triage`
snapshots the worktree's git state *before* dispatching the triage worker and
recomputes it *after*. The set of paths that actually changed between the two
snapshots replaces `report.files_modified` wholesale as the return value and
as the evidence set handed to `_confirm_has_evidence`. Claimed-but-invisible
paths are logged as a warning and dropped; git-visible-but-unclaimed paths
are kept (the same union-with-git posture `_reconcile_files_changed` already
takes on the development side).

The snapshot is a *delta*, not an absolute diff against the base branch:
by the time triage runs, `DevelopmentNode` has already committed the
feature's work, so an absolute `git diff origin/dev...HEAD` would "verify"
any claim naming a file development touched. Only the change **during the
triage dispatch** is evidence that triage did something.

**Change 2 — diff-scoped ruff.** A new repo script,
`scripts/sdd/lint_new.py`, runs `ruff check --output-format json` over the
changed files and keeps only findings whose reported source range intersects
a line the branch added or modified. `QANode` swaps the `ruff check …`
sub-command of its lint command for an invocation of that script; the rest of
the command (`mypy …`) is untouched and still goes through
`_scope_lint_to_files`.

Range intersection — not "the finding's first line is a changed line" — is
what satisfies G4: `I001` is reported at the top of the import block with an
`end_location` covering the whole block, so an import added five lines down
still intersects.

A baseline strategy (lint the merge-base version of each file and subtract
the findings) was rejected: it needs the ruff configuration to resolve
identically for files materialised outside their real path, which
`per-file-ignores` makes unreliable, and it doubles the lint runtime.

### Component Diagram

```
QANode.execute
  ├─ _run_code_review ──────────────► (advisory reviewer, read-only)
  │
  ├─ _run_finding_triage ───────────► sdd-worker (write-enabled)
  │     │  before = _git_state(worktree)          ◄── NEW
  │     │  …dispatch (+1 retry)…
  │     │  actual = _paths_touched_since(before)  ◄── NEW
  │     └─ returns (notes, actual, escalation_passed)   [was: report.files_modified]
  │
  └─ _run_deterministic_qa
        │  changed  = _get_changed_files(cwd)
        │  lint_cmd = _baseline_aware_lint(...)   ◄── NEW: ruff -> lint_new.py
        │  lint_cmd = _scope_lint_to_files(...)       (mypy half, unchanged)
        └─ dispatch sdd-qa ──► runs `python -m scripts.sdd.lint_new <files> && mypy <files>`
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `QANode._run_finding_triage` | modifies | Return value becomes git-derived; `files_modified_set` too |
| `QANode._confirm_has_evidence` | unchanged signature | Receives the git-derived set instead of the claimed one |
| `QANode._run_deterministic_qa` | modifies | One extra call in the lint-command build (`qa.py:461`) |
| `QANode._scope_lint_to_files` | unchanged | Still handles the `mypy` half |
| `scripts/sdd/` | new module | Joins `reserve_ids.py`, `check_id_collisions.py` as a `python -m`-invoked repo script |
| `sdd-qa` subagent | unchanged | Runs whatever `lint_command` string it is given |

### Data Models

No new Pydantic models. `TriageReport.files_modified` keeps its shape and
meaning ("what the worker claims"); it simply stops being the authority.

---

## 3. Module Breakdown

### Module 1: Git-verified triage evidence

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`
- **Responsibility**: G1 + G2 — replace the triage worker's self-reported
  `files_modified` with the set of paths git observed changing during the
  triage dispatch.
- **Depends on**: nothing in this spec.

Add these two helpers to `QANode`, immediately after `_get_changed_files`
(whose body ends with `return []` at `qa.py:708`) and before the
`@staticmethod def _scope_lint_to_files` at `qa.py:710-711`:

```python
    # ------------------------------------------------------------------
    # Triage evidence — git is the authority, not the worker's claim
    # ------------------------------------------------------------------

    @staticmethod
    async def _git_state(worktree_path: str) -> Tuple[str, FrozenSet[str]]:
        """The worktree's ``(HEAD sha, dirty paths)`` at this instant.

        Both halves degrade to empty on any git failure, which makes
        :meth:`_paths_touched_since` report "nothing changed" rather than
        inventing evidence — the fail-closed direction for a gate.

        Args:
            worktree_path: The feature worktree to inspect.

        Returns:
            The HEAD commit sha (``""`` when unavailable) and the set of
            paths with uncommitted modifications, staged or not.
        """

        async def _run(*args: str) -> str:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    *args,
                    cwd=worktree_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
            except Exception:  # noqa: BLE001 - a missing worktree is not fatal
                return ""
            return stdout.decode() if proc.returncode == 0 else ""

        head = (await _run("rev-parse", "HEAD")).strip()
        dirty = frozenset(
            entry
            for line in (await _run("status", "--porcelain")).splitlines()
            # Porcelain v1: two status chars, a space, then the path. A
            # rename reads "R  old -> new"; the post-rename path is what a
            # later lint/pytest run can actually open, so keep that half.
            if (entry := line[3:].strip().split(" -> ")[-1])
        )
        return head, dirty

    @classmethod
    async def _paths_touched_since(
        cls,
        worktree_path: str,
        before: Tuple[str, FrozenSet[str]],
    ) -> List[str]:
        """Every path that really changed between ``before`` and now.

        A DELTA, deliberately — not an absolute diff against the base
        branch. By the time triage runs, ``DevelopmentNode`` has already
        committed the feature's work, so an absolute diff would "verify"
        any claim naming a file development touched. Only what moved
        during the triage dispatch is evidence that triage did anything.

        Args:
            worktree_path: The feature worktree to inspect.
            before: The :meth:`_git_state` snapshot taken pre-dispatch.

        Returns:
            Sorted repo-relative paths: newly dirty files, plus everything
            in commits the triage dispatch added.
        """
        before_head, before_dirty = before
        after_head, after_dirty = await cls._git_state(worktree_path)

        touched: set = set(after_dirty - before_dirty)

        if before_head and after_head and before_head != after_head:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "diff",
                    "--name-only",
                    f"{before_head}..{after_head}",
                    cwd=worktree_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    touched.update(p.strip() for p in stdout.decode().splitlines() if p.strip())
            except Exception:  # noqa: BLE001 - degrade to the dirty-set delta
                pass

        return sorted(touched)
```

Then wire them into `_run_finding_triage`. Capture the snapshot immediately
before the first dispatch — i.e. replace the line `report = await
_dispatch_once()` at `qa.py:986` with:

```python
        before_state = await self._git_state(worktree_path)
        report = await _dispatch_once()
```

and replace `files_modified_set = set(report.files_modified)` (`qa.py:1001`)
with:

```python
        # The worker's `files_modified` is a claim, not evidence. Git is the
        # authority — both for triggering the (expensive) deterministic
        # re-run and for `_confirm_has_evidence`, which would otherwise be
        # validating the worker's claim against the worker's own claim.
        actual_modified = await self._paths_touched_since(worktree_path, before_state)
        unverified = [p for p in report.files_modified if p not in set(actual_modified)]
        if unverified:
            self.logger.warning(
                "Triage worker claimed %d modified file(s) git cannot see; "
                "dropping the claim and using git's %d instead. Unverified: %s",
                len(unverified),
                len(actual_modified),
                unverified[:20],
            )
        files_modified_set = set(actual_modified)
```

and the return statement (`qa.py:1053`) with:

```python
        return notes, list(actual_modified), escalation_passed
```

`FrozenSet` and `Tuple` must be present in the `typing` import at the head of
`qa.py` — see §6.

### Module 2: `scripts/sdd/lint_new.py` — ruff findings the branch introduced

- **Path**: `scripts/sdd/lint_new.py` (new file)
- **Responsibility**: G3 + G4 — run ruff over given files and report only
  findings whose source range intersects a line the branch added/changed.
- **Depends on**: nothing in this spec.

Write it verbatim:

```python
#!/usr/bin/env python
"""Ruff runner that reports only the findings a branch introduced.

The dev-loop QA gate scopes lint to the files a feature changed — correct,
but too blunt: a five-line addition to a module carrying 28 pre-existing
``UP``-series findings turns that whole backlog into a blocker for the
feature, and the QA feedback then asks the worker to modernise a file it
barely touched. This filters ruff's output down to findings whose reported
source range intersects a line the branch actually added or modified.

Range intersection, not "the finding starts on a changed line", is the point:
``I001`` (un-sorted imports) is reported at the top of the import block with
an ``end_location`` spanning the whole block, so an import added five lines
below the reported row is still correctly attributed to this branch.

Usage:
    python -m scripts.sdd.lint_new [--base <ref>] <file> [<file> ...]

Exit status:
    0 — the branch introduced no new ruff finding (pre-existing ones are
        reported as an informational count only).
    1 — at least one new finding; each is printed in ``ruff --output-format
        concise`` shape.
    2 — ruff itself could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

#: Refs tried, in order, to locate the branch point when --base is omitted.
#: Mirrors ``QANode._get_changed_files``' own candidate order.
_BASE_CANDIDATES = ("origin/dev", "origin/main")

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _git(*args: str) -> str:
    """Run a git command, returning stdout — or ``""`` on any failure."""
    try:
        proc = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )
    except OSError:
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _merge_base(base: str | None) -> str:
    """The commit this branch forked from, or ``""`` when undeterminable."""
    for ref in ([base] if base else list(_BASE_CANDIDATES)):
        sha = _git("merge-base", ref, "HEAD").strip()
        if sha:
            return sha
    return ""


def _parse_hunks(diff_text: str, added: dict[str, set[int]]) -> None:
    """Fold ``git diff -U0`` output into a path -> added-line-numbers map."""
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/") :].strip()
            added.setdefault(current, set())
        elif line.startswith("@@") and current is not None:
            match = _HUNK_RE.match(line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2) or 1)
                added[current].update(range(start, start + count))


def _added_lines(merge_base: str, paths: list[str]) -> dict[str, set[int]]:
    """Every line this branch added or modified, per path.

    One ``git diff`` against the merge base covers committed AND uncommitted
    work in a single call; untracked files are new in their entirety and are
    added separately.
    """
    added: dict[str, set[int]] = {}
    if merge_base:
        _parse_hunks(_git("diff", "-U0", merge_base, "--", *paths), added)

    untracked = _git("ls-files", "--others", "--exclude-standard", "--", *paths).split()
    for rel in untracked:
        try:
            total = len(Path(rel).read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        added.setdefault(rel, set()).update(range(1, total + 1))

    return added


def _ruff_findings(paths: list[str]) -> list[dict] | None:
    """Ruff's JSON findings for ``paths``, or ``None`` when ruff failed."""
    try:
        proc = subprocess.run(
            ["ruff", "check", "--output-format", "json", "--force-exclude", *paths],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    # ruff exits 1 when it finds violations — that is not a failure here.
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stderr)
        return None
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        sys.stderr.write(proc.stdout)
        return None


def _is_new(finding: dict, added: dict[str, set[int]], repo_root: str) -> bool:
    """Whether a finding's source range intersects a line this branch changed."""
    filename = finding.get("filename") or ""
    try:
        rel = os.path.relpath(filename, repo_root)
    except ValueError:
        return True  # cannot attribute it — fail closed, report it
    lines = added.get(rel)
    if not lines:
        return False
    start = int((finding.get("location") or {}).get("row") or 0)
    end = int((finding.get("end_location") or {}).get("row") or start)
    if start <= 0:
        return True
    return any(row in lines for row in range(start, max(end, start) + 1))


def _format(finding: dict, repo_root: str) -> str:
    """One finding in ``ruff --output-format concise`` shape."""
    filename = finding.get("filename") or ""
    try:
        rel = os.path.relpath(filename, repo_root)
    except ValueError:
        rel = filename
    location = finding.get("location") or {}
    return (
        f"{rel}:{location.get('row', 0)}:{location.get('column', 0)}: "
        f"{finding.get('code') or '?'} {finding.get('message') or ''}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report only the ruff findings this branch introduced."
    )
    parser.add_argument("--base", default=None, help="Base ref (default: origin/dev, then origin/main)")
    parser.add_argument("paths", nargs="*", help="Files to check")
    args = parser.parse_args(argv)

    if not args.paths:
        print("lint_new: no files to check — nothing to do.")
        return 0

    repo_root = _git("rev-parse", "--show-toplevel").strip() or os.getcwd()

    findings = _ruff_findings(args.paths)
    if findings is None:
        print("lint_new: ruff could not be run.", file=sys.stderr)
        return 2

    added = _added_lines(_merge_base(args.base), args.paths)
    new = [f for f in findings if _is_new(f, added, repo_root)]
    pre_existing = len(findings) - len(new)

    for finding in new:
        print(_format(finding, repo_root))

    if new:
        print(
            f"lint_new: {len(new)} new finding(s) introduced by this branch "
            f"({pre_existing} pre-existing finding(s) ignored)."
        )
        return 1

    print(
        f"lint_new: no new findings ({pre_existing} pre-existing finding(s) "
        f"in the changed files were ignored)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Module 3: Wire the diff-scoped runner into the QA lint command

- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`
- **Responsibility**: G3 — make `_run_deterministic_qa` build its lint
  command around `lint_new.py` instead of a bare `ruff check`.
- **Depends on**: Module 2.

Add the pattern next to `_LINT_TARGET_RE` (declared at `qa.py:63-65`):

```python
#: Matches the ``ruff check <targets>`` half of a compound lint command, up to
#: the next ``&&``/``;`` separator.
_RUFF_CHECK_RE = re.compile(r"\bruff\s+check\b[^&;]*")
```

Add this classmethod immediately after `_scope_lint_to_files` (whose body
ends at `qa.py:730`) and before the `@classmethod def _scope_criteria` at
`qa.py:732-733`:

```python
    @classmethod
    def _baseline_aware_lint(cls, command: str, files: List[str]) -> str:
        """Swap ``ruff check <targets>`` for the diff-scoped runner.

        Scoping lint to the changed FILES (``_scope_lint_to_files``) stops
        unrelated modules from failing the gate, but still lints each
        changed file in full — so a five-line edit to a module carrying
        pre-existing findings inherits all of them as blockers, and the QA
        feedback then asks the worker to fix debt the feature never
        touched. ``scripts/sdd/lint_new.py`` reports only findings whose
        source range intersects a line this branch changed.

        Only the ``ruff`` half is rewritten: the ``mypy`` half stays on the
        existing file-scoping path (``_scope_lint_to_files``), and a lint
        command with no ``ruff check`` in it is returned untouched, so an
        operator-configured command keeps working.

        Args:
            command: The configured lint command.
            files: Changed files, already resolved by the caller.

        Returns:
            The rewritten command, or ``command`` unchanged when there is
            nothing to scope or no ``ruff check`` to replace.
        """
        if not files:
            return command
        file_args = " ".join(shlex.quote(f) for f in files)
        replacement = f"python -m scripts.sdd.lint_new {file_args}"
        return _RUFF_CHECK_RE.sub(lambda _match: replacement, command, count=1)
```

Then, in `_run_deterministic_qa`, replace `qa.py:461`:

```python
        lint_cmd = self._scope_lint_to_files(self._lint_command, changed)
```

with:

```python
        lint_cmd = self._scope_lint_to_files(
            self._baseline_aware_lint(self._lint_command, changed), changed
        )
```

Ordering matters: `_baseline_aware_lint` runs first so the `ruff check .`
target is gone by the time `_scope_lint_to_files` looks for a `.` to rewrite;
what it then finds is the bare `mypy --no-incremental`, which it scopes to
the changed files exactly as it does today.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_claimed_but_invisible_files_are_dropped` | 1 | Worker claims 13 paths, git shows none changed → returned `files_modified` is `[]` and a warning is logged |
| `test_git_visible_changes_are_reported_even_if_unclaimed` | 1 | Worker claims nothing, git shows a new commit touching `a.py` → `["a.py"]` returned |
| `test_uncommitted_edit_during_triage_counts_as_evidence` | 1 | Worker leaves an uncommitted edit → path is returned |
| `test_pre_existing_dirty_file_is_not_evidence` | 1 | A file already dirty before the dispatch and untouched by it → NOT returned |
| `test_confirm_without_git_evidence_escalates` | 1 | CONFIRM naming a file git never saw → disposition becomes `escalate` |
| `test_git_failure_degrades_to_no_evidence` | 1 | Non-git `worktree_path` → `[]`, no exception |
| `test_pre_existing_finding_on_unchanged_line_is_ignored` | 2 | Baseline file with a violation, branch adds an unrelated clean line → exit 0 |
| `test_new_finding_on_added_line_fails` | 2 | Branch adds a line with a violation → exit 1 and the finding is printed |
| `test_i001_import_block_is_attributed_to_the_added_import` | 2 | Adding an out-of-order import → `I001` reported even though its row is unchanged (G4) |
| `test_untracked_file_counts_as_fully_added` | 2 | New untracked file with a violation → exit 1 |
| `test_no_paths_exits_zero` | 2 | No positional args → exit 0 |
| `test_ruff_failure_exits_two` | 2 | ruff unavailable → exit 2 |
| `test_ruff_half_is_replaced_mypy_half_scoped` | 3 | `"ruff check . && mypy --no-incremental"` → `"python -m scripts.sdd.lint_new a.py && mypy --no-incremental a.py"` |
| `test_command_without_ruff_is_untouched` | 3 | `"mypy --no-incremental"` → only the mypy scoping applies |
| `test_no_changed_files_leaves_command_unchanged` | 3 | `files=[]` → identical string |

### Integration Tests

| Test | Description |
|---|---|
| `test_triage_claim_without_git_evidence_skips_the_qa_rerun` | Drive `QANode.execute` with an advisory reviewer whose triage worker claims files it never wrote; assert `_run_deterministic_qa` is awaited exactly ONCE (the pre-review pass), not twice |
| `test_triage_that_really_commits_triggers_the_rerun` | Same shape, but the fake dispatcher commits a file; assert `_run_deterministic_qa` is awaited TWICE |

### Test Data / Fixtures

Module 2 needs a real git repo. Build it with `subprocess` in a `tmp_path`
fixture (the pattern `tests/sdd_scripts/test_check_id_collisions.py` already
uses) — `git init`, commit a baseline file carrying a known violation, branch,
then apply the change under test:

```python
@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A real git repo on a branch forked from `origin/dev`-shaped history."""
    def run(*args):
        subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)

    run("git", "init", "-q", "-b", "dev")
    run("git", "config", "user.email", "t@t.t")
    run("git", "config", "user.name", "t")
    (tmp_path / "mod.py").write_text("from typing import Dict\n\nX: Dict = {}\n")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "baseline")
    run("git", "checkout", "-qb", "feature")
    monkeypatch.chdir(tmp_path)
    return tmp_path
```

Pass `--base dev` explicitly in Module 2's tests: the fixture has no
`origin/*` refs, and relying on the fallback would make the tests depend on
the developer's own remote state.

---

## 5. Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop tests/sdd_scripts -v` passes.
- [ ] `python -m scripts.sdd.lint_new packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`
      exits 0 on an unmodified `dev` checkout — i.e. the file's pre-existing
      findings do not fail it (G3, and the direct regression for the
      FEAT-494 failure).
- [ ] `QANode._run_finding_triage` no longer returns `report.files_modified`
      anywhere; `grep -n "report.files_modified" qa.py` shows only the
      claim-vs-git comparison.
- [ ] Injecting a fresh violation on a changed line makes
      `scripts/sdd/lint_new.py` exit 1 and print it (G4).
- [ ] `ruff check` on the two touched files reports **no new findings**
      relative to the parent commit (verify with the new script itself).
- [ ] No new entry in `parrot/conf.py` — both behaviours are unconditional (G5).
- [ ] No breaking change to `TriageReport`, `QAReport`, or any node signature.

---

## 6. Codebase Contract

### Verified Imports

```python
# All already present at the head of qa.py — do NOT re-add:
import asyncio                                                    # qa.py:22
import re                                                         # qa.py:24
import shlex                                                      # qa.py:25
from typing import Any, Dict, List, Optional, Tuple, Union        # qa.py:27 — see below
```

**`FrozenSet` is NOT currently imported in `qa.py`.** Module 1's
`_git_state` signature needs it — add it to the existing `typing` import
line, keeping the alphabetical order already used there. `Tuple` IS already
imported (it types `_run_finding_triage`'s return).

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
_DEFAULT_LINT_COMMAND = "ruff check . && mypy --no-incremental"     # line 56
_LINT_TARGET_RE = ...                                              # line 65

class QANode(DevLoopNode):
    def __init__(self, *, dispatcher, ..., lint_command: Optional[str] = None)   # line 137
        self._lint_command = lint_command or _DEFAULT_LINT_COMMAND               # line 145

    async def _run_deterministic_qa(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
        executable: List[AcceptanceCriterion],
        *,
        cwd_override: Optional[str] = None,
    ) -> QAReport:                                                 # line 425
        changed = await self._get_changed_files(effective_cwd)     # line 460
        lint_cmd = self._scope_lint_to_files(self._lint_command, changed)   # line 461 ← Module 3 edits this
        scoped_criteria = self._scope_criteria(executable, changed)         # line 462

    @staticmethod
    async def _get_changed_files(worktree_path: str) -> List[str]:  # line 682
        # `git diff --name-only --diff-filter=d <upstream>...HEAD -- '*.py'`
        # Tries "origin/dev" then "origin/main"; returns [] on any error.

    @staticmethod
    def _scope_lint_to_files(command: str, files: List[str]) -> str:  # line 711

    @classmethod
    def _scope_criteria(cls, criteria, files) -> List[AcceptanceCriterion]:  # line 733

    async def _run_finding_triage(
        self,
        shared: Dict[str, Any],
        research: ResearchOutput,
        brief: BugBrief,
        findings: List[AdversarialFinding],
    ) -> Tuple[List[str], List[str], bool]:                        # line 923
        worktree_path = research.worktree_path                     # line 946
        report = await _dispatch_once()                            # line 986 ← Module 1 inserts before this
        files_modified_set = set(report.files_modified)            # line 1001 ← Module 1 replaces
        return notes, list(report.files_modified), escalation_passed  # line 1053 ← Module 1 replaces

    @staticmethod
    def _confirm_has_evidence(resolved: AdversarialFinding, files_modified: set) -> bool:  # line 1056
        # UNCHANGED — it already takes the evidence set as a parameter; Module 1
        # only changes what is passed in.
```

The triage return value is consumed at `qa.py:287-296`; `files_modified`
drives the re-run branch at `qa.py:314-326`. Neither call site needs editing —
they receive a git-derived list transparently.

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `QANode._git_state` | `asyncio.create_subprocess_exec` | same pattern as `_get_changed_files` | `qa.py:689-705` |
| `QANode._paths_touched_since` | `QANode._git_state` | classmethod call | this spec §3 |
| `QANode._baseline_aware_lint` | `_run_deterministic_qa` | called before `_scope_lint_to_files` | `qa.py:461` |
| `scripts/sdd/lint_new.py` | `sdd-qa` subagent | `python -m scripts.sdd.lint_new` inside `lint_command` | `qa.py:466` (`_QABrief.lint_command`) |
| `scripts/sdd/lint_new.py` | package init | `scripts/sdd/__init__.py` already exists | `scripts/sdd/__init__.py` |

### Does NOT Exist (Anti-Hallucination)

- ~~`QANode._git_changed_files`~~ — that name belongs to **`DevelopmentNode`**
  (`nodes/development.py`), not `QANode`. `QANode`'s helper is
  `_get_changed_files` and it takes ONE argument. Do not import
  `DevelopmentNode` into `qa.py` to reuse its version: it would create a new
  cross-node import for a five-line helper, and its base-branch semantics
  (absolute diff vs. the base) are the WRONG semantics here — Module 1 needs
  a delta across the dispatch.
- ~~`ruff check --diff-only`~~ / ~~`--changed-only`~~ — no such ruff flag.
  The filtering must be done on ruff's JSON output.
- ~~`TriageReport.verified_files`~~ / ~~`files_verified`~~ — the model has
  only `files_modified` and `findings`.
- ~~`conf.DEV_LOOP_LINT_BASELINE`~~ (or any similar knob) — G5 says no new
  configuration; do not add one.
- ~~`scripts/sdd/lint_diff.py`~~ — the file is `lint_new.py`; do not invent a
  second one.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Google-style docstrings and strict type hints on every new function
  (`CLAUDE.md` → Code Standards).
- `async`/`await` with `asyncio.create_subprocess_exec` for git inside
  `qa.py` — never `subprocess.run`, which would block the event loop.
  `scripts/sdd/lint_new.py` is a standalone sync CLI and correctly uses
  `subprocess.run`.
- `self.logger` for the unverified-claim warning; never `print` inside nodes.
- Degrade, never raise: every git failure in Module 1 resolves to "no
  evidence", which fails the gate closed rather than fabricating a pass.

### Known Risks / Gotchas

- **`git status --porcelain` rename lines.** Format is `R  old -> new`; the
  reference implementation keeps the post-rename path. A rename during triage
  therefore reports only the new path — acceptable, and the alternative
  (reporting a path that no longer exists) is worse for the pytest/lint
  re-run that consumes this list.
- **`--porcelain` path quoting.** Paths with unusual characters come back
  quoted. Not handled; the repo has no such paths. If one appears, the path
  simply fails to match a claim and is reported as-is.
- **A finding whose range does not intersect the diff but was still caused by
  it.** Rare beyond the `I001` case that range-intersection already covers
  (e.g. a rule reported at module scope). It would be silently ignored. This
  is the deliberate fail-open direction for Module 2: the alternative — the
  status quo — blocks features on unrelated debt, which is the defect being
  fixed.
- **`--force-exclude`** is passed to ruff so explicitly-listed files that the
  project excludes stay excluded, matching what `ruff check .` would do.
- **The pre-existing `ModuleNotFoundError: parrot.utils.types`** seen on
  `run-49039bac` (collection error across 326 modules, exit 4) is an
  environment/build problem, NOT in scope here. Neither module addresses it,
  and Module 2 does not make a failing pytest collection pass.
- **Run the acceptance criteria from the repo root.** `python -m
  scripts.sdd.lint_new` resolves `scripts` as a top-level package, exactly
  like `python -m scripts.sdd.reserve_ids` in `/sdd-spec`. It is invoked with
  the worktree as cwd by the `sdd-qa` subagent, which is the repo root of
  that worktree.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `ruff` | already a dev dependency | `--output-format json` (stable since ruff 0.1) |

No new dependency is introduced.

---

## 8. Open Questions

- [x] Should the triage claim be intersected with git, or replaced by it? —
      *Resolved at spec time*: replaced. An intersection would still let a
      claim suppress a real change git saw; `_reconcile_files_changed`
      already set the precedent that git wins.
- [x] Baseline-subtraction or diff-line attribution for lint? — *Resolved at
      spec time*: diff-line attribution. Baseline subtraction needs ruff's
      config (notably `per-file-ignores`) to resolve identically for files
      materialised outside their real path, and doubles lint runtime.
- [x] Does `mypy` get the same treatment? — *Resolved at spec time*: no, see
      §1 Non-Goals. The observed failure was entirely ruff.
- [ ] Should `lint_new.py` also gate on **removed** lines (a deletion that
      makes a surviving line violate a rule)? — *Owner: Jesus Lara*; can be
      decided during implementation, defaults to "no".

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree, tasks run sequentially.
- Modules 1 and 2 are genuinely independent (different files, no shared
  symbol) and could run in parallel; Module 3 depends on Module 2. With only
  three small tasks the pool's coordination overhead exceeds the gain — run
  them sequentially in one worktree.
- **Cross-feature dependencies**: none. The `feedback_router` retry hotfix
  (`843fa0095`) is already on `dev`; base this feature on top of it so the
  integration tests in §4 exercise a retry path that actually dispatches.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-02 | Jesus Lara | Initial draft — defects 3 & 4 from the `run-49039bac` post-mortem |
