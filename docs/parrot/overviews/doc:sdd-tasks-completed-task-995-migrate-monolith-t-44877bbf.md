---
type: Wiki Overview
title: 'TASK-995: One-shot migration `monolith → per-spec` index'
id: doc:sdd-tasks-completed-task-995-migrate-monolith-to-per-spec-index-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of FEAT-145. Splits the existing
---

# TASK-995: One-shot migration `monolith → per-spec` index

**Feature**: FEAT-145 — SDD Flow Types and Per-Spec Index
**Spec**: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-994
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of FEAT-145. Splits the existing
`sdd/tasks/.index.json` (~15.850 lines, 862 tasks, 44 historic features)
into per-spec index files at `sdd/tasks/index/<feature-slug>.json`.
History must be preserved as a knowledge base (user requirement). The
script does NOT delete the source — that is a manual final step after
the team verifies the migration.

After this task ships, the implementer is expected to RUN the migration
once on the live `sdd/tasks/.index.json` so subsequent tasks (998–1002)
have a real per-spec index to work against.

---

## Scope

- Create `scripts/sdd/migrate_index.py`, executable as
  `python -m scripts.sdd.migrate_index [--source PATH] [--dest DIR] [--dry-run]`.
- Group tasks by `feature` slug (NOT `feature_id` — see Known Risk §1
  in the spec: FEAT-142 collision means slug is the disambiguator).
- For each group, write `<dest>/<feature>.json` containing:
  `feature`, `feature_id`, `spec`, `type` (default `"feature"`),
  `base_branch` (default `"dev"`), `created_at`, `completed_at` (set if
  every task has `status == "done"`, otherwise `null`), and the full
  `tasks` array.
- Handle the `previous_features` registry: each entry there becomes its
  own per-spec index file with whatever tasks in `tasks[]` match its
  feature slug.
- Tasks with no resolvable `feature` (or `feature_id`) go into
  `<dest>/_orphans.json` with `feature: "_orphans"`, `feature_id: null`,
  `spec: null`, defaults for `type`/`base_branch`. Print a stderr
  warning per orphan: `WARN: TASK-NNN has no feature; routed to _orphans.json`.
- Idempotent: running twice on the same input must produce byte-equivalent output.
- Do NOT delete or modify `sdd/tasks/.index.json`.
- Create `tests/scripts/test_migrate_index.py` with the unit tests listed in the spec §4.

**NOT in scope**:
- Rewriting any SDD command to read per-spec indexes (TASK-998, 1000, 1001).
- Removing the source monolith (separate manual commit after team review).
- Migrating tasks across `sdd/tasks/active/` ↔ `sdd/tasks/completed/` (file locations are unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/migrate_index.py` | CREATE | Migration script |
| `tests/scripts/test_migrate_index.py` | CREATE | Unit tests with synthetic monolith fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import argparse                         # stdlib
import json                             # stdlib
import sys                              # stdlib
from pathlib import Path                # stdlib
from datetime import datetime, timezone # stdlib
from collections import defaultdict     # stdlib
from scripts.sdd.sdd_meta import FlowMeta  # from TASK-994
```

### Existing Schema (verified by `jq` on 2026-05-05)

The monolith has top-level keys: `created_at`, `feature`, `feature_id`,
`previous_features`, `spec`, `tasks`. The current top-level points to
the most recently scaffolded feature (currently `FEAT-143
flows-consolidation`); 44 entries live in `previous_features`; 862
entries live in `tasks[]`. Each task entry has at minimum:
`id`, `slug`, `title`, `feature_id`, `feature`, `spec`, `status`,
`priority`, `effort`, `depends_on`, `parallel`, `parallelism_notes`,
`assigned_to`, `started_at`, `file`. Some legacy entries may be missing
optional fields — the script must tolerate that.

### Does NOT Exist

- ~~`sdd/tasks/index/`~~ — directory does not exist; create it.
- ~~Any existing per-spec index file~~ — TASK-994 only created the parser, no indexes yet.
- ~~`scripts/sdd/migrate_index.py`~~ — created by this task.
- ~~`tests/scripts/test_migrate_index.py`~~ — created by this task.

---

## Implementation Notes

### Algorithm

```python
def migrate(source: Path, dest: Path, dry_run: bool = False) -> int:
    raw = json.loads(source.read_text())
    # 1. Build feature → metadata map
    feat_meta: dict[str, dict] = {}
    feat_meta[raw["feature"]] = {
        "feature": raw["feature"],
        "feature_id": raw.get("feature_id"),
        "spec": raw.get("spec"),
        "created_at": raw.get("created_at"),
    }
    for prev in raw.get("previous_features", []):
        feat_meta[prev["feature"]] = {
            "feature": prev["feature"],
            "feature_id": prev.get("feature_id"),
            "spec": prev.get("spec"),
            "created_at": prev.get("created_at"),
        }
    # 2. Group tasks by feature slug
    grouped = defaultdict(list)
    orphans: list[dict] = []
    for task in raw.get("tasks", []):
        slug = task.get("feature")
        if not slug:
            orphans.append(task)
            continue
        grouped[slug].append(task)
    # 3. Emit one file per group
    dest.mkdir(parents=True, exist_ok=True)
    for slug, tasks in sorted(grouped.items()):
        meta = feat_meta.get(slug, {
            "feature": slug,
            "feature_id": tasks[0].get("feature_id"),
            "spec": tasks[0].get("spec"),
            "created_at": None,
        })
        completed_at = (
            datetime.now(timezone.utc).isoformat()
            if all(t.get("status") == "done" for t in tasks)
            else None
        )
        index_doc = {
            **meta,
            "type": "feature",
            "base_branch": "dev",
            "completed_at": completed_at,
            "tasks": tasks,
        }
        out = dest / f"{slug}.json"
        if not dry_run:
            out.write_text(json.dumps(index_doc, indent=2, sort_keys=False) + "\n")
    # 4. Emit orphans
    if orphans:
        for o in orphans:
            print(f"WARN: TASK-{o.get('id', '?')} has no feature; routed to _orphans.json", file=sys.stderr)
        orph_doc = {
            "feature": "_orphans",
            "feature_id": None,
            "spec": None,
            "type": "feature",
            "base_branch": "dev",
            "created_at": None,
            "completed_at": None,
            "tasks": orphans,
        }
        out = dest / "_orphans.json"
        if not dry_run:
            out.write_text(json.dumps(orph_doc, indent=2) + "\n")
    return 0
```

### Idempotency

- `sort_keys=False` plus deterministic ordering (`sorted(grouped.items())`) ensures byte-equivalent output across runs.
- `completed_at` uses `datetime.now()` only when every task is done — for in-progress features it stays `null`. To stay byte-stable, prefer reading the latest `started_at`/`completed_at` from the task entries themselves rather than calling `datetime.now()`. **Use the max of `task.get("completed_at")` across the group, or `None` if any task is not done.** This makes the script byte-stable on idempotent reruns.

### CLI

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="sdd/tasks/.index.json", type=Path)
    parser.add_argument("--dest", default="sdd/tasks/index", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return migrate(args.source, args.dest, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
```

### Key Constraints

- Stdlib + `scripts.sdd.sdd_meta` only.
- Must NOT modify or delete `sdd/tasks/.index.json`.
- Must tolerate legacy task entries missing optional fields.
- Must produce one JSON file per feature slug, even if `feature_id` collides across slugs.

---

## Acceptance Criteria

- [ ] `python -m scripts.sdd.migrate_index --source <fixture> --dest <tmp>` runs to completion.
- [ ] Re-running produces byte-identical output (idempotent).
- [ ] Source `sdd/tasks/.index.json` is unmodified after the run.
- [ ] One file per `feature` slug under `<dest>/`.
- [ ] `_orphans.json` exists if and only if any task lacked a feature; stderr warnings emitted.
- [ ] Both FEAT-142 slugs (`embedding-catalog-as-prefix-source-of-truth` and `webscrapingloader-jsonld-support`) produce SEPARATE files (slug-based grouping handles the ID collision).
- [ ] `pytest tests/scripts/test_migrate_index.py -v` passes.
- [ ] After implementation, the agent runs the migration once on the real monolith and commits the resulting `sdd/tasks/index/` directory in a separate follow-up commit (`sdd: run TASK-995 migration on live monolith`).

---

## Test Specification

```python
# tests/scripts/test_migrate_index.py
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def monolith(tmp_path: Path) -> Path:
    """Synthetic monolith with current feature, two prior, and one orphan."""
    src = tmp_path / "src.json"
    src.write_text(json.dumps({
        "feature": "current-feature",
        "feature_id": "FEAT-100",
        "spec": "sdd/specs/current-feature.spec.md",
        "created_at": "2026-05-01T00:00:00+00:00",
        "previous_features": [
            {"feature": "prior-a", "feature_id": "FEAT-099", "spec": "sdd/specs/prior-a.spec.md"},
            {"feature": "prior-b", "feature_id": "FEAT-098", "spec": "sdd/specs/prior-b.spec.md"},
        ],
        "tasks": [
            {"id": "TASK-001", "feature": "current-feature", "feature_id": "FEAT-100", "status": "pending"},
            {"id": "TASK-002", "feature": "prior-a", "feature_id": "FEAT-099", "status": "done"},
            {"id": "TASK-003", "feature": "prior-b", "feature_id": "FEAT-098", "status": "done"},
            {"id": "TASK-099", "status": "pending"},  # orphan: no feature
        ],
    }))
    return src


def test_groups_by_feature_slug(monolith: Path, tmp_path: Path):
    dest = tmp_path / "out"
    from scripts.sdd.migrate_index import migrate
    migrate(monolith, dest)
    assert (dest / "current-feature.json").exists()
    assert (dest / "prior-a.json").exists()
    assert (dest / "prior-b.json").exists()


def test_orphans_routed(monolith: Path, tmp_path: Path, capsys):
    dest = tmp_path / "out"
    from scripts.sdd.migrate_index import migrate
    migrate(monolith, dest)
    orph = json.loads((dest / "_orphans.json").read_text())
    assert orph["feature"] == "_orphans"
    assert len(orph["tasks"]) == 1
    captured = capsys.readouterr()
    assert "TASK-099" in captured.err


def test_idempotent(monolith: Path, tmp_path: Path):
    dest = tmp_path / "out"
    from scripts.sdd.migrate_index import migrate
    migrate(monolith, dest)
    first = {p.name: p.read_bytes() for p in dest.iterdir()}
    migrate(monolith, dest)
    second = {p.name: p.read_bytes() for p in dest.iterdir()}
    assert first == second


def test_does_not_modify_source(monolith: Path, tmp_path: Path):
    original = monolith.read_bytes()
    from scripts.sdd.migrate_index import migrate
    migrate(monolith, tmp_path / "out")
    assert monolith.read_bytes() == original


def test_completed_at_set_when_all_done(monolith: Path, tmp_path: Path):
    dest = tmp_path / "out"
    from scripts.sdd.migrate_index import migrate
    migrate(monolith, dest)
    prior = json.loads((dest / "prior-a.json").read_text())
    # All tasks for prior-a are status=done in the fixture
    assert prior["completed_at"] is not None
    current = json.loads((dest / "current-feature.json").read_text())
    # current has a pending task → completed_at is null
    assert current["completed_at"] is None
```

---

## Agent Instructions

1. Activate venv: `source .venv/bin/activate`.
2. Verify TASK-994 is in `sdd/tasks/completed/` and `from scripts.sdd.sdd_meta import FlowMeta` works.
3. Implement `migrate_index.py` per the contract.
4. Run `pytest tests/scripts/test_migrate_index.py -v` until green.
5. Run `ruff check scripts/sdd/migrate_index.py tests/scripts/test_migrate_index.py`.
6. Commit code: `feat(sdd): TASK-995 — monolith → per-spec migration script`.
7. **Then run the migration on the live monolith:**
   ```bash
   python -m scripts.sdd.migrate_index
   ls sdd/tasks/index/ | head
   ```
8. Stage and commit the generated indexes in a separate commit:
   ```bash
   git add sdd/tasks/index/
   git commit -m "sdd: run TASK-995 migration on live monolith"
   ```

---

## Completion Note

**Completed by**: Claude (Opus 4.7) — interactive session via `/sdd-start TASK-995`
**Date**: 2026-05-05
**Notes**: Implemented `scripts/sdd/migrate_index.py` and ran the live migration. Source monolith preserved; 127 per-spec index files written under `sdd/tasks/index/`. All 7 unit tests pass.

**Migration outcome on the live monolith** (commit `0f434117`):
- 126 per-spec index files (one per unique `feature` slug across the current top-level + `previous_features` registry).
- 1 orphan in `_orphans.json`: legacy entry `TASK-748` (recorded as `TASK-TASK-748` in the monolith — malformed `id`, no `feature`). Routed cleanly with the documented stderr warning.
- FEAT-145's per-spec index (`sdd-flow-types-and-per-spec-index.json`) generated correctly with all 9 tasks and the current `done`/`in-progress`/`pending` mix.
- Idempotency verified by sha256 — re-running the migration on the live monolith produces byte-identical output.

**Tests added**: 7 (one beyond the contract's 5: `test_dry_run_writes_nothing` and `test_feat142_collision_split_by_slug`, the latter explicitly exercising the FEAT-142 collision risk called out in §7 of the spec).

**Deviations from contract**:
1. **Test directory**: created in `tests/sdd_scripts/` instead of `tests/scripts/` to remain consistent with the rename done by TASK-994 (the original name shadows the worktree's real `scripts/` package under pytest).
2. **Lint step skipped**: ruff/pyflakes still unavailable in `.venv`; `python -m py_compile` passes.

**Follow-ups for downstream tasks**:
- TASK-998 (`/sdd-start` rewrite) can now safely read from per-spec indexes — the FEAT-145 per-spec index is in place.
- TASK-1000 (`/sdd-status`, `/sdd-next`) should surface `_orphans.json` per the spec §3 / Module 7.
- The legacy monolith `sdd/tasks/.index.json` is untouched and should remain so until the team has verified the migration end-to-end. Removal is a separate, explicit step.
