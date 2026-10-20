# TASK-4561: Ledger snapshot removal guard script

**Feature**: FEAT-712 — Ledger snapshot removal guard
**Spec**: `sdd/specs/ledger-service-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1752eb466e1e`

---

## Context

`sdd/ledger/issues.jsonl` is the committed snapshot of the work ledger. It has
silently lost issues twice — `ccbfef606` (2026-09-21, 26 rows) and `769ca8516`
(2026-10-17, +5/−142 including open issues, among them vulnerability
`issue:44941ecac8cc`). 25 issues stayed lost until a human restored them on
2026-10-19.

FEAT-671 already fixed the exporter: `LedgerService.export_snapshot`
(`service.py:532`) reconciles against the committed file by default
(`reconcile: bool = True`), carrying forward rows it does not know. The
remaining gap is that **no gate** stands between a bad export and `dev`, and a
removal inside a 357-line machine-generated JSONL file is invisible in review.

This task builds the backstop, mirroring the FEAT-387 collision guard that
`CLAUDE.md` already describes as "an independent, read-only backstop wired
into CI".

## Scope

Create `scripts/sdd/check_ledger_snapshot.py`: parse the head and base
snapshots, collect `Ledger-Removal:` override trailers from `base..HEAD`, and
report every `issue_id` whose **base** status is `open` or `claimed` and which
is absent from the head snapshot. Exit 1 on any violation, 0 when clean.

Create `tests/sdd_scripts/test_check_ledger_snapshot.py` covering spec cases
U1–U9 and I1–I5.

**NOT in scope**: wiring the step into `.github/workflows/ci.yml` (TASK-4562);
any change to `parrot.knowledge.wiki.ledger.*`; guarding
`sdd/ledger/events.jsonl`; restoring already-lost issues.

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `scripts/sdd/check_ledger_snapshot.py` | CREATE | The guard; stdlib only |
| `tests/sdd_scripts/test_check_ledger_snapshot.py` | CREATE | U1–U9, I1–I5 |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

Stdlib only — `argparse`, `json`, `subprocess`, `sys`, `dataclasses.dataclass`,
`pathlib.Path`. **No third-party imports, no `parrot.*` imports.** The guard
must run in CI before any workspace package is importable.

Test module imports follow the sibling guards verbatim:

```python
# tests/sdd_scripts/test_check_id_collisions.py:6 (verified)
from scripts.sdd.check_id_collisions import find_collisions, main
```

### Existing Signatures (verified)

```python
# scripts/sdd/check_id_collisions.py:254
def main(argv: list[str] | None = None) -> int: ...
# scripts/sdd/check_id_collisions.py:327
raise SystemExit(main())
# scripts/sdd/check_id_collisions.py:267
parser.add_argument("--index-dir", type=Path, default=Path("sdd/tasks/index"))
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:532
async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool: ...
```
This is the producer whose output the guard asserts. **Do not import it, do not
modify it** — the guard is deliberately independent of the code it protects.

### Snapshot row shape (verified against the live 357-row file)

Keys present on every row: `about`, `acknowledged`, `claimed_by`, `closed_by`,
`closed_reason`, `discovered_from`, `issue_id`, `kind`, `resolved_by`,
`severity`, `status`, `title`. Observed `status` values: `closed` (213),
`open` (134), `claimed` (10). Only `issue_id`, `status` and `title` are read.

### Does NOT Exist (verified absent)

- `scripts/sdd/check_ledger_snapshot.py` — created by this task.
- `tests/sdd_scripts/test_check_ledger_snapshot.py` — created by this task.
- `packages/ai-parrot/tests/sdd/` — **does not exist**; guard tests live in
  `tests/sdd_scripts/` (verified: `test_check_id_collisions.py`,
  `test_check_task_graph.py`, `test_check_task_state.py` are all there).
- There is **no** `wikitoolkit ledger import` subcommand — the flow is
  `export-log` / `import-log` plus `rebuild`. Do not call one.
- No existing CI step reads `sdd/ledger/issues.jsonl` (verified by grep over
  `.github/workflows/*.yml`).
- `LedgerService` has no `verify_snapshot`/`diff_snapshot` helper to reuse.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/check_ledger_snapshot.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_check_ledger_snapshot.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

## Implementation Notes

- Mirror `check_id_collisions.py` exactly in shape: module docstring,
  `main(argv: list[str] | None = None) -> int`, argparse with repo-relative
  defaults, `raise SystemExit(main())` under `if __name__ == "__main__":`.
- Run git through `subprocess.run([...], capture_output=True, text=True)` with
  an **argument list**. Never `shell=True`, never an f-string command.
- Google-style docstrings, strict type hints, 120-column lines, `black`.
- `self.logger` does not apply (module-level script): print to stdout.

## Implementation Blueprint

### `scripts/sdd/check_ledger_snapshot.py` — CREATE

```python
"""Fail CI when a commit removes an open or claimed issue from the ledger snapshot.

``sdd/ledger/issues.jsonl`` has silently lost rows twice (``ccbfef606``,
``769ca8516``). ``LedgerService.export_snapshot`` reconciles since FEAT-671, so
this guard is the independent backstop: it compares the snapshot against a base
ref and fails when a row whose BASE status is open/claimed has disappeared.

A status transition (open -> closed) is normal and passes; only disappearance
is fatal. Removing a ``closed`` row is legal compaction.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROTECTED_STATUSES: frozenset[str] = frozenset({"open", "claimed"})
OVERRIDE_TRAILER: str = "Ledger-Removal"
DEFAULT_SNAPSHOT = Path("sdd/ledger/issues.jsonl")


@dataclass(frozen=True)
class SnapshotRow:
    """One parsed row of the ledger snapshot."""

    issue_id: str
    status: str
    title: str


def load_snapshot(text: str) -> dict[str, SnapshotRow]:
    """Parse JSONL into ``{issue_id: SnapshotRow}``, skipping blank lines.

    Raises:
        ValueError: If a non-blank line is not a JSON object with an ``issue_id``.
    """
    rows: dict[str, SnapshotRow] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        # FILL IN: parse one line — bounded by AC9 (a malformed line must raise
        # ValueError naming `number`, never be skipped silently).
    return rows


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a git command with an argument list and captured text output."""
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def read_base_snapshot(base_ref: str, path: Path) -> str | None:
    """Return the snapshot text at ``base_ref``, or None when the file is absent there.

    Raises:
        RuntimeError: If ``base_ref`` itself cannot be resolved (a fetch problem
            must fail the gate, not silently pass it — see AC10 / spec §7).
    """
    # FILL IN: distinguish "ref missing" from "path missing at that ref" —
    # bounded by spec §7: `git rev-parse --verify <base_ref>` failing is a
    # RuntimeError; `git show <ref>:<path>` failing after that means a new file
    # and returns None.


def allowed_removals(base_ref: str) -> set[str]:
    """Collect issue ids from ``Ledger-Removal:`` trailers in ``base_ref..HEAD``."""
    result = _git(["log", f"{base_ref}..HEAD", "--format=%B"])
    allowed: set[str] = set()
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith(f"{OVERRIDE_TRAILER.lower()}:"):
            continue
        # FILL IN: take everything after the first ':' and split on whitespace
        # and commas — bounded by AC5 (one trailer may authorize several ids,
        # and ONLY the ids it names).
    return allowed


def find_violations(
    base: dict[str, SnapshotRow],
    head: dict[str, SnapshotRow],
    allowed: set[str],
) -> list[SnapshotRow]:
    """Return base rows that are protected, absent from head, and not overridden."""
    return [
        row
        for issue_id, row in sorted(base.items())
        if row.status in PROTECTED_STATUSES and issue_id not in head and issue_id not in allowed
    ]


def main(argv: list[str] | None = None) -> int:
    """Exit 0 when clean, 1 when a protected row was removed or input is unusable."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--base-ref", default="origin/dev")
    parser.add_argument("--allow", action="append", default=[])
    args = parser.parse_args(argv)
    # FILL IN: read head (missing/unreadable/malformed -> print and return 1,
    # per AC9); read base (None -> print "no base snapshot" and return 0, per
    # the spec's Module 1 fail-closed note); union --allow with
    # allowed_removals(); report every violation as
    # "issue:<id>  [<status>]  <title>" plus the override hint; return 1 if any.


if __name__ == "__main__":
    raise SystemExit(main())
```

**Why this shape**: `find_violations` is a pure function over two dicts so
U1–U8 test it without git; `read_base_snapshot` and `allowed_removals` isolate
every subprocess call so the integration tests exercise them through a real
`tmp_path` repo. `PROTECTED_STATUSES` is a module constant because AC3/AC4
depend on exactly which statuses are guarded. **Must NOT change**: the
`main(argv) -> int` + `SystemExit(main())` shape, or CI invocation breaks.

### `tests/sdd_scripts/test_check_ledger_snapshot.py` — CREATE

```python
"""Tests for the ledger snapshot removal guard."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.sdd.check_ledger_snapshot import (
    SnapshotRow,
    find_violations,
    load_snapshot,
    main,
)


def _jsonl(*rows: dict) -> str:
    """Render rows as the snapshot's JSONL form (sorted keys, one object per line)."""
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _row(issue_id: str, status: str, title: str = "t") -> dict:
    return {"issue_id": issue_id, "status": status, "title": title}


class TestFindViolations:
    # FILL IN: U1-U8 — bounded by spec §4: open removed and claimed removed are
    # violations; closed removed and open->closed are not; an id in `allowed` is
    # not; several removals are ALL returned (AC6).
    ...


class TestLoadSnapshot:
    # FILL IN: U8/U9 — blank lines ignored; a malformed line raises ValueError
    # naming the 1-based line number.
    ...


class TestMainInGitRepo:
    # FILL IN: I1-I4 — build a tmp_path git repo (git init; git config
    # user.email/user.name LOCALLY, never --global; commit a base snapshot;
    # commit a head snapshot) and assert main([...]) return codes. I3 adds a
    # "Ledger-Removal: issue:x" trailer to the removing commit's message.
    ...


def test_real_repo_snapshot_is_clean() -> None:
    """I5 / AC8: today's snapshot vs origin/dev must pass."""
    # FILL IN: skip when `git rev-parse --verify origin/dev` fails (shallow or
    # detached CI clone) — bounded by AC8; otherwise assert main([]) == 0.
```

**Why**: pure-function tests cover the decision table cheaply; the git-repo
tests are the only ones that can prove the trailer override and the base-ref
read. `git config` is set **locally** so a developer's global identity is never
touched.

### Steps (in order)

1. Write `scripts/sdd/check_ledger_snapshot.py` from the block above, filling
   each `FILL IN` — do this first because the tests import its symbols.
2. Write the test module and complete its stubs.
3. `ruff check --fix` both files — the lint gate rejects a banned import, and
   the guard must stay stdlib-only.
4. Run the validation commands below; confirm I5 passes against the real
   snapshot (AC8) rather than skipping.

### FILL IN checklist

- [ ] `load_snapshot` raises `ValueError` naming the 1-based line number (AC9)
- [ ] `read_base_snapshot` raises on an unresolvable ref, returns None only for
      a genuinely absent path (AC10, spec §7 depth-1 risk)
- [ ] `allowed_removals` authorizes only the ids its trailer names (AC5)
- [ ] `main` returns 1 on a missing/malformed head snapshot (AC9)
- [ ] `main` reports every violation with id, base status and title (AC6)
- [ ] Tests cover U1–U9 and I1–I5

## Acceptance Criteria

Implements spec AC1–AC9. AC10 is completed by TASK-4562.

- [ ] AC1/AC2: removing an `open` or `claimed` row makes `main()` return 1
- [ ] AC3: removing a `closed` row returns 0
- [ ] AC4: an `open` → `closed` transition returns 0
- [ ] AC5: a `Ledger-Removal: issue:<id>` trailer permits exactly that id
- [ ] AC6: all violations reported in one run, each with id, status, title
- [ ] AC7: the guard writes no file and imports no `parrot.*`
- [ ] AC8: run against today's `dev`, the guard exits 0
- [ ] AC9: a missing or malformed head snapshot exits 1

## Validation Commands

- `pytest tests/sdd_scripts/test_check_ledger_snapshot.py -q`

Non-pytest gates (run as steps 3 and 4 above, deliberately NOT selector operands):
`ruff check scripts/sdd/check_ledger_snapshot.py tests/sdd_scripts/test_check_ledger_snapshot.py`
and the guard's own self-run `python -m scripts.sdd.check_ledger_snapshot --base-ref origin/dev`,
which must exit 0 (AC8).

## Test Specification

See spec §4 (U1–U9, I1–I5). Every test runs offline against `tmp_path`; the
single real-repo test (I5) skips when `origin/dev` is unavailable.

## Agent Instructions

Do not modify `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`.
The guard's independence from the exporter is the point of the feature — a
guard that imports what it checks cannot catch the exporter running old code,
which is the most likely cause of the 2026-10-17 loss.

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
