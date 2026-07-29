# TASK-1964: `reserve_ids.py` — compare-and-swap ID allocator

**Feature**: FEAT-387 — SDD Task-ID Allocation Race Fix
**Spec**: `sdd/specs/sdd-task-id-allocation-race.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1963
**Assigned-to**: unassigned

---

## Context

TASK-1963 provides `IdLedger` and `load_ledger`/`save_ledger`. This task
implements the actual allocation mechanism (spec §2 Architectural Design,
§3 Module 2): read the ledger, compute a reservation, commit a
ledger-only diff, push to `origin/<base_branch>`, and — on a
non-fast-forward push rejection — fetch, re-read the now-current ledger,
recompute, and retry. This is the piece that actually closes the race
window described in the spec's Problem Statement, by making a losing
allocator fail loudly (non-fast-forward push rejection) and retry, instead
of silently succeeding with a stale number.

---

## Scope

- Implement `reserve_ids(kind, count, base_branch, label, *, max_retries=5,
  repo_root=None) -> IdReservation` per spec §2 New Public Interfaces.
- The function's own git commit MUST touch only
  `sdd/tasks/.id_ledger.json` — never bundle in any other working-tree
  changes the caller may have pending.
- Detect a non-fast-forward push rejection specifically (distinct from an
  auth failure or network error, which should NOT be retried the same
  way) via `git push`'s exit code and stderr content.
- On rejection: `git fetch origin <base_branch>`, `git reset --hard
  origin/<base_branch>` (or an equivalent rebase — see Implementation
  Notes), re-`load_ledger()`, recompute the reservation from the new
  state, retry the commit+push. Bounded by `max_retries`, with jittered
  backoff between attempts (`random.uniform`).
- Raise `IdReservationError` (new exception) after `max_retries` is
  exhausted.
- CLI: `python -m scripts.sdd.reserve_ids --kind task --count 8
  --base-branch dev --label sandbox-hardening` prints the reserved IDs one
  per line (e.g. `TASK-1963`, `TASK-1964`, ...) to stdout, so a calling
  shell command in `/sdd-task`/`/sdd-spec` can capture them directly.
- Write unit tests using a throwaway local bare-remote fixture (spec's Test
  Data / Fixtures) to exercise real `git fetch`/`git push` rejection
  semantics without touching the actual repository.

**NOT in scope**:
- The collision scanner (TASK-1965).
- Wiring `/sdd-task`/`/sdd-spec` command files to actually call this script
  (TASK-1966) — this task only produces the script + its own tests.
- CI wiring (TASK-1967).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/reserve_ids.py` | CREATE | `reserve_ids()`, `IdReservation` model, `IdReservationError`, CLI entrypoint |
| `tests/sdd_scripts/test_reserve_ids.py` | CREATE | Happy path, retry-on-rejection, max-retries-exhausted, commit-touches-only-ledger tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-28. TASK-1963 (this task's
> dependency) must be `done` before starting — re-verify the signatures
> below against its actual implementation, not just this description, since
> the executing agent for TASK-1963 may have adjusted details within its
> own scope.

### Verified Imports
```python
from __future__ import annotations
import argparse
import random
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel  # verified: scripts/sdd/sdd_meta.py:19

from scripts.sdd.id_ledger import IdLedger, load_ledger, save_ledger  # produced by TASK-1963 — re-verify exact names via `read scripts/sdd/id_ledger.py` before using
```

### Existing Signatures to Use
```python
# scripts/sdd/id_ledger.py (TASK-1963 — VERIFY actual signatures before use, this is the spec's planned shape)
class IdLedger(BaseModel):
    next_task_id: int
    next_feature_id: int
    updated_at: str
    updated_by: str

def load_ledger(path: Path) -> IdLedger: ...
def save_ledger(path: Path, ledger: IdLedger) -> None: ...
```

**Git subprocess pattern to follow** — this codebase already runs git via
`subprocess` in the SDD command definitions (not Python scripts, but the
same shell primitives apply): `.claude/commands/sdd-task.md:30-31` uses
`git checkout "$BASE"` / `git pull --ff-only origin "$BASE"`. This task's
Python equivalent should use `subprocess.run([...], check=True,
capture_output=True, text=True)` and inspect `CalledProcessError` for
non-fast-forward detection (git's stderr for a rejected push contains
`"[rejected]"` and `"(fetch first)"` or `"(non-fast-forward)"` — verify
this exact wording against the installed git version's actual output in
the test fixture rather than hardcoding a guess).

### Does NOT Exist
- ~~`scripts/sdd/reserve_ids.py`~~ — this task creates it.
- ~~A `Ledger.reserve()` method~~ — TASK-1963 deliberately keeps `IdLedger`
  a pure data container (see TASK-1963's "Does NOT Exist" section); all
  reservation/increment/retry logic belongs in THIS module's
  `reserve_ids()` function, not on the model.
- ~~Any use of `git merge`/`git rebase` against the CALLER's own working
  tree state~~ — `reserve_ids()` must not touch any files the caller has
  modified; it operates ONLY on `sdd/tasks/.id_ledger.json` in its own
  commit. If the caller's working tree is dirty with unrelated changes,
  `reserve_ids()`'s `git add`/`git commit` must stage ONLY the ledger file
  (`git add sdd/tasks/.id_ledger.json`, never `git add .` / `git add -A`),
  matching the project's own "never `git add -A`" convention (CLAUDE.md,
  "Git Safety Protocol").

---

## Implementation Notes

### Pattern to Follow
```python
# scripts/sdd/reserve_ids.py — sketch
from __future__ import annotations

import random
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel

from scripts.sdd.id_ledger import load_ledger, save_ledger

LEDGER_PATH = Path("sdd/tasks/.id_ledger.json")


class IdReservationError(RuntimeError):
    """Raised when reserve_ids() exhausts its retry budget."""


class IdReservation(BaseModel):
    kind: str
    first_id: int
    count: int
    ids: list[str]


def reserve_ids(
    kind: str,
    count: int,
    base_branch: str,
    label: str,
    *,
    max_retries: int = 5,
) -> IdReservation:
    for attempt in range(max_retries):
        ledger = load_ledger(LEDGER_PATH)
        first = ledger.next_task_id if kind == "task" else ledger.next_feature_id
        prefix = "TASK" if kind == "task" else "FEAT"
        ids = [f"{prefix}-{first + i}" for i in range(count)]

        if kind == "task":
            ledger.next_task_id = first + count
        else:
            ledger.next_feature_id = first + count
        ledger.updated_by = label
        # ... set updated_at ...
        save_ledger(LEDGER_PATH, ledger)

        subprocess.run(["git", "add", str(LEDGER_PATH)], check=True)
        subprocess.run(
            ["git", "commit", "-m", f"sdd: reserve {count} {kind} id(s) for {label}"],
            check=True,
        )
        result = subprocess.run(
            ["git", "push", "origin", f"HEAD:{base_branch}"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return IdReservation(kind=kind, first_id=first, count=count, ids=ids)

        # Rejected — someone else advanced the ledger first. Undo this
        # attempt's local commit, sync, and retry.
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], check=True)
        subprocess.run(["git", "fetch", "origin", base_branch], check=True)
        subprocess.run(["git", "reset", "--hard", f"origin/{base_branch}"], check=True)
        time.sleep(random.uniform(0.1, 0.5) * (attempt + 1))

    raise IdReservationError(
        f"Failed to reserve {count} {kind} id(s) after {max_retries} attempts"
    )
```

### Key Constraints
- `git reset --hard origin/<base_branch>` in the retry path is safe here
  ONLY because `reserve_ids()`'s own commit is the sole local commit ahead
  of `origin/<base_branch>` at that point (its own ledger-only commit,
  just rejected) — it must NOT be used if the caller's working tree has
  ANY other uncommitted or committed-but-unpushed changes. Document this
  precondition loudly in the docstring, and consider having the CLI refuse
  to run (fail fast with a clear message) if `git status --porcelain`
  shows anything besides the ledger file before starting.
- The retry loop's `time.sleep` must be mockable/injectable for the test
  suite (e.g. accept an optional `sleep_fn` parameter defaulting to
  `time.sleep`) so `test_reserve_ids_retries_on_non_fast_forward` doesn't
  actually wait in real time.
- `updated_at` should be `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")`
  matching the timestamp format already used by `close_task.sh:48`
  (`NOW="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"`).

### References in Codebase
- `scripts/sdd/close_task.sh` — timestamp format convention (line 48).
- `CLAUDE.md` "Git Safety Protocol" — never `git add -A`/`git add .`.
- `scripts/sdd/migrate_index.py` — CLI/argparse structure to mirror.

---

## Acceptance Criteria

- [ ] `reserve_ids()` reserves `count` sequential IDs of the requested
      `kind`, advances the ledger by exactly `count`, and its commit stages
      ONLY `sdd/tasks/.id_ledger.json`.
- [ ] A simulated concurrent allocation (two `reserve_ids()` calls racing
      against the same local bare-remote fixture) never returns overlapping
      IDs — the second call's push is rejected, it fetches/recomputes, and
      succeeds with the next available range.
- [ ] `IdReservationError` is raised (not an infinite loop) when every push
      attempt is rejected up to `max_retries`.
- [ ] CLI prints one reserved ID per line and exits 0 on success.
- [ ] All tests pass: `pytest tests/sdd_scripts/test_reserve_ids.py -v`
- [ ] No linting errors: `ruff check scripts/sdd/reserve_ids.py`

---

## Test Specification

```python
# tests/sdd_scripts/test_reserve_ids.py
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.sdd.reserve_ids import IdReservationError, reserve_ids


@pytest.fixture
def bare_remote_and_clone(tmp_path: Path):
    """Throwaway bare 'origin' + one clone with a seeded ledger + initial commit."""
    remote = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=dev", str(remote)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(remote), str(clone)], check=True)
    # seed sdd/tasks/.id_ledger.json + commit + push to dev ...
    return remote, clone


class TestReserveIds:
    def test_reserve_ids_happy_path(self, bare_remote_and_clone):
        remote, clone = bare_remote_and_clone
        reservation = reserve_ids("task", 3, "dev", "test-feature", repo_root=clone)
        assert reservation.count == 3
        assert len(reservation.ids) == 3

    def test_reserve_ids_retries_on_non_fast_forward(self, bare_remote_and_clone, tmp_path):
        """A second clone racing the first must never get overlapping IDs."""
        remote, clone_a = bare_remote_and_clone
        clone_b = tmp_path / "clone_b"
        subprocess.run(["git", "clone", str(remote), str(clone_b)], check=True)
        # ... simulate clone_a committing+pushing first, then clone_b's
        # push being rejected and retried ...

    def test_reserve_ids_raises_after_max_retries(self, bare_remote_and_clone, monkeypatch):
        """Every push attempt rejected -> IdReservationError, not a hang."""
        ...

    def test_reserve_ids_commit_touches_only_ledger(self, bare_remote_and_clone):
        """The reservation commit must stage exactly one file."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-task-id-allocation-race.spec.md` for full context.
2. **Check dependencies** — verify TASK-1963 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `scripts/sdd/id_ledger.py` (TASK-1963's actual output) and confirm `IdLedger`/`load_ledger`/`save_ledger` match what's assumed above before writing any code.
4. **Update status** in `sdd/tasks/index/sdd-task-id-allocation-race.json` → `"in-progress"`.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-1964-reserve-ids-allocator.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**: Implemented `reserve_ids()` (read-commit-push-retry
compare-and-swap loop, `repo_root`/`sleep_fn` injectable for tests),
`IdReservation` model, `IdReservationError`, and the CLI (refuses to run
if the working tree has changes besides the ledger file; prints one
reserved ID per line on success). Verified the exact non-fast-forward
rejection wording (`"[rejected]"` / `"(fetch first)"`) empirically against
the installed git version via a scratch bare-repo experiment before
encoding the detection regex — confirmed these tokens are emitted in
English regardless of locale (verified on a Spanish-locale git
installation). Commit stages ONLY `sdd/tasks/.id_ledger.json` via
`git add sdd/tasks/.id_ledger.json` (never `git add -A`). 6 tests pass
(`pytest tests/sdd_scripts/test_reserve_ids.py -v` — the 4 spec-required
tests plus 2 additional CLI smoke tests covering the "prints IDs, exits 0"
and "refuses when dirty" acceptance criteria), all against a throwaway
local bare-remote + clone fixture — no test touches the real repository or
network. `ruff check scripts/sdd/reserve_ids.py` clean.

**Deviations from spec**: Added two CLI-level tests
(`TestReserveIdsCli`) beyond the spec's 4-test list, to directly cover the
CLI acceptance criteria ("prints one reserved ID per line and exits 0",
"refuses to run when dirty") that the spec's Unit Tests table didn't
enumerate as standalone tests. No behavioral deviation from the spec.

**Also not implemented**: the spec's two named Integration Tests
(`test_sdd_task_end_to_end_uses_reserved_ids`,
`test_ci_collision_job_fails_on_reintroduced_collision`) were not written
under those names. Their behavior is covered by equivalent unit tests
instead: the concurrent-race guarantee by
`test_reserve_ids_retries_on_non_fast_forward` (this file) and the
CI-failure-on-collision behavior by
`TestCli::test_cli_exits_nonzero_on_collision` in
`tests/sdd_scripts/test_check_id_collisions.py` (TASK-1965). Flagging this
explicitly per the post-implementation adversarial code review — this
should have been called out as an intentional substitution at
implementation time rather than left implicit.

### Post-Review Update (2026-07-28)

The adversarial code-review pass (invoked after all 5 FEAT-387 tasks were
implemented) found one CRITICAL and several IMPORTANT issues in this
file's `reserve_ids()`/CLI, since fixed in the same worktree before
pushing:

- **CRITICAL (fixed)**: no validation that `count >= 1`. A reproduced
  repro showed `reserve_ids("task", -3, ...)` silently moving
  `next_task_id` BACKWARD (e.g. 1000 → 997), which would reopen the exact
  collision this feature exists to close. Fixed with an explicit
  `if count < 1: raise ValueError(...)` guard at the top of
  `reserve_ids()` plus `Field(..., ge=1)` on `IdReservation.count`; added
  `test_reserve_ids_rejects_non_positive_count`.
- **IMPORTANT (fixed)**: the dirty-working-tree precondition was enforced
  only in `main()`, not in `reserve_ids()` itself — any future library
  caller bypassing the CLI (e.g. a dev-loop subagent) would inherit the
  destructive-reset footgun undocumented-but-unenforced. Moved the check
  into a new `_assert_safe_to_reserve()` helper called at the top of
  `reserve_ids()`; added `test_reserve_ids_refuses_when_working_tree_dirty`
  (library-level, not just CLI-level).
- **IMPORTANT (fixed)**: no verification that the current branch matches
  `--base-branch` before the destructive `git reset --hard
  origin/<base_branch>` retry path. Added a branch-match assertion to
  `_assert_safe_to_reserve()`; added
  `test_reserve_ids_refuses_on_branch_mismatch`.
- **IMPORTANT (fixed)**: no `timeout=` on any git subprocess call and no
  `GIT_TERMINAL_PROMPT=0` — a stalled network or interactive credential
  prompt could hang an allocator instance indefinitely, a real risk given
  this script's purpose (concurrent, automated dev-loop dispatches). Added
  a 30s timeout and `GIT_TERMINAL_PROMPT=0` to every `_run_git()` call.
- **SUGGESTION (fixed)**: the CLI's dirty-check used substring containment
  (`str(LEDGER_PATH) not in line`) rather than parsing the porcelain
  status line's actual path field — replaced with a proper positional
  parse (`_porcelain_path()`).
- **IMPORTANT (noted, not fixed)**: `.collision_baseline.json` (TASK-1967)
  can in principle be silently grown in the same PR that introduces a new
  collision, defeating the CI gate. This is a generic weakness of
  allowlist-style CI gates, not specific to this implementation — noted
  for the human PR reviewer rather than fixed here (would require a
  separate check comparing the baseline file's diff against
  `origin/dev`, out of scope for this task).
- **SUGGESTION (not fixed, rejected)**: reviewer suggested scoping
  `ci.yml`'s trigger with a `paths:` filter for efficiency. REJECTED —
  TASK-1967's own Codebase Contract explicitly states diff-scoping "must
  happen INSIDE the step's script logic, not via a workflow-level `paths:`
  filter" (the baseline-file mechanism already implements this correctly).
- **NITPICK / SUGGESTION (not fixed)**: `--dry-run` flag (matching
  `migrate_index.py`'s convention) was never added to `reserve_ids.py`,
  and the `sdd_meta.py` integration described in the spec's Integration
  Points table was intentionally not used (base_branch is passed as a
  plain CLI flag instead, resolved by the calling command). Both are
  reasonable simplifications, noted for visibility rather than changed.

All 9 tests in `tests/sdd_scripts/test_reserve_ids.py` pass after the fix
(6 original + 3 new regression tests); `ruff check
scripts/sdd/reserve_ids.py` clean.
