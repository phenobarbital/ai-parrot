# TASK-1963: `IdLedger` model + `sdd/tasks/.id_ledger.json` bootstrap

**Feature**: FEAT-387 — SDD Task-ID Allocation Race Fix
**Spec**: `sdd/specs/sdd-task-id-allocation-race.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`/sdd-task` and `/sdd-spec` currently assign `TASK-<NNN>`/`FEAT-<NNN>` numbers
by scanning existing files for the highest number in use and incrementing —
no lock, no reservation, no re-check against `origin/dev` immediately before
committing (spec §1 Problem Statement). This produced six silent numeric
collisions between FEAT-380 (sandbox-hardening) and two unrelated features
(`eventbus-replacement-evaluation`, `fix-msword-loader-none-*`) because
colliding task files have different paths and git's merge machinery never
flags the collision.

This task implements Module 1 of the spec: the data model and bootstrap for
a tiny, git-tracked "next ID" ledger file that the allocator (TASK-1964) will
use as a compare-and-swap counter. This task does NOT implement the
allocator itself — only the model, the load/save helpers, and the one-time
bootstrap that seeds the ledger strictly ahead of every ID currently in use.

---

## Scope

- Implement `IdLedger` (Pydantic model) with fields `next_task_id: int`,
  `next_feature_id: int`, `updated_at: str`, `updated_by: str` (spec §2 Data
  Models).
- Implement `load_ledger(path: Path) -> IdLedger` and
  `save_ledger(path: Path, ledger: IdLedger) -> None`, writing
  byte-stable JSON (`json.dumps(..., indent=2, sort_keys=False)` + trailing
  newline, matching `migrate_index.py`'s own output convention).
- Implement `bootstrap_ledger() -> IdLedger`: scans
  `sdd/tasks/index/*.json` (all `id`/`feature_id` fields) AND
  `sdd/specs/*.md` (the `**Feature ID**: FEAT-<NNN>` header line) for the
  current maximum `TASK-<NNN>` and `FEAT-<NNN>` respectively, and returns an
  `IdLedger` with `next_task_id`/`next_feature_id` set to `max + 1`.
- Add a CLI (`python -m scripts.sdd.id_ledger bootstrap`) that runs
  `bootstrap_ledger()` and writes the result to
  `sdd/tasks/.id_ledger.json` — this task's own execution IS the one-time
  bootstrap; run it and commit the resulting file as part of this task's
  deliverable.
- Write unit tests per the spec's Test Specification: ledger bootstrap
  seeds ahead of existing IDs, and roundtrip stability.

**NOT in scope**:
- The compare-and-swap allocator itself (reserve/commit/push/retry) — that
  is TASK-1964.
- The collision scanner — that is TASK-1965.
- Wiring `/sdd-task`/`/sdd-spec` to use any of this — that is TASK-1966.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/id_ledger.py` | CREATE | `IdLedger` Pydantic model, `load_ledger`/`save_ledger`, `bootstrap_ledger`, CLI entrypoint |
| `sdd/tasks/.id_ledger.json` | CREATE | The bootstrapped ledger file itself (run the CLI, commit its output) |
| `tests/sdd_scripts/test_id_ledger.py` | CREATE | Unit tests for the model, load/save, and bootstrap |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-28.

### Verified Imports
```python
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field  # verified: scripts/sdd/sdd_meta.py:19 uses `from pydantic import BaseModel, model_validator` — same package, same import style
```

### Existing Signatures to Use
```python
# scripts/sdd/migrate_index.py (pattern to mirror for CLI structure)
def main(argv: list[str] | None = None) -> int:  # line 62
    parser = argparse.ArgumentParser(...)
    ...
    args = parser.parse_args(argv)
    return migrate(args.source, args.dest, args.dry_run)

if __name__ == "__main__":  # line 75
    raise SystemExit(main())

# scripts/sdd/sdd_meta.py (pattern to mirror for Pydantic model style)
class FlowMeta(BaseModel):  # line 29
    type: Literal["feature", "hotfix"]
    base_branch: str
```

**Per-spec index schema** (`sdd/tasks/index/<feature>.json`, confirmed via
`sdd/tasks/index/sandbox-hardening.json` header and
`.claude/commands/sdd-task.md:117-146`): top-level `feature_id` field is a
string like `"FEAT-380"`; each entry in `tasks[]` has a string `id` field
like `"TASK-1939"`. Both need `int(s.split("-")[1])` extraction for the
bootstrap's max-scan.

**Spec header line format** (confirmed via
`sdd/specs/sdd-task-id-allocation-race.spec.md:11` and every other spec in
`sdd/specs/`): `**Feature ID**: FEAT-<NNN>` — a single line, always present,
always this exact label.

### Does NOT Exist
- ~~`sdd/tasks/.index.json` as a live counter source~~ — this is the legacy
  monolith, preserved as a historical artifact and ignored by all FEAT-145
  commands (`CLAUDE.md`, "Migration history"). Do NOT read it for the
  bootstrap scan; use `sdd/tasks/index/*.json` (the per-spec files) instead.
- ~~`scripts/sdd/reserve_ids.py`~~ — does not exist yet; created by
  TASK-1964, which imports `IdLedger`/`load_ledger`/`save_ledger` from this
  task's module.
- ~~A `next_id()` method on `IdLedger` itself~~ — keep the model a pure data
  container (Pydantic `BaseModel` with just the four fields); the
  allocation/increment logic belongs in TASK-1964's `reserve_ids.py`, not in
  this module, to keep Module 1 and Module 2 independently testable per the
  spec's Module Breakdown.

---

## Implementation Notes

### Pattern to Follow
```python
# scripts/sdd/id_ledger.py — sketch, mirrors migrate_index.py's structure
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field


class IdLedger(BaseModel):
    next_task_id: int = Field(..., ge=1)
    next_feature_id: int = Field(..., ge=1)
    updated_at: str
    updated_by: str


def load_ledger(path: Path) -> IdLedger:
    return IdLedger.model_validate_json(path.read_text(encoding="utf-8"))


def save_ledger(path: Path, ledger: IdLedger) -> None:
    path.write_text(
        json.dumps(ledger.model_dump(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def bootstrap_ledger(
    index_dir: Path = Path("sdd/tasks/index"),
    specs_dir: Path = Path("sdd/specs"),
) -> IdLedger:
    ...
```

### Key Constraints
- Byte-stable JSON output (matches `migrate_index.py`'s own convention,
  referenced in its docstring: "idempotent — re-running on the same input
  produces byte-equivalent output").
- The bootstrap must take the max across BOTH `sdd/tasks/index/*.json` and
  `sdd/specs/*.md` — a spec could exist with no tasks generated yet (a
  higher `FEAT-<NNN>` with zero entries in `sdd/tasks/index/`), and a task
  index could theoretically reference a `TASK-<NNN>` higher than any spec's
  `FEAT-<NNN>` (unrelated counters, scanned independently).
- `_orphans.json` under `sdd/tasks/index/` (produced by `migrate_index.py`)
  should be included in the `TASK-<NNN>` scan (it has real task entries with
  real IDs) but has no `feature_id` header worth scanning for the FEAT
  counter — confirm by reading `sdd/tasks/index/_orphans.json` before
  writing the scan logic, since its header shape may differ from a normal
  per-spec index.
- Use `glob("*.json")` and skip `_orphans.json` for the FEAT-ID scan only if
  it lacks a `feature_id` header (matches how `.claude/commands/sdd-start.md`'s
  own feature-resolution glob already excludes `_orphans.json` from feature
  matching — same exclusion rule, applied here to header-driven scans).

### References in Codebase
- `scripts/sdd/migrate_index.py` — CLI structure, docstring conventions,
  byte-stable JSON writing pattern.
- `scripts/sdd/sdd_meta.py` — Pydantic model style for small, focused SDD
  tooling data models.
- `sdd/tasks/index/sandbox-hardening.json` — real example of the per-spec
  index schema this task's scanner reads.

---

## Acceptance Criteria

- [ ] `IdLedger` model defined with the four fields per spec §2.
- [ ] `load_ledger`/`save_ledger` round-trip byte-stably.
- [ ] `bootstrap_ledger()` scans `sdd/tasks/index/*.json` + `sdd/specs/*.md`
      and returns `next_task_id`/`next_feature_id` strictly greater than
      every ID currently in use (verify against the real `dev` tree: as of
      this task's creation, max `TASK-<NNN>` is 1962 and max `FEAT-<NNN>` is
      387 — expect `next_task_id >= 1963`, `next_feature_id >= 388`, though
      by the time this task runs those maxima may have moved further; the
      test must compute its OWN expected floor from the live tree, not
      hardcode these numbers).
- [ ] `sdd/tasks/.id_ledger.json` is committed, containing the bootstrap's
      output.
- [ ] All tests pass: `pytest tests/sdd_scripts/test_id_ledger.py -v`
- [ ] No linting errors: `ruff check scripts/sdd/id_ledger.py`

---

## Test Specification

```python
# tests/sdd_scripts/test_id_ledger.py
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdd.id_ledger import IdLedger, bootstrap_ledger, load_ledger, save_ledger


class TestIdLedgerModel:
    def test_ledger_roundtrip(self, tmp_path: Path) -> None:
        """save_ledger -> load_ledger is byte-for-byte stable."""
        ledger = IdLedger(
            next_task_id=2000, next_feature_id=400,
            updated_at="2026-07-28T00:00:00+00:00", updated_by="test",
        )
        path = tmp_path / "ledger.json"
        save_ledger(path, ledger)
        first_bytes = path.read_bytes()
        save_ledger(path, load_ledger(path))
        assert path.read_bytes() == first_bytes

    def test_ledger_rejects_non_positive_ids(self) -> None:
        with pytest.raises(Exception):
            IdLedger(next_task_id=0, next_feature_id=1, updated_at="x", updated_by="x")


class TestBootstrap:
    def test_bootstrap_seeds_ahead_of_existing_ids(self, tmp_path: Path) -> None:
        """Bootstrapping on a fixture repo with known max IDs seeds strictly ahead."""
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        specs_dir = tmp_path / "sdd" / "specs"
        index_dir.mkdir(parents=True)
        specs_dir.mkdir(parents=True)
        (index_dir / "example.json").write_text(
            '{"feature_id": "FEAT-042", "tasks": [{"id": "TASK-100"}, {"id": "TASK-101"}]}'
        )
        (specs_dir / "example.spec.md").write_text("**Feature ID**: FEAT-042\n")
        ledger = bootstrap_ledger(index_dir=index_dir, specs_dir=specs_dir)
        assert ledger.next_task_id >= 102
        assert ledger.next_feature_id >= 43
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-task-id-allocation-race.spec.md` for full context.
2. **Check dependencies** — none for this task.
3. **Verify the Codebase Contract** — confirm the imports/signatures above still match `dev` HEAD before editing.
4. **Update status** in `sdd/tasks/index/sdd-task-id-allocation-race.json` → `"in-progress"`.
5. **Implement** following the scope, codebase contract, and notes above. Run the bootstrap CLI and commit its output as part of this task.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-1963-id-ledger-model-bootstrap.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**: Implemented `IdLedger` (Pydantic model, 4 fields), `load_ledger`/
`save_ledger` (byte-stable JSON via `json.dumps(..., indent=2,
sort_keys=False)` + trailing newline, matching `migrate_index.py`), and
`bootstrap_ledger()` scanning `sdd/tasks/index/*.json` (including
`_orphans.json` for the TASK counter, excluded from the FEAT-header scan)
plus `sdd/specs/*.md` for the `**Feature ID**` header. Ran the CLI
(`python -m scripts.sdd.id_ledger bootstrap`) and committed the resulting
`sdd/tasks/.id_ledger.json` (`next_task_id=1968`, `next_feature_id=388` —
strictly ahead of the live max of TASK-1967/FEAT-387). 5 unit tests pass
(`pytest tests/sdd_scripts/test_id_ledger.py -v`), `ruff check
scripts/sdd/id_ledger.py` clean.

**Deviations from spec**: none
