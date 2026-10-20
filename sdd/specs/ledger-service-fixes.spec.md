---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, ci]
tags: [ledger, ci, snapshot, data-loss, guard]
---

# Feature Specification: Ledger snapshot removal guard

**Feature ID**: FEAT-712
**Date**: 2026-10-21
**Author**: Jesus
**Status**: approved
**Target version**: 0.29.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`sdd/ledger/issues.jsonl` is the committed snapshot of the work ledger. It has
silently lost issues at least twice:

| Commit | When | Damage |
|---|---|---|
| `ccbfef606` (`/sdd-done FEAT-586`) | 2026-09-21 | 26 rows removed |
| `769ca8516` (FEAT-696 snapshot) | 2026-10-17 | +5 / −142, including **open** issues |

FEAT-671 made `LedgerService.export_snapshot` reconcile against the committed
snapshot (`reconcile=True`), carrying forward rows whose `issue_id` the exporting
machine has never seen. The 2026-10-17 export therefore most likely ran either
with pre-FEAT-671 code or with the destructive `--no-reconcile` opt-out.

Nothing caught either event. **25 issues (14 open, including vulnerability
`issue:44941ecac8cc`) stayed lost until a human restored them on 2026-10-19.**

The gap is not in `export_snapshot` — that is already fixed. The gap is that no
gate stands between a bad export and `dev`. Review cannot be that gate: the
removals appear as deletions inside a 357-line machine-generated JSONL file in a
diff nobody reads line by line.

Resolves `issue:1752eb466e1e` (`feature_gap`, `major`, discovered from
`spec:FEAT-694`).

### Goals

- Fail CI on any commit that removes a row from `sdd/ledger/issues.jsonl` whose
  **base-ref** status is `open` or `claimed`.
- Provide an explicit, auditable override for intentional removals.
- Report every offending `issue_id` in one run — never stop at the first.
- Keep the check read-only, dependency-free, and runnable locally with the same
  command CI uses.

### Non-Goals (explicitly out of scope)

- Changing `export_snapshot` or any ledger runtime code — FEAT-671 already fixed
  the exporter; this feature only adds the backstop.
- Guarding `sdd/ledger/events.jsonl` (append-only, rotated by `/sdd-done`).
- Blocking a **status transition** (`open` → `closed`) — that is normal traffic.
  Only *disappearance* of a row is fatal.
- Restoring already-lost issues (done by hand on 2026-10-19).
- Reconciling snapshots across machines — that is FEAT-694's shared event log.

---

## 2. Architectural Design

### Overview

A read-only Python guard, `scripts/sdd/check_ledger_snapshot.py`, diffs the
working-tree snapshot against the same file at a base ref and fails when an
`issue_id` whose **base** row is `open` or `claimed` is absent from the head
snapshot. It mirrors `check_id_collisions.py` and `check_task_state.py`: a
`main(argv) -> int` entry point, `argparse` flags with repo-relative defaults,
`raise SystemExit(main())`, and a CI step in the existing `lint-and-registry`
job.

### Component Diagram

```
.github/workflows/ci.yml (lint-and-registry)
        │  fetch base branch (depth-1 checkout cannot see it)
        ▼
scripts/sdd/check_ledger_snapshot.py
        │
        ├──→ git show <base-ref>:sdd/ledger/issues.jsonl   (base rows)
        ├──→ sdd/ledger/issues.jsonl                        (head rows)
        └──→ git log <base-ref>..HEAD --format=%B           (override trailers)
                 │
                 ▼
         exit 0 (clean) | exit 1 (removals, each issue_id listed)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `.github/workflows/ci.yml` → `lint-and-registry` | adds a step | Same job as the FEAT-387 collision guard |
| `scripts/sdd/check_id_collisions.py` | pattern source | `main(argv) -> int`, argparse, `SystemExit` |
| `LedgerService.export_snapshot` | **read-only contract** | Guard asserts its output; never imports it |
| `/sdd-done` step 9.1 | producer | Writes the snapshot this guard protects |

### Data Models

No new persisted models. One in-memory record per snapshot row:

```python
@dataclass(frozen=True)
class SnapshotRow:
    """One parsed row of sdd/ledger/issues.jsonl."""

    issue_id: str
    status: str
    title: str
```

### New Public Interfaces

```python
# scripts/sdd/check_ledger_snapshot.py

PROTECTED_STATUSES: frozenset[str] = frozenset({"open", "claimed"})
OVERRIDE_TRAILER: str = "Ledger-Removal"

def load_snapshot(text: str) -> dict[str, SnapshotRow]:
    """Parse JSONL into {issue_id: SnapshotRow}, ignoring blank lines."""

def read_base_snapshot(base_ref: str, path: Path) -> str | None:
    """Return the snapshot at ``base_ref`` via ``git show``; None when absent there."""

def allowed_removals(base_ref: str) -> set[str]:
    """Collect issue ids from ``Ledger-Removal:`` trailers in base_ref..HEAD."""

def find_violations(
    base: dict[str, SnapshotRow],
    head: dict[str, SnapshotRow],
    allowed: set[str],
) -> list[SnapshotRow]:
    """Base rows that are open/claimed, absent from head, and not overridden."""

def main(argv: list[str] | None = None) -> int:
    """Exit 0 when clean, 1 when any protected row was removed."""
```

---

## 3. Module Breakdown

### Module 1: Snapshot guard script

`scripts/sdd/check_ledger_snapshot.py` — parsing, base-ref read, override
collection, violation detection, human-readable report. Stdlib only
(`argparse`, `json`, `subprocess`, `dataclasses`, `pathlib`).

Flags (all with working defaults):

| Flag | Default | Purpose |
|---|---|---|
| `--snapshot` | `sdd/ledger/issues.jsonl` | Head snapshot path |
| `--base-ref` | `origin/dev` | Ref to compare against |
| `--allow` | *(repeatable)* | Explicit `issue_id` override |

Failure output lists every violation as
`issue:<id>  [<base status>]  <title>`, then prints how to override.

**Fail-closed detail**: a head snapshot that is missing, unreadable, or contains
a malformed JSON line is an error (exit 1), not a silent pass. A base snapshot
that does not exist at `--base-ref` (the file is new) is a clean pass — there is
nothing to remove.

### Module 2: CI wiring

A `lint-and-registry` step running the guard. Because `actions/checkout@v6`
defaults to a depth-1 checkout, the step first fetches the base branch
(`git fetch --depth=1 origin <base>`); `--base-ref` is then
`origin/${{ github.base_ref || 'dev' }}` so the check works on both PR and push
events.

### Module 3: Tests

`packages/ai-parrot/tests/sdd/test_check_ledger_snapshot.py` — pure-function
tests over `load_snapshot` / `find_violations`, plus end-to-end `main()` runs in
a `tmp_path` git repo built by a fixture.

---

## 4. Test Specification

### Unit Tests

| # | Case | Expected |
|---|---|---|
| U1 | Row `open` in base, absent in head | violation |
| U2 | Row `claimed` in base, absent in head | violation |
| U3 | Row `closed` in base, absent in head | **no** violation (compaction is legal) |
| U4 | Row `open` in base, `closed` in head | **no** violation (normal transition) |
| U5 | Row `open` in base, absent in head, id in `allowed` | **no** violation |
| U6 | Rows added only | no violation |
| U7 | Several protected removals | **all** reported, not just the first |
| U8 | Blank lines / trailing newline in JSONL | parsed, ignored |
| U9 | Malformed JSON line in head | exit 1 with the line number |

### Integration Tests

| # | Case | Expected |
|---|---|---|
| I1 | `main()` in a tmp git repo, clean commit | returns 0 |
| I2 | `main()` after a commit deleting an open row | returns 1, id in stdout |
| I3 | Same as I2 with a `Ledger-Removal: issue:<id>` trailer | returns 0 |
| I4 | Snapshot absent at base ref | returns 0 |
| I5 | Real repo snapshot vs `origin/dev` | returns 0 (no regression today) |

### Validation Contract

```bash
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_check_ledger_snapshot.py -q
ruff check scripts/sdd/check_ledger_snapshot.py
python -m scripts.sdd.check_ledger_snapshot --base-ref origin/dev
```

### Test Data / Fixtures

A `tmp_path` git repo fixture (`git init`, `user.email`/`user.name` set locally,
two commits) writing three-row JSONL snapshots inline. No network, no real
ledger, no `.parrot/` access.

---

## 5. Acceptance Criteria

- **AC1** — A commit removing an `open` row from the snapshot fails CI.
- **AC2** — A commit removing a `claimed` row fails CI.
- **AC3** — Removing a `closed` row passes (compaction stays legal).
- **AC4** — An `open` → `closed` transition passes.
- **AC5** — A `Ledger-Removal: issue:<id>` commit trailer in `base..HEAD`
  permits exactly that id and no other.
- **AC6** — Every violation in one run is reported, each with id, base status
  and title.
- **AC7** — The guard never writes any file and never imports `parrot.*`.
- **AC8** — Run against today's `dev`, the guard exits 0.
- **AC9** — A missing or malformed head snapshot exits 1 (fail closed).
- **AC10** — The guard runs in `lint-and-registry` and works on a depth-1
  checkout.

---

## 6. Codebase Contract

### Verified Imports

Stdlib only: `argparse`, `json`, `subprocess`, `sys`, `dataclasses.dataclass`,
`pathlib.Path`. No third-party, no `parrot.*`.

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:532
async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool: ...

# scripts/sdd/check_id_collisions.py:254  — the pattern this guard mirrors
def main(argv: list[str] | None = None) -> int: ...
# scripts/sdd/check_id_collisions.py:327
raise SystemExit(main())
```

### Integration Points

- `.github/workflows/ci.yml:10` — `lint-and-registry` job.
- `.github/workflows/ci.yml:94-97` — the FEAT-387 collision step to copy.
- `.github/workflows/ci.yml:104-107` — the task-state step to copy.

### Snapshot row shape (verified against the live file, 357 rows)

Keys: `about`, `acknowledged`, `claimed_by`, `closed_by`, `closed_reason`,
`discovered_from`, `issue_id`, `kind`, `resolved_by`, `severity`, `status`,
`title`. Observed `status` values today: `closed` (213), `open` (134),
`claimed` (10).

### Does NOT Exist (Anti-Hallucination)

- `scripts/sdd/check_ledger_snapshot.py` — created by this feature.
- `packages/ai-parrot/tests/sdd/test_check_ledger_snapshot.py` — created here.
- There is **no** `wikitoolkit ledger import` subcommand; the flow is
  `export-log` / `import-log` plus `rebuild`.
- There is no existing CI step that reads `sdd/ledger/issues.jsonl`.

### Edit Sites (Blueprint Anchors)

| File | Anchor | Action |
|---|---|---|
| `.github/workflows/ci.yml` | `- name: Check stalled SDD task files` | insert the new step after this block |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `check_id_collisions.py`: module docstring, `main(argv) -> int`,
  `raise SystemExit(main())`, repo-relative defaults, no side effects.
- Google-style docstrings, strict type hints, 120-column lines, `black`.
- Run `git` through `subprocess.run([...], capture_output=True, text=True)` with
  an argument list — never `shell=True`, never an f-string command.

### Known Risks / Gotchas

- **Depth-1 checkout**: `actions/checkout@v6` fetches one commit; the base ref
  must be fetched explicitly or `git show` fails. Treat a `git show` failure as
  "no base snapshot" **only** when the path is genuinely absent — a fetch
  failure must not silently pass the gate.
- **Trailer scope**: collect trailers from `base..HEAD` only, so an override
  from an unrelated older commit cannot authorize a removal.
- `sdd/` edits are auto-committed by a repo hook; stage explicit paths and never
  `git add .` (other sessions' files land otherwise).
- The `.gitignore` `templates/` rule is unrelated here but `.github/workflows/*`
  pushes need the SSH remote (the `gh` token lacks `workflow` scope).

### External Dependencies

None.

---

## 8. Open Questions

- [ ] Should the guard also run on `push` to `dev` (post-merge detection), or
      only on PRs? Current plan: both, via `github.base_ref || 'dev'`.
- [ ] Should a removal of a `closed` row that is still referenced by an open
      issue's `discovered_from` warn? Deferred — out of scope for the data-loss
      gate.

---

## 9. Design Research Cross-Check

The two documented losses were diagnosed in `issue:1752eb466e1e` itself and
re-verified here: `export_snapshot` already reconciles (FEAT-671,
`service.py:532`, `reconcile: bool = True`), so the exporter is not the
remaining defect — the absent gate is. `check_id_collisions.py` (FEAT-387) is
the precedent for "an independent, read-only backstop wired into CI" and is
cited as such in `CLAUDE.md`.

---

## Revision History

| Version | Date | Author | Changes |
|---|---|---|---|
| 0.1 | 2026-10-21 | Jesus | Initial spec from `issue:1752eb466e1e` via `/sdd-fix` |
