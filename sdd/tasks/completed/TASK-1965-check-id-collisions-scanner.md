# TASK-1965: `check_id_collisions.py` — defense-in-depth scanner

**Feature**: FEAT-387 — SDD Task-ID Allocation Race Fix
**Spec**: `sdd/specs/sdd-task-id-allocation-race.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Even with the compare-and-swap allocator (TASK-1964), the spec calls for an
independent, read-only backstop (§2, §3 Module 3): a stateless scanner that
detects any `TASK-<NNN>` number associated with more than one distinct
feature slug across the repo's current SDD state. This is the check that
would have caught the six real collisions found during FEAT-380's closeout
(TASK-1939/1940/1941/1942/1944/1946 each shared with an unrelated feature)
had it existed at the time.

This task has NO dependency on TASK-1963/1964 — it only reads existing SDD
files (`sdd/tasks/index/*.json`, `sdd/tasks/active/*.md`,
`sdd/tasks/completed/*.md`) and is independently testable/mergeable,
matching the spec's `parallel: true` guidance for Module 3.

---

## Scope

- Implement `find_collisions() -> list[CollisionReport]` per spec §2 New
  Public Interfaces: scans `sdd/tasks/index/*.json` (task `id` fields +
  their owning `feature`/`feature_id`), `sdd/tasks/active/*.md`, and
  `sdd/tasks/completed/*.md` (filenames, matched by `TASK-<NNN>-` prefix)
  for any `TASK-<NNN>` number used by more than one distinct feature slug.
- `TASK-<NNN>` collisions across different slugs are **failures**.
  `FEAT-<NNN>` collisions across different specs are explicitly tolerated
  (spec Non-Goals — `migrate_index.py`'s own documented convention) and
  must be reported separately as informational, never as a failure.
- CLI (`python -m scripts.sdd.check_id_collisions`) exits 1 and prints a
  human-readable report (one line per colliding `TASK-<NNN>`, listing every
  offending file/slug) when any `TASK` collision is found; exits 0
  otherwise, still printing the informational `FEAT-<NNN>` reuse list
  (non-fatal) if any exist.
- Write unit tests per the spec's Test Specification: detects real
  collisions, tolerates the accepted `FEAT-<NNN>` reuse pattern, and a
  clean-repo case exits 0.

**NOT in scope**:
- Fixing or renumbering any of the six pre-existing `TASK-<NNN>` collisions
  discovered during FEAT-380's closeout (spec Non-Goals — this task must
  NOT modify `sdd/tasks/active/`, `sdd/tasks/completed/`, or
  `sdd/tasks/index/` files belonging to any OTHER feature).
- CI wiring (TASK-1967 adds the workflow step that calls this script).
- The allocator (TASK-1964).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_id_collisions.py` | CREATE | `find_collisions()`, `CollisionReport` model, CLI entrypoint |
| `tests/sdd_scripts/test_check_id_collisions.py` | CREATE | Collision-detection, FEAT-ID-reuse-tolerance, clean-repo tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-28.

### Verified Imports
```python
from __future__ import annotations
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel  # verified: scripts/sdd/sdd_meta.py:19
```

### Existing Signatures to Use / Data Shapes to Read

**Per-spec index schema** — confirmed by reading
`sdd/tasks/index/sandbox-hardening.json` directly (real file on `dev`):
```json
{
  "feature": "sandbox-hardening",
  "feature_id": "FEAT-380",
  "tasks": [
    {"id": "TASK-1939", "feature_id": "FEAT-380", "feature": "sandbox-hardening", "...": "..."}
  ]
}
```
Each task entry carries its OWN `feature`/`feature_id` (not just the index
header) — confirmed via `.claude/commands/sdd-task.md:130-131` ("Both
`feature_id` and `feature` must be present on every task entry" per
`CLAUDE.md`'s Task Index Schema section) — use the per-task fields as the
authoritative slug for collision comparison, not just the file's header
(defends against a task somehow being appended to the wrong index file).

**`_orphans.json` shape** — confirmed by reading
`sdd/tasks/index/_orphans.json` directly: `{"feature": "_orphans",
"feature_id": null, ..., "tasks": []}`. Exclude this file from the scan
by basename, same as `.claude/commands/sdd-start.md:24-28`'s own exclusion
rule (`[[ "$(basename "$f")" == "_orphans.json" ]] && continue`).

**Task filename pattern** — confirmed via
`scripts/sdd/close_task.sh:54` (`active_matches=("$ACTIVE_DIR/${TASK_ID}-"*.md)`):
files are named `TASK-<NNN>-<slug>.md`; the numeric ID is the prefix up to
the first `-` after the digits.

**The six known pre-existing collisions** (confirmed via `git log`/`ls`
during FEAT-380's closeout, real files currently on `dev`) — use these as
a live acceptance-test fixture for `test_find_collisions_detects_task_id_reuse`
if convenient, OR construct synthetic fixtures instead (see Implementation
Notes) to keep the test suite independent of this pre-existing, unrelated
repo state:
- `TASK-1939-repl-dedicated-executor.md` (sandbox-hardening) vs.
  `TASK-1939-audit-residual-bus-artifacts.md` (eventbus-replacement-evaluation)
- `TASK-1940-repl-worker-protocol-entrypoint.md` (sandbox-hardening) vs.
  `TASK-1940-fix-residual-bus-issues.md` (eventbus-replacement-evaluation)
- `TASK-1941-repl-worker-handle-deadline.md` (sandbox-hardening) vs.
  `TASK-1941-guard-test-update-and-green-gate.md` (fix-msword-loader-none-name)
- `TASK-1942-repl-worker-pool-lifecycle.md` (sandbox-hardening) vs.
  `TASK-1942-guard-para-style-none.md` (fix-mswordloader-none-name)
- `TASK-1944-port-namespace-callsites.md` (sandbox-hardening) vs.
  `TASK-1944-guard-para-style-none-access.md` (fix-msword-loader-none-style)
- `TASK-1946-rlimit-as-calibration.md` (sandbox-hardening) vs.
  `TASK-1946-guard-para-style-none-access.md` (fix-msword-loader-none-style)

### Does NOT Exist
- ~~`scripts/sdd/check_id_collisions.py`~~ — this task creates it.
- ~~Any mechanism that FAILS on `FEAT-<NNN>` reuse~~ — explicitly rejected
  by the spec's Non-Goals; `migrate_index.py`'s own docstring documents
  FEAT-ID reuse as an accepted, disambiguated-by-slug pattern. This
  scanner must report shared FEAT-IDs informationally, never as a failure.
- ~~A dependency on `scripts/sdd/reserve_ids.py` or `id_ledger.py`~~ — this
  task is read-only and independent of TASK-1963/1964's allocator; do not
  import from those modules.

---

## Implementation Notes

### Pattern to Follow
```python
# scripts/sdd/check_id_collisions.py — sketch
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from pydantic import BaseModel

_TASK_FILENAME_RE = re.compile(r"^(TASK-\d+)-")


class CollisionReport(BaseModel):
    id: str  # e.g. "TASK-1939"
    kind: str  # "task" | "feature"
    slugs: list[str]  # every distinct feature slug found using this id
    sources: list[str]  # file paths where each was found


def find_collisions(
    index_dir: Path = Path("sdd/tasks/index"),
    active_dir: Path = Path("sdd/tasks/active"),
    completed_dir: Path = Path("sdd/tasks/completed"),
    specs_dir: Path = Path("sdd/specs"),
) -> list[CollisionReport]:
    task_owners: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    # 1. Walk sdd/tasks/index/*.json (skip _orphans.json), read each task's
    #    own "id"/"feature" fields.
    # 2. Cross-check sdd/tasks/active/*.md + completed/*.md filenames against
    #    the index-derived slug (catches drift between filename and index).
    # 3. Separately tally FEAT-<NNN> -> spec slug from sdd/specs/*.md headers
    #    for the informational (non-failing) report.
    ...
```

### Key Constraints
- Read-only — this script must never write to `sdd/tasks/` or
  `sdd/specs/` under any code path.
- Must run correctly from the repo root with no network access (pure local
  file scan), so it's cheap enough for a required CI check on every push.
- Prefer constructing collision fixtures in an isolated `tmp_path` (per the
  spec's Test Data / Fixtures pattern) over asserting against the real,
  currently-collision-bearing `dev` tree in unit tests — keeps the test
  suite deterministic and independent of future cleanup of those six
  pre-existing entries (which are explicitly out of scope to fix, per
  Non-Goals, and could be cleaned up by an unrelated future change without
  breaking this task's tests).
- The CLI's human-readable report should be greppable/parseable enough for
  a human debugging a CI failure to immediately identify BOTH offending
  files (path + owning feature slug) for each collision — this is the
  exact information that was missing when the six real collisions were
  discovered manually.

### References in Codebase
- `sdd/tasks/index/sandbox-hardening.json` — real per-spec index example.
- `sdd/tasks/index/_orphans.json` — real orphans-file example (exclude from FEAT-ID scan).
- `scripts/sdd/close_task.sh:54` — task filename pattern.
- `scripts/sdd/migrate_index.py` — FEAT-ID reuse convention, byte-stable output style.

---

## Acceptance Criteria

- [ ] `find_collisions()` reports one `CollisionReport` per `TASK-<NNN>`
      number associated with more than one distinct feature slug, naming
      every offending source file.
- [ ] `FEAT-<NNN>` reuse across specs is reported informationally and never
      causes a non-zero exit or appears in the "failing" collision list.
- [ ] CLI exits 1 with a human-readable report on any `TASK` collision;
      exits 0 (with any informational FEAT-ID-reuse notes printed but
      non-fatal) otherwise.
- [ ] All tests pass: `pytest tests/sdd_scripts/test_check_id_collisions.py -v`
- [ ] No linting errors: `ruff check scripts/sdd/check_id_collisions.py`

---

## Test Specification

```python
# tests/sdd_scripts/test_check_id_collisions.py
from __future__ import annotations

import json
from pathlib import Path

from scripts.sdd.check_id_collisions import find_collisions


def _write_index(path: Path, feature: str, feature_id: str, task_ids: list[str]) -> None:
    path.write_text(json.dumps({
        "feature": feature,
        "feature_id": feature_id,
        "tasks": [
            {"id": t, "feature": feature, "feature_id": feature_id}
            for t in task_ids
        ],
    }))


class TestFindCollisions:
    def test_detects_task_id_reuse(self, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        _write_index(index_dir / "feature-a.json", "feature-a", "FEAT-001", ["TASK-100"])
        _write_index(index_dir / "feature-b.json", "feature-b", "FEAT-002", ["TASK-100"])
        collisions = find_collisions(index_dir=index_dir, active_dir=tmp_path / "active",
                                      completed_dir=tmp_path / "completed", specs_dir=tmp_path / "specs")
        task_collisions = [c for c in collisions if c.kind == "task"]
        assert len(task_collisions) == 1
        assert task_collisions[0].id == "TASK-100"
        assert set(task_collisions[0].slugs) == {"feature-a", "feature-b"}

    def test_tolerates_feature_id_reuse(self, tmp_path: Path) -> None:
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "a.spec.md").write_text("**Feature ID**: FEAT-380\n")
        (specs_dir / "b.spec.md").write_text("**Feature ID**: FEAT-380\n")
        collisions = find_collisions(index_dir=tmp_path / "index", active_dir=tmp_path / "active",
                                      completed_dir=tmp_path / "completed", specs_dir=specs_dir)
        assert not any(c.kind == "task" for c in collisions)

    def test_clean_repo_exits_zero(self, tmp_path: Path) -> None:
        index_dir = tmp_path / "index"
        index_dir.mkdir()
        _write_index(index_dir / "feature-a.json", "feature-a", "FEAT-001", ["TASK-100"])
        _write_index(index_dir / "feature-b.json", "feature-b", "FEAT-002", ["TASK-200"])
        collisions = find_collisions(index_dir=index_dir, active_dir=tmp_path / "active",
                                      completed_dir=tmp_path / "completed", specs_dir=tmp_path / "specs")
        assert not any(c.kind == "task" for c in collisions)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-task-id-allocation-race.spec.md` for full context.
2. **Check dependencies** — none for this task; it can run in parallel with TASK-1963/1964.
3. **Verify the Codebase Contract** — re-read `sdd/tasks/index/sandbox-hardening.json` and `sdd/tasks/index/_orphans.json` to confirm the schema shapes above before writing any code.
4. **Update status** in `sdd/tasks/index/sdd-task-id-allocation-race.json` → `"in-progress"`.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-1965-check-id-collisions-scanner.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**: Implemented `find_collisions()`/`CollisionReport`/CLI. Important
finding during implementation: the sketch's step 2 ("cross-check
active/completed filenames against the index-derived slug") as literally
described conflates two different namespaces — a per-task index entry's
`feature` slug (e.g. `"sandbox-hardening"`) vs. a task file's own
descriptive slug (e.g. `"repl-dedicated-executor"`, the `<slug>` in
`TASK-<NNN>-<slug>.md`). These are never expected to be equal even for a
single, healthy, correctly-owned task, so naively merging both into one
dict produced ~1804 false "collisions" when run against the real `dev`
tree (nearly every task in the repo). Fixed by tracking the two as
independent namespaces: (1) index-derived `feature` ownership is the
primary, authoritative collision signal (empirically confirmed sufficient
to detect all six FEAT-380-era collisions on its own, since both sides of
each real collision are properly indexed); (2) raw filename-derived
descriptive-slug duplication under active/completed is kept as an
independent, secondary fallback signal, only surfaced when the index
doesn't disambiguate a given TASK-ID at all. Re-running against the real
`dev` tree after the fix reports 316 genuine `TASK-<NNN>` collisions
(all pre-existing, pre-per-spec-index-era task numbering reused across
unrelated features, including but far exceeding the six FEAT-380-era ones
named in the spec) — flagging this for TASK-1967, since its assumption of
"exactly six" pre-existing collisions for the baseline file undercounts
reality by ~50x; the baseline must be generated from the live tree, not
hardcoded to the six named IDs, to satisfy TASK-1967's own acceptance
criterion that a local dry run must exit 0 against the current `dev`
tree. 7 tests pass (`pytest tests/sdd_scripts/test_check_id_collisions.py
-v` — the 3 spec-required tests plus 4 additional tests covering
filename-only fallback detection, `_orphans.json` handling, and CLI exit
codes). `ruff check scripts/sdd/check_id_collisions.py` clean.

**Deviations from spec**: Added 4 tests beyond the spec's 3-test list
(filename-fallback collision detection, `_orphans.json` task-scan
inclusion, CLI exit-code smoke tests) to cover edge cases surfaced while
verifying against the real repo. No `--baseline` flag added here (left for
TASK-1967 per its own Implementation Notes, which explicitly permit adding
it there). The step-2 filename cross-check was redesigned (see Notes
above) from the sketch's literal "one merged dict" shape to two
independent namespaces — same detection GOAL (catch collisions the index
might miss), corrected mechanism to avoid a false-positive storm on real
data; the officially-specified 3 unit tests and all Acceptance Criteria
are unaffected and pass.
