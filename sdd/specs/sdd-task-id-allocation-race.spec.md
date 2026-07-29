---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: SDD Task-ID Allocation Race Fix

**Feature ID**: FEAT-387
**Date**: 2026-07-28
**Author**: Claude (session-initiated, per user request)
**Status**: approved
**Target version**: n/a (tooling-only, no package version bump)

---

## 1. Motivation & Business Requirements

### Problem Statement

`/sdd-task` (and, to a lesser extent, `/sdd-spec` for Feature IDs) assigns
`TASK-<NNN>` numbers by scanning existing task files/indexes for the highest
number currently in use and incrementing it — "check existing before
assigning" is literally the entire documented algorithm
(`.claude/commands/sdd-task.md` never specifies more than the placeholder
`TASK-<NNN>`, and `.claude/commands/sdd-spec.md:230` says only "check
existing; increment last; start at FEAT-001 if none"). There is no lock, no
reservation step, and no re-check against `origin/<base_branch>` immediately
before the new task files are committed.

This was caught empirically while closing out FEAT-380
(sandbox-hardening): `TASK-1939` through `TASK-1946` were independently
reused by an unrelated `eventbus-replacement-evaluation` feature
(`TASK-1939-audit-residual-bus-artifacts.md`,
`TASK-1940-fix-residual-bus-issues.md`, …) and by three
`fix-msword-loader-none-*` fix specs
(`TASK-1941-guard-test-update-and-green-gate.md`,
`TASK-1942-guard-para-style-none.md`,
`TASK-1944-guard-para-style-none-access.md`,
`TASK-1946-guard-para-style-none-access.md`) — six numeric collisions across
three unrelated features, discovered only because `/sdd-done`'s task-closing
step happened to glob by `TASK-<NNN>-*.md` and moved (or, in this case,
would have incorrectly moved) more than one file per number.

**Why this is invisible to git and survives silently today:** two
`/sdd-task` runs racing each other allocate the same `TASK-<NNN>` for
*different* slugs — e.g. `TASK-1939-repl-dedicated-executor.md` vs.
`TASK-1939-audit-residual-bus-artifacts.md`. These are different file
*paths*, so git's merge machinery sees no conflict at all: both commits
land cleanly via ordinary sequential fast-forward pushes. Nothing detects
the collision unless a human or a script later greps/globs by the numeric
ID alone (which several existing SDD scripts do — see `close_task.sh` and
the "Codebase Contract" below). The race is real, silent, and only
surfaces as accidental data loss at close/cleanup time, not at creation
time when it would be cheap to catch.

**Root cause, precisely:** the "highest number currently in use" scan reads
whatever `dev` looks like on the *local* machine/worktree at the moment
`/sdd-task` runs. When the SDD dev-loop pipeline (FEAT-378
devloop-enhancement, `sdd-planner` subagent) dispatches spec/task creation
for multiple features around the same time, each invocation's `git pull
--ff-only` (`.claude/commands/sdd-task.md` §1) can complete before the
*other* invocation's task-creation commit has been pushed to `origin/dev` —
so both compute the same "next" number from a view of `dev` that doesn't
yet include the other's allocation. This is a textbook TOCTOU
(time-of-check-to-time-of-use) race on an implicit, unprotected shared
counter.

### Goals
- Eliminate silent `TASK-<NNN>` collisions across independently-created
  features, whether created by a human running `/sdd-task` manually or by
  the autonomous dev-loop pipeline dispatching multiple planner runs.
- Shrink the race window for `FEAT-<NNN>` allocation (`/sdd-spec`) using the
  same mechanism, since it has the identical "check existing; increment"
  weakness — but see Non-Goal below on why FEAT-ID *reuse* itself is not
  being outlawed.
- Add a cheap, no-network-required, defense-in-depth check that can catch
  any collision that still slips through (e.g. from an older cached
  command definition, a manual edit, or a bug in the new allocator) before
  it lands on `dev`, rather than relying solely on the allocator being
  bug-free forever.
- Keep the fix scoped to the allocation mechanism only — no changes to the
  per-spec index schema (FEAT-145), the task file format, or any other part
  of the SDD workflow.

### Non-Goals (explicitly out of scope)
- **Outlawing `FEAT-<NNN>` reuse across specs.** `scripts/sdd/migrate_index.py`
  already documents, as an accepted fact of this codebase, that "multiple
  specs share a numeric [feature] ID in the wild" and disambiguates by the
  `feature` slug, not `feature_id`. FEAT-380 itself is intentionally shared
  across three specs (`sandbox-hardening`, `shelltool-hardening`,
  `tool-result-compression`) as one initiative split into multiple specs by
  design. This spec does **not** change that tolerance — it only fixes
  `TASK-<NNN>` uniqueness, since task files (unlike specs) are looked up by
  numeric-ID-prefix glob in multiple existing scripts (`close_task.sh`) with
  no feature-slug disambiguation, so a task-ID collision silently corrupts
  an unrelated feature's SDD state in a way a feature-ID collision does not.
- **A centralized ID-issuing server or database.** The fix must work with
  nothing more than the existing git remote — no new infrastructure.
- **Renumbering any of the ~1946 existing TASK IDs**, including the six
  colliding ones found during FEAT-380's closeout. Those files are left as
  they are; this spec only prevents *new* collisions going forward.
- **Changing `/sdd-start`, `/sdd-done`, or any other SDD command's
  behavior** beyond the ID-allocation call sites in `/sdd-task` and
  `/sdd-spec`.

---

## 2. Architectural Design

### Overview

Replace the "scan files, take the max, +1" allocation with a tiny,
git-native **compare-and-swap ledger**: a single JSON file,
`sdd/tasks/.id_ledger.json`, holding the next-available `TASK` and `FEAT`
numbers. Allocating N task IDs (or one feature ID) becomes: read the
ledger, compute the reserved range, commit an *ledger-only* update, and
push. If the push is rejected (because another allocation landed first),
`git fetch` + re-read the now-current ledger + recompute + retry — bounded
retries with jitter, matching the classic optimistic-concurrency-with-retry
pattern used for git-backed counters elsewhere (e.g. Homebrew's bottle
build numbers, many `CHANGELOG` bump bots).

This shrinks the race window from "the entire duration of spec/task
authoring" (today: unbounded, easily minutes) down to "the time to push one
single-line JSON diff" (typically sub-second), and — critically — makes a
losing allocator **fail loudly and retry** instead of silently succeeding
with a stale number, because a non-fast-forward push is a hard error, not a
silent no-op.

A second, independent line of defense — a stateless collision checker,
runnable both as a manual command and in CI — catches anything that still
gets through (bugs in the new allocator, hand-edited task files, pre-fix
task files that were created concurrently with this fix's own rollout).

### Component Diagram
```
/sdd-task, /sdd-spec (Claude Code commands)
        │
        ▼
scripts/sdd/reserve_ids.py  ──reads/writes──▶  sdd/tasks/.id_ledger.json
        │                                              ▲
        │ (git fetch + retry on push rejection)        │
        └──────────────────────────────────────────────┘
                          │
                          ▼
              git push origin <base_branch>

scripts/sdd/check_id_collisions.py  ──scans──▶  sdd/tasks/index/*.json
        │                                       sdd/tasks/active/*.md
        │                                       sdd/tasks/completed/*.md
        ▼
  exit 0 (clean) | exit 1 (collision found, listed)
        │
        └──wired into──▶ .github/workflows/ci.yml (new job)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.claude/commands/sdd-task.md` §4 "Generate Tasks" | modifies | Numbering step now calls `reserve_ids.py --kind task --count N` instead of an ad-hoc scan; the returned IDs are used verbatim for `TASK-<NNN>-<slug>.md` and the index entries. |
| `.claude/commands/sdd-spec.md` (Feature ID assignment, §"check existing; increment last") | modifies | Calls `reserve_ids.py --kind feature --count 1` instead of manual scanning, but a spec MAY still explicitly reuse an existing `FEAT-<NNN>` when the author is intentionally splitting one initiative across multiple specs (Non-Goal above) — the reservation call is skipped in that explicit-reuse path. |
| `scripts/sdd/sdd_meta.py` | uses (no changes) | `reserve_ids.py` reads `base_branch` the same way existing commands do, so it operates on the correct branch (`dev`/`staging`/`main` per FEAT-145/187) without duplicating that logic. |
| `scripts/sdd/close_task.sh` | uses (no changes, but now benefits) | Its `TASK-ID-*.md` glob is exactly the code path that silently mismatched files on a collision (found empirically in FEAT-380's closeout); this fix removes the underlying cause without touching the script itself. |
| `.github/workflows/ci.yml` | modifies | New job runs `scripts/sdd/check_id_collisions.py` on every push/PR touching `sdd/tasks/**` or `sdd/specs/**`, as a defense-in-depth backstop. |
| `sdd/WORKFLOW.md`, `CLAUDE.md` | modifies | Document the ledger file, the reservation script, and the collision checker as part of the standard SDD auto-commit rules table. |

### Data Models
```python
from pydantic import BaseModel, Field


class IdLedger(BaseModel):
    """The full contents of sdd/tasks/.id_ledger.json.

    A single, tiny, git-tracked file acting as a compare-and-swap counter
    for globally-unique TASK-<NNN> numbers (and, best-effort, FEAT-<NNN>
    numbers). Every allocator reads this file, computes a reservation,
    and races to push an update — the push itself is the compare-and-swap:
    a non-fast-forward rejection means someone else already advanced the
    counter, so the allocator must re-read and retry.
    """

    next_task_id: int = Field(..., ge=1, description="Next unassigned TASK number.")
    next_feature_id: int = Field(..., ge=1, description="Next unassigned FEAT number.")
    updated_at: str = Field(..., description="ISO-8601 UTC timestamp of the last reservation.")
    updated_by: str = Field(..., description="Free-text origin of the last reservation (feature slug or session id) — diagnostic only, not used for correctness.")


class IdReservation(BaseModel):
    """Result handed back to the calling SDD command."""

    kind: str  # "task" | "feature"
    first_id: int
    count: int
    ids: list[str]  # e.g. ["TASK-1961", "TASK-1962", ...] or ["FEAT-387"]
```

### New Public Interfaces
```python
# scripts/sdd/reserve_ids.py

def reserve_ids(
    kind: Literal["task", "feature"],
    count: int,
    base_branch: str,
    label: str,
    *,
    max_retries: int = 5,
) -> IdReservation:
    """Atomically reserve `count` sequential TASK or FEAT numbers.

    Reads sdd/tasks/.id_ledger.json, computes the next `count` numbers of
    the given `kind`, commits the incremented ledger, and pushes to
    `origin/<base_branch>`. On a non-fast-forward push rejection, fetches
    the current remote state, re-reads the ledger, recomputes, and retries
    up to `max_retries` times (with jittered backoff). Raises
    `IdReservationError` if retries are exhausted.

    This function's own commit touches ONLY sdd/tasks/.id_ledger.json —
    it never bundles in the task/spec files themselves, so the
    reservation race is decided by a single-line JSON diff, not by
    whatever else the calling command is about to commit.
    """
```

```python
# scripts/sdd/check_id_collisions.py

def find_collisions() -> list[CollisionReport]:
    """Scan sdd/tasks/index/*.json, sdd/tasks/active/*.md, and
    sdd/tasks/completed/*.md for any TASK-<NNN> or FEAT-<NNN> number that
    is associated with more than one distinct feature slug. Returns one
    CollisionReport per colliding number (empty list = clean).
    """
```

---

## 3. Module Breakdown

### Module 1: `IdLedger` model + `sdd/tasks/.id_ledger.json` bootstrap
- **Path**: `scripts/sdd/id_ledger.py` (Pydantic model + read/write helpers)
- **Responsibility**: Define `IdLedger`, load/save it as JSON, and a
  one-time bootstrap that seeds `next_task_id`/`next_feature_id` from the
  current maximum across `sdd/tasks/index/*.json` (`+1`) and
  `sdd/specs/*.md` (`+1`) respectively, so the ledger starts strictly ahead
  of every ID in use today (including the six known-colliding numbers).
- **Depends on**: none (new file).

### Module 2: `reserve_ids.py` — the compare-and-swap allocator
- **Path**: `scripts/sdd/reserve_ids.py`
- **Responsibility**: `reserve_ids()` per the interface above: read ledger
  → compute reservation → commit ledger-only diff → push → on rejection,
  fetch + re-read + retry. CLI entrypoint
  (`python -m scripts.sdd.reserve_ids --kind task --count 8 --base-branch dev --label sandbox-hardening`)
  prints the reserved IDs one per line for the calling command to consume.
- **Depends on**: Module 1.

### Module 3: `check_id_collisions.py` — defense-in-depth scanner
- **Path**: `scripts/sdd/check_id_collisions.py`
- **Responsibility**: `find_collisions()` per the interface above; CLI
  exits 1 and prints a human-readable report if any collision is found,
  exits 0 otherwise. Explicitly allowed to find (and NOT flag)
  `FEAT-<NNN>` numbers shared across multiple specs (Non-Goal) — only
  `TASK-<NNN>` collisions are treated as failures, plus `FEAT-<NNN>`
  collisions are still *reported* (not failed) for visibility.
- **Depends on**: none (read-only, independent of Modules 1/2).

### Module 4: Wire `/sdd-task` and `/sdd-spec` to the allocator
- **Path**: `.claude/commands/sdd-task.md`, `.claude/commands/sdd-spec.md`
- **Responsibility**: Replace the "scan and increment" numbering
  instructions with a call to `reserve_ids.py`, using the returned IDs
  verbatim for file names and index/spec-header fields. `/sdd-spec` keeps
  an explicit escape hatch for the documented, intentional FEAT-ID-reuse
  case (splitting one initiative across multiple specs).
- **Depends on**: Module 2.

### Module 5: CI wiring + docs
- **Path**: `.github/workflows/ci.yml`, `sdd/WORKFLOW.md`, `CLAUDE.md`
- **Responsibility**: Add a CI job running
  `python -m scripts.sdd.check_id_collisions` on any push/PR touching
  `sdd/tasks/**` or `sdd/specs/**`; document the ledger file and both
  scripts in the SDD Auto-Commit Rule table and `WORKFLOW.md`.
- **Depends on**: Module 3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_ledger_bootstrap_seeds_ahead_of_existing_ids` | Module 1 | Bootstrapping on a repo with existing `TASK-1946`/`FEAT-386` produces `next_task_id >= 1947`, `next_feature_id >= 387`. |
| `test_ledger_roundtrip` | Module 1 | `IdLedger` save → load is byte-for-byte stable (matches the "byte-equivalent output" convention already used by `migrate_index.py`). |
| `test_reserve_ids_happy_path` | Module 2 | Single allocator run against a throwaway local bare-remote fixture reserves the expected contiguous IDs and advances the ledger by exactly `count`. |
| `test_reserve_ids_retries_on_non_fast_forward` | Module 2 | Simulates a concurrent push landing between this allocator's read and its push attempt; asserts it fetches, recomputes (skipping the now-taken numbers), and succeeds without ever returning a number the concurrent commit already claimed. |
| `test_reserve_ids_raises_after_max_retries` | Module 2 | A remote that rejects every push (simulating a pathological hot-loop) causes `IdReservationError` after `max_retries`, not an infinite loop. |
| `test_reserve_ids_commit_touches_only_ledger` | Module 2 | The commit produced by `reserve_ids()` stages exactly one file (`sdd/tasks/.id_ledger.json`) — guards against the ledger commit accidentally bundling in caller-side working-tree changes. |
| `test_find_collisions_detects_task_id_reuse` | Module 3 | Given two fixture task files with the same `TASK-<NNN>` prefix but different slugs/feature, `find_collisions()` reports exactly one `TASK` collision. |
| `test_find_collisions_tolerates_feature_id_reuse` | Module 3 | Given two specs sharing the same `FEAT-<NNN>` (the FEAT-380 pattern), `find_collisions()` does NOT include it in the failing set, but does include it in an informational "shared feature IDs" list. |
| `test_find_collisions_clean_repo_exits_zero` | Module 3 | Running against the current `sdd/` tree (after the six known FEAT-380-era collisions are either left alone per Non-Goals, or documented as a pre-existing accepted exception) exits 0 for `TASK` collisions introduced by this spec's own test fixtures. |

### Integration Tests
| Test | Description |
|---|---|
| `test_sdd_task_end_to_end_uses_reserved_ids` | Running `/sdd-task` twice in quick succession against two different specs (simulated as two sequential local invocations against the same bare remote, standing in for two concurrent dev-loop dispatches) produces two features with zero `TASK-<NNN>` overlap. |
| `test_ci_collision_job_fails_on_reintroduced_collision` | A CI-equivalent local run of `check_id_collisions.py` against a deliberately-reconstructed pre-fix-style collision (two task files, same number, different slugs) exits non-zero with both offending paths named in the output. |

### Test Data / Fixtures
```python
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def bare_remote_and_clone(tmp_path: Path):
    """A throwaway bare git 'origin' plus one clone, standing in for the
    real `dev` branch — lets reservation/retry tests exercise real
    `git fetch`/`git push` rejection semantics without touching the actual
    repository or network.
    """
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True)
    # ... seed sdd/tasks/.id_ledger.json + an initial commit + push ...
    return remote, clone
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `sdd/tasks/.id_ledger.json` exists, is bootstrapped strictly ahead of
      every `TASK-<NNN>`/`FEAT-<NNN>` currently in use, and is committed to
      `dev`.
- [ ] `scripts/sdd/reserve_ids.py` allocates task/feature IDs via the
      read-commit-push-retry compare-and-swap pattern described in §2; a
      simulated concurrent allocation (two processes racing against the
      same bare-remote fixture) never returns overlapping IDs.
- [ ] `scripts/sdd/check_id_collisions.py` exits non-zero and names every
      offending file when two DIFFERENT-slug task files share a
      `TASK-<NNN>` number; exits 0 on the current, otherwise-clean parts of
      the tree; does not fail on the accepted `FEAT-<NNN>` reuse pattern.
- [ ] `/sdd-task` (`.claude/commands/sdd-task.md`) no longer contains any
      "scan existing, take the max" numbering instructions — it calls
      `reserve_ids.py` and uses the returned IDs verbatim.
- [ ] `/sdd-spec` (`.claude/commands/sdd-spec.md`) calls `reserve_ids.py`
      for new Feature IDs, while still supporting explicit, intentional
      FEAT-ID reuse for a spec that is a deliberate split of an existing
      initiative (documented escape hatch, not a silent fallback).
- [ ] `.github/workflows/ci.yml` runs `check_id_collisions.py` on every
      push/PR touching `sdd/tasks/**` or `sdd/specs/**` and fails the build
      on a `TASK-<NNN>` collision.
- [ ] All unit + integration tests pass:
      `pytest packages/ai-parrot/tests/... -k id_ledger or reserve_ids or check_id_collisions -v`
      (exact test module path to be finalized at task-decomposition time —
      likely `scripts/sdd/tests/` alongside the scripts, since they are
      not part of the `parrot` package proper).
- [ ] No breaking changes to the per-spec index schema, task file format,
      or any command's OTHER behavior.
- [ ] `sdd/WORKFLOW.md` and `CLAUDE.md`'s SDD Auto-Commit Rule table
      document the new ledger file and both scripts.
- [ ] The six pre-existing `TASK-<NNN>` collisions discovered during
      FEAT-380's closeout are left untouched (Non-Goal) and are NOT
      required to pass the new collision checker retroactively — the
      checker's CI job only runs on NEW pushes/PRs from this point forward
      (a one-time baseline exception, documented inline in the workflow
      file, is acceptable so existing history doesn't block unrelated PRs).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from pathlib import Path                          # verified: scripts/sdd/migrate_index.py:19
from pydantic import BaseModel, model_validator    # verified: scripts/sdd/sdd_meta.py:19
import yaml                                        # verified: scripts/sdd/sdd_meta.py:18
import json                                        # verified: scripts/sdd/migrate_index.py:20
import argparse                                    # verified: scripts/sdd/migrate_index.py:20
from scripts.sdd.sdd_meta import parse, FlowMeta    # verified: scripts/sdd/sdd_meta.py:29,45 (used by every SDD command via `python -c "from scripts.sdd.sdd_meta import parse..."`, e.g. .claude/commands/sdd-task.md:26)
```

### Existing Class Signatures
```python
# scripts/sdd/sdd_meta.py
class FlowMeta(BaseModel):
    type: Literal["feature", "hotfix"]   # line 32
    base_branch: str                     # line 33

def parse(doc_path: Path) -> FlowMeta:  # line 45 — returns FlowMeta(type="feature", base_branch="dev") when no frontmatter present
def emit(meta: FlowMeta) -> str:        # line 78

# scripts/sdd/close_task.sh
# Bash script, not Python. Resolves the active file to move via:
#   active_matches=("$ACTIVE_DIR/${TASK_ID}-"*.md)   # line 54 — GLOBS BY TASK-ID PREFIX ONLY, no feature disambiguation.
# This is the exact code path a TASK-ID collision silently corrupts
# (confirmed empirically during FEAT-380's /sdd-done closeout: this glob
# would have matched files belonging to two different, unrelated
# features had they been closed via this script instead of manually).

# scripts/sdd/migrate_index.py
# _build_meta_registry() docstring/comment (line ~19-21, paraphrased):
#   "groups tasks by their `feature` slug (NOT `feature_id` — multiple
#    specs share a numeric ID in the wild, so the slug is the
#    disambiguator)"
# This is the authoritative, pre-existing statement that FEAT-ID reuse
# across specs is ACCEPTED, not a bug — this spec's Non-Goals rely on it.
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `reserve_ids.py` | `sdd_meta.parse()` | reads `base_branch` for the correct remote branch to push against | `scripts/sdd/sdd_meta.py:45` |
| `/sdd-task` §4 "Generate Tasks" | `reserve_ids.py` CLI | subprocess call, replacing the undocumented scan-and-increment step | `.claude/commands/sdd-task.md:94-97` |
| `/sdd-spec` Feature-ID assignment | `reserve_ids.py` CLI | subprocess call, replacing "check existing; increment last" | `.claude/commands/sdd-spec.md:230` |
| `check_id_collisions.py` | `sdd/tasks/index/*.json`, `sdd/tasks/active/*.md`, `sdd/tasks/completed/*.md` | read-only glob/scan, same file set `close_task.sh` operates on | `scripts/sdd/close_task.sh:45-55` |
| `.github/workflows/ci.yml` | `check_id_collisions.py` | new job, `python -m scripts.sdd.check_id_collisions` | new addition; existing jobs verified via `.github/workflows/ci.yml` (present, no prior `sdd/` references) |

### Does NOT Exist (Anti-Hallucination)
- ~~`scripts/sdd/next_task_id.py`~~ — does not exist yet; this spec creates
  `reserve_ids.py` and `id_ledger.py` instead (naming per Module 1/2 above).
- ~~`sdd/tasks/.index.json` as an active file~~ — this is the legacy
  monolith, explicitly preserved as a historical artifact and ignored by
  all FEAT-145 commands (`CLAUDE.md`, "Migration history"). The new ledger
  file `sdd/tasks/.id_ledger.json` is unrelated and must not be confused
  with it, nor should the fix resurrect the monolith as a counter source.
- ~~A `flock`/file-lock-based allocator~~ — rejected design; the repo has
  no shared filesystem across the machines/CI runners/dev-loop sandboxes
  that would invoke `/sdd-task`, so a local file lock cannot coordinate
  across them. The git-push-rejection retry loop is the only mechanism
  that works across genuinely independent clones/worktrees.
- ~~Any change to `WorkerPool`, `WorkerHandle`, or anything under
  `parrot/tools/repl_worker/`~~ — unrelated to this spec; do not touch
  FEAT-380 code while implementing this fix.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Match `scripts/sdd/migrate_index.py`'s conventions: `from __future__ import
  annotations`, `pathlib.Path` throughout, a `--dry-run` flag on any script
  that mutates state, and byte-stable JSON output (`json.dumps(..., indent=2,
  sort_keys=False)` matching the per-spec index style) so diffs stay small
  and reviewable.
- `reserve_ids.py`'s retry loop should use `subprocess.run(["git", ...],
  check=True, capture_output=True, text=True)` and detect a non-fast-forward
  rejection specifically (via git's exit code / stderr pattern), not treat
  every failure identically — an auth failure or network error should NOT
  be retried the same way a rejected push is.
- Follow the project's async-first convention where it applies to actual
  `parrot/` package code, but note these are **standalone repo-tooling
  scripts** (like `migrate_index.py`), not part of the `parrot` package —
  synchronous, direct `subprocess`/`pathlib` code matching
  `migrate_index.py`'s own style is correct here, not `asyncio`.
- Google-style docstrings + type hints throughout, per project convention.

### Known Risks / Gotchas
- **Retry storms under heavy dev-loop parallelism**: if many planner
  instances race simultaneously, later retries could still collide with
  each other repeatedly. Mitigate with jittered exponential backoff
  (`random.uniform` between retry attempts) and a generous-but-bounded
  `max_retries` (default 5, configurable) — document that a very large
  fan-out (dozens of simultaneous `/sdd-task` runs) may need a larger
  `max_retries` or a longer backoff ceiling; this is a tuning knob, not a
  correctness gap.
- **The ledger commit itself could race with the caller's OWN task/spec
  commit** if not sequenced carefully — `reserve_ids.py` MUST commit and
  push the ledger update as an independent, immediate commit BEFORE the
  calling command starts writing task/spec files, not bundled into the
  same commit. This is why Module 2's test list includes
  `test_reserve_ids_commit_touches_only_ledger`.
- **Bootstrap correctness**: the one-time ledger bootstrap must scan
  `sdd/tasks/index/*.json` (not just `sdd/tasks/active/`+`completed/`,
  since a task could theoretically be referenced in the index without a
  file present, or vice versa during an in-flight migration) AND
  `sdd/specs/*.md` for the FEAT counter, taking the max across both to
  avoid seeding the ledger BEHIND an ID already in use.
- **The six known pre-existing collisions** must NOT trip up the
  bootstrap's "seed strictly ahead of every ID in use" logic — taking the
  simple numeric max across all files already handles this correctly
  (the max is the max, regardless of how many slugs share the highest
  number), so no special-casing is needed there.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `==2.12.5` (already pinned, `packages/ai-parrot/pyproject.toml:51`) | `IdLedger`/`IdReservation` models, matching `sdd_meta.py`'s existing use |
| `PyYAML` | `>=6.0.2` (already a dependency) | Not directly needed by this spec's scripts, but already present for `sdd_meta.py`; no new dependency required |
| (none new) | — | This spec introduces zero new third-party dependencies — `subprocess`, `json`, `pathlib`, `argparse` are all stdlib. |

---

## 8. Open Questions

- [ ] Should `reserve_ids.py` live under `scripts/sdd/` (matching
      `migrate_index.py`, `close_task.sh`) or under a new
      `scripts/sdd/ids/` sub-package if Module 1+2 grow enough to warrant
      splitting the model from the CLI? — *Owner: implementer, decide at
      task-decomposition time; default to flat `scripts/sdd/` unless the
      combined file exceeds ~200 lines.*
- [ ] Should the CI collision job be a required check (blocking merge) or
      advisory-only for the initial rollout, given the six known
      pre-existing collisions need an explicit baseline exception? —
      *Owner: repo maintainer (Jesus Lara) — recommend required-but-only-
      for-diff (i.e. only fails on NEW collisions introduced by the PR's
      own diff, not pre-existing ones), matching how most "no new lint
      errors" gates are implemented elsewhere in this repo (see the
      code-review pattern in FEAT-380's fix commit, which explicitly
      diffed "new vs. pre-existing" lint errors by line range).*
- [ ] Should `/sdd-spec`'s "explicit FEAT-ID reuse" escape hatch require an
      interactive confirmation, or is a documented flag/frontmatter field
      (e.g. `reuse_feature_id: FEAT-380`) sufficient? — *Owner: implementer,
      lean toward the explicit frontmatter field for auditability, decide
      at task-decomposition time.*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-28 | Claude | Initial draft, filed per user request after the FEAT-380 closeout surfaced six TASK-ID collisions with unrelated features. |
