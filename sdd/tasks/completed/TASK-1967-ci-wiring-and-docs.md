# TASK-1967: CI wiring for `check_id_collisions.py` + documentation

**Feature**: FEAT-387 — SDD Task-ID Allocation Race Fix
**Spec**: `sdd/specs/sdd-task-id-allocation-race.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1965, TASK-1966
**Assigned-to**: unassigned

---

## Context

Final module of the spec (§3 Module 5): make the collision scanner
(TASK-1965) an automatic backstop in CI, and document the new ledger file
and both scripts so future contributors (human or agent) understand the
allocation mechanism without re-deriving it from source. Depends on
TASK-1965 (the scanner must exist to be wired in) and TASK-1966 (docs
should describe the FULL, already-wired end-to-end flow, not just the
scripts in isolation).

---

## Scope

- Add a step to the **existing** `lint-and-registry` job in
  `.github/workflows/ci.yml` (NOT a new job — see Codebase Contract: this
  job already runs a structurally identical "check X freshness" step) that
  runs `uv run python -m scripts.sdd.check_id_collisions` and fails the
  build on a `TASK-<NNN>` collision.
- Document a **one-time baseline exception** for the six pre-existing
  collisions (spec §5 Acceptance Criteria, last bullet): since this task
  must NOT retroactively fix those six files (Non-Goal, TASK-1965's own
  scope), the new CI step is expected to start FAILING on `dev` the moment
  it's merged, unless explicitly scoped to avoid them. Resolve this per the
  spec's Open Question recommendation (diff-scoped: only fail on
  collisions introduced by the current PR's own diff, not pre-existing
  ones) — see Implementation Notes for the concrete mechanism.
- Update `sdd/WORKFLOW.md` and `CLAUDE.md`'s SDD Auto-Commit Rule table
  (`CLAUDE.md:232-239`) to mention:
  - `sdd/tasks/.id_ledger.json` as a new git-tracked file, updated by
    `reserve_ids.py`, committed independently (not part of any single
    command's normal commit — it's committed by the reservation call
    itself, which both `/sdd-task` and `/sdd-spec` now invoke).
  - `scripts/sdd/reserve_ids.py` and `scripts/sdd/check_id_collisions.py`
    as new tooling, briefly describing their role.

**NOT in scope**:
- Renumbering the six known pre-existing collisions.
- Any change to the scanner's or allocator's actual Python implementation
  (TASK-1964/1965 own that; this task only wires the scanner into CI and
  writes docs).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.github/workflows/ci.yml` | MODIFY | Add a step to `lint-and-registry` running `check_id_collisions.py`, diff-scoped to the current push/PR |
| `sdd/WORKFLOW.md` | MODIFY | Document the ledger file and both new scripts |
| `CLAUDE.md` | MODIFY | Add the ledger file to the SDD Auto-Commit Rule table (`CLAUDE.md:232-239`) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` HEAD on 2026-07-28. TASK-1965/1966 (this task's
> dependencies) must be `done` before starting.

### Verified Imports
N/A — this task edits a YAML workflow file and two markdown docs, not
Python source.

### Existing Signatures to Use
```yaml
# .github/workflows/ci.yml:10-30 (existing job to extend — confirmed full
# file is 167 lines, this is the FIRST job, "lint-and-registry")
jobs:
  lint-and-registry:
    name: Lint & Registry Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      - name: Sync all workspace packages
        run: uv sync --all-packages
      - name: Check registry freshness
        run: uv run python scripts/generate_tool_registry.py --check
```
This job already establishes the exact pattern to mirror: a repo-content
"freshness/consistency" assertion run as a plain script invocation, not a
pytest suite (confirmed: `scripts/generate_tool_registry.py --check` is
the precedent for "a script that asserts something about repo state and
exits non-zero on violation," which is exactly what
`check_id_collisions.py` is).

**Confirmed: `check_id_collisions.py`'s own unit tests are ALREADY covered
by the existing `test-core` job** — `.github/workflows/ci.yml:63` runs
`uv run pytest tests/ -x -q --tb=short --ignore=tests/tools`, and root
`pyproject.toml:220` sets `testpaths = ["tests"]`, so
`tests/sdd_scripts/test_check_id_collisions.py` (TASK-1965's deliverable)
is picked up automatically — this task does NOT need to add a new test job,
only the repo-state CHECK step to `lint-and-registry`.

**`CLAUDE.md`'s existing table** (verify still at these lines before
editing — content may have shifted since this contract was written):
```markdown
<!-- CLAUDE.md:232-239 -->
| Command | What it commits | Where (FEAT-145) |
|---------|-----------------|------------------|
| `/sdd-brainstorm` | `sdd/proposals/<n>.brainstorm.md` (with frontmatter) | `base_branch` |
| `/sdd-proposal`   | `sdd/proposals/<n>.proposal.md` (with frontmatter)  | `base_branch` |
| `/sdd-spec`       | `sdd/specs/<n>.spec.md` (with frontmatter)          | `base_branch` |
| `/sdd-task`       | `sdd/tasks/index/<feature>.json` + `sdd/tasks/active/TASK-*` | `base_branch` |
| `/sdd-start`      | Per-spec index status update + implementation code  | worktree (feature branch) |
| `/sdd-done`       | Per-spec index final state + task file moves; merges feature → `base_branch` | `base_branch` (NEVER `main`) |
```

### Does NOT Exist
- ~~A dedicated `id-collision-check` CI job~~ — this task adds a STEP to
  the existing `lint-and-registry` job, per the precedent above; do not
  invent a new job unless the executing agent finds a concrete reason the
  existing job is unsuitable (e.g. a dependency conflict), in which case
  document the deviation in the Completion Note.
- ~~Any `paths:` filter already on `ci.yml`'s triggers~~ — confirmed via
  full read of `.github/workflows/ci.yml:1-8`: the `push`/`pull_request`
  triggers fire on ALL changes to `main`/`dev` branches with no path
  filtering at all today. Do not assume a `paths:` filter exists to scope
  when this job runs — if diff-scoping is needed (see Implementation
  Notes), it must happen INSIDE the step's script logic, not via a
  workflow-level `paths:` filter.

---

## Implementation Notes

### Pattern to Follow
Add the new step directly after "Check registry freshness" in
`lint-and-registry`, matching its exact style (`name:` + `run:` on one
line via `uv run python -m ...`).

### Key Constraints — the baseline-exception mechanism
The six pre-existing collisions must not fail CI on unrelated future PRs.
Per the spec's Open Question recommendation (diff-scoped check), implement
this as: the CI step passes `--baseline` pointing at a small, git-tracked
allowlist file (e.g. `scripts/sdd/.collision_baseline.json`, listing
exactly the six known `TASK-<NNN>` numbers as of this task's creation)
to `check_id_collisions.py`'s CLI. `find_collisions()` (TASK-1965) already
returns every collision unconditionally — this task's CLI wrapper (or a
small addition to it, coordinate with TASK-1965's actual final interface
if not already flexible enough) filters OUT any collision whose `id` is in
the baseline file before deciding the exit code, so:
- CI fails only on a **NEW** collision (one not in the baseline).
- The six known ones remain visible in the script's output (not hidden),
  just non-fatal.
- If `check_id_collisions.py`'s CLI does not yet support a `--baseline`
  flag by the time this task starts, ADD it here (small, additive change,
  still within this task's file list since it's the wiring/consumption
  side of the contract, not new detection logic) rather than reopening
  TASK-1965.

### References in Codebase
- `.github/workflows/ci.yml` — job/step structure to extend.
- `scripts/generate_tool_registry.py --check` — the existing precedent for
  a "repo-state consistency" CI step run as a plain script.
- `CLAUDE.md:226-244` — SDD Auto-Commit Rule section and table to extend.
- `sdd/WORKFLOW.md` — narrative SDD workflow doc to extend with the new
  scripts.

---

## Acceptance Criteria

- [ ] `.github/workflows/ci.yml`'s `lint-and-registry` job runs
      `check_id_collisions.py` and fails the build on any NEW `TASK-<NNN>`
      collision, while not failing on the six pre-existing, baselined ones.
- [ ] `sdd/WORKFLOW.md` documents `sdd/tasks/.id_ledger.json`,
      `reserve_ids.py`, and `check_id_collisions.py`.
- [ ] `CLAUDE.md`'s SDD Auto-Commit Rule table mentions the ledger file.
- [ ] A local dry run of the new CI step
      (`uv run python -m scripts.sdd.check_id_collisions --baseline
      scripts/sdd/.collision_baseline.json`) exits 0 against the current
      `dev` tree.

---

## Test Specification

This task is primarily CI/YAML + docs; the only executable-behavior
change (the `--baseline` flag, if added here) should get a focused test
alongside TASK-1965's existing suite:

```python
# tests/sdd_scripts/test_check_id_collisions.py (addition)
def test_baseline_suppresses_known_collisions(tmp_path):
    """A collision listed in the baseline file must not cause a failing exit."""
    ...
```

Manual verification for the CI/docs portions:
```bash
# Confirm the new step is present:
grep -n "check_id_collisions" .github/workflows/ci.yml

# Confirm docs mention the ledger:
grep -n "id_ledger" sdd/WORKFLOW.md CLAUDE.md
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sdd-task-id-allocation-race.spec.md` for full context.
2. **Check dependencies** — verify TASK-1965 and TASK-1966 are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `.github/workflows/ci.yml` and `CLAUDE.md:226-244` to confirm line numbers/content haven't shifted.
4. **Update status** in `sdd/tasks/index/sdd-task-id-allocation-race.json` → `"in-progress"`.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-1967-ci-wiring-and-docs.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-28
**Notes**: Added a new step to the existing `lint-and-registry` job in
`.github/workflows/ci.yml` (not a new job, per the confirmed precedent)
running `check_id_collisions.py --baseline scripts/sdd/.collision_baseline.json`.
Added the `--baseline` flag to `check_id_collisions.py`'s CLI (its own
Implementation Notes explicitly permit this, since `--baseline` did not
yet exist after TASK-1965) plus 2 new tests
(`test_baseline_suppresses_known_collisions`,
`test_baseline_does_not_suppress_new_collisions`) in
`tests/sdd_scripts/test_check_id_collisions.py`. Updated `sdd/WORKFLOW.md`
(new "TASK/FEAT ID Allocation (FEAT-387)" section) and `CLAUDE.md`'s SDD
Auto-Commit Rule table + a new FEAT-387 note.

**IMPORTANT finding, materially changing the baseline's scope**: TASK-1965's
completion note already flagged this, but it's worth restating here since
it drove this task's actual implementation. Running
`check_id_collisions.py` against the real `dev` tree (via this worktree,
which branched from `dev` and has no other feature's SDD files modified)
found **316** distinct `TASK-<NNN>` collisions — not the "six known
FEAT-380-era" ones the spec's Non-Goals/Acceptance-Criteria text describes.
The other ~310 are low-numbered IDs (TASK-001 through roughly TASK-1770)
reused across many, many unrelated older features — clearly a pre-existing,
pre-`per-spec-index` (FEAT-145) era where task numbering was scoped
per-feature rather than globally unique, long before this spec's race
condition was possible. Since TASK-1967's own acceptance criterion
requires "a local dry run... exits 0 against the current dev tree," a
baseline containing only six IDs would make this brand-new CI check
immediately fail on merge for reasons unrelated to this feature — the
opposite of the stated intent ("only fails on NEW collisions introduced
by the PR's own diff, not pre-existing ones"). I generated
`scripts/sdd/.collision_baseline.json` programmatically by running
`find_collisions()` against the live tree at implementation time and
capturing every current `TASK-<NNN>` collision ID (316 entries, sorted
numerically) — not a hand-typed six-item list. Verified the local dry run
acceptance criterion directly: `python -m scripts.sdd.check_id_collisions
--baseline scripts/sdd/.collision_baseline.json` exits 0 against the
current tree (316 pre-existing baselined, 40 informational FEAT-ID reuse
notes, 0 new collisions). All 61 tests in `tests/sdd_scripts/` pass;
`ruff check scripts/sdd/check_id_collisions.py
tests/sdd_scripts/test_check_id_collisions.py` clean; `ci.yml` re-parsed
as valid YAML after editing.

**Deviations from spec**: (1) The baseline file's CONTENT is the full,
programmatically-generated set of 316 current collisions rather than the
spec's assumed six — a data correction, not an architectural deviation;
the baseline-exception MECHANISM itself (diff-scoped, in-script, git-tracked
allowlist) is implemented exactly as specified. (2) Per the task's own
Implementation Notes (not its Files-to-Create/Modify table, which lists
only the 3 CI/docs files), also modified `scripts/sdd/check_id_collisions.py`
(added `--baseline`) and created `scripts/sdd/.collision_baseline.json`,
and added 2 tests to `tests/sdd_scripts/test_check_id_collisions.py` —
explicitly authorized by the task's own prose ("ADD it here... still
within this task's file list... rather than reopening TASK-1965").
