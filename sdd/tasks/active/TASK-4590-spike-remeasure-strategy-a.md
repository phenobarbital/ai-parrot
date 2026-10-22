# TASK-4590: Spike — re-measure strategy (a) on current dev

**Feature**: FEAT-720 — One Importable Identity per Package Test Tree
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:45cf6a054e06`

---

## Context

Implements spec **Module 1**. This is a measurement task: it produces evidence
and **no product change**.

FEAT-618's `TASK-3908` measured strategy (a) three weeks ago and paused at the
decision point. One measurement it could **not** take was the per-distribution
`--collect-only` **baseline before the change** — the sandbox denied writing in
the shared main checkout. Without that baseline, round 2 could not attribute its
most alarming result: `packages/ai-parrot` exits 4 on collect after the change,
and nobody knows whether it did so before.

Every later task in this feature is scoped from this task's output. TASK-4592's
~24 sites, TASK-4593's ~34 and TASK-4594's ~12 are *estimates from round 2*; this
spike replaces them with today's numbers.

---

## Scope

- Record the per-distribution `--collect-only` baseline for all 28 package test
  roots **before** touching anything.
- Apply strategy (a) in the worktree: delete the 25 top-level
  `packages/*/tests/__init__.py`, add `--import-mode=importlib` to the root
  `addopts`.
- Re-run the same per-distribution collect; diff against the baseline.
- Classify every **new** error into breakage classes (i)–(vi) from spec §2.
- Resolve the open question: does `ai-parrot`'s exit 4 pre-exist the change?
- **Revert the experiment.** Commit the evidence file only.
- Write `sdd/state/FEAT-720/spike-collect.md` ending with an explicit verdict
  line: `STRATEGY (a) CONFIRMED` or `STRATEGY (a) REFUTED — <why>`.

**NOT in scope**: deleting any `__init__.py` for real (TASK-4591), repairing any
import site (TASK-4592/4593/4594), writing the regression test (TASK-4595),
fixing anything the baseline shows as already broken, and fixing any
`parrot-formdesigner` test failure (FEAT-618 owns those).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/state/FEAT-720/spike-collect.md` | CREATE | The two collect matrices, their diff, the per-class tally, and the verdict line |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

None — this task writes no Python.

### Existing Signatures to Use

```toml
# pyproject.toml:247
[tool.pytest.ini_options]           # line 247
addopts = [                         # line 248
    "--strict-config",              # line 249
    "--strict-markers",             # line 250
]                                   # line 251
testpaths = ["tests"]               # line 252
```

### Verified facts (measured on `dev c2fd0ae28`, pytest 9.1.1)

| Fact | Value | Command |
|---|---|---|
| top-level `packages/*/tests/__init__.py` | **25** (all 0 bytes) | `ls packages/*/tests/__init__.py \| wc -l` |
| all `__init__.py` under `packages/*/tests` | **267** (⇒ 242 nested) | `find packages/*/tests -name '__init__.py' \| wc -l` |
| files importing `from tests.<x>` | **34** | `grep -rln -E '^\s*(from\|import)\s+tests[.\s]' packages/` |
| dotted string targets `"tests.…"` | **68** occurrences | `grep -rn "['\"]tests\." packages/*/tests` |
| pytest | **9.1.1** | `python -m pytest --version` |

The 28 package test roots are `packages/*/tests`; 3 of them
(`ai-parrot-advisors`, `ai-parrot-openlit-bridge`, `navrules`) already have no
`__init__.py` and are the control group.

### Does NOT Exist
- ~~a per-package `pytest.ini` / `setup.cfg` / `[tool.pytest]` block~~ — pytest
  config lives **only** in the root `pyproject.toml:247`.
- ~~`--import-mode` anywhere in the repo today~~ — `grep -n "import-mode" pyproject.toml`
  returns nothing.
- ~~`consider_namespace_packages`~~ — not set. If the spike finds it helps, that
  is a **new finding to report**, not an option to adopt silently.
- ~~a baseline recorded by `TASK-3908`~~ — it does not exist; that absence is
  the reason this task exists.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "sdd/state/FEAT-720/spike-collect.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Run in the worktree, never the main checkout.** The main checkout is shared
  with other sessions; round 2 was blocked here for exactly that reason.
- **Revert before committing.** `git checkout -- pyproject.toml && git checkout -- packages/`
  then confirm `git status --porcelain` shows only the new evidence file.
- Use `-p no:randomly` on every collect so item counts are comparable.
- `--collect-only` only. Do **not** run the suites: several are slow and
  `parrot-formdesigner` is red for unrelated reasons.
- Record the exit code **and** the item count per root. An exit of 0 with a
  changed count is still a regression.

### Pattern to Follow
```bash
# baseline, per root, BEFORE any change
for d in packages/*/tests; do
  out=$(python -m pytest "$d" --collect-only -q -p no:randomly 2>&1 | tail -3)
  printf '%s\trc=%s\t%s\n' "$d" "$?" "$(echo "$out" | tr '\n' ' ')"
done
```

### References in Codebase
- `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md` §2 — breakage classes (i)–(vi)
- `sdd/tasks/completed/` / the FEAT-618 branch — `TASK-3908`'s round-2 block, the
  measurement this task supersedes

---

## Implementation Blueprint

### Steps (in order)
1. Create the worktree and confirm `git status --porcelain` is empty — *why*: a
   dirty tree makes the before/after diff meaningless.
2. Capture the baseline matrix for all 28 roots — *why*: this is the measurement
   round 2 could not take, and the only way to attribute `ai-parrot`'s exit 4.
3. Apply strategy (a): `git rm` the 25 top-level `__init__.py`, add
   `--import-mode=importlib` to `addopts` — *why*: the import mode alone does not
   fix the collision (verified), so both halves must be present to measure (a).
4. Capture the after matrix with the identical command — *why*: only an identical
   command makes the counts comparable.
5. Diff the two matrices and classify every new error into (i)–(vi) — *why*:
   TASK-4592/4593/4594 are scoped from this classification.
6. Revert every product change and verify only the evidence file remains — *why*:
   this task must not land the change; TASK-4591 does, under its own review.
7. Write the verdict line — *why*: TASK-4591 is gated on `CONFIRMED` and must not
   start on prose.

### `sdd/state/FEAT-720/spike-collect.md` (CREATE)
```markdown
# FEAT-720 M1 spike — strategy (a) re-measurement

**Run at**: <UTC ISO-8601>
**Worktree**: .claude/worktrees/feat-FEAT-720-tests-test-wheel-layout-tech-debt-2
**Base commit**: <git rev-parse --short HEAD>
**pytest**: 9.1.1

## 1. Baseline — before any change

| Package test root | rc | items | notes |
|---|---|---|---|
<!-- FILL IN: one row per all 28 packages/*/tests roots — bounded by AC2 (the
     after-matrix must match these item counts exactly) -->

## 2. After strategy (a)

Applied: 25 top-level `packages/*/tests/__init__.py` deleted;
`--import-mode=importlib` appended to the root `addopts`.

| Package test root | rc | items | delta vs baseline |
|---|---|---|---|
<!-- FILL IN: the same 28 rows — bounded by AC2 -->

## 3. New errors, classified

| Site (path:line) | Class (i)–(vi) | What broke | Proposed repair |
|---|---|---|---|
<!-- FILL IN: one row per NEW error only — bounded by spec §2's six classes.
     Anything fitting none of them is a NEW class: record it here AND report it,
     because the spec must be amended before TASK-4592 starts. -->

## 4. Per-class tally

| Class | Round 2 (2026-10-01) | This run | Owning task |
|---|---|---|---|
| (i) `from tests.<x>` | 34 files | <!-- FILL IN --> | 4592 / 4593 / 4594 |
| (ii) relative, no parent package | — | <!-- FILL IN --> | per dist |
| (iii) prepend-mode `sys.path` | — | <!-- FILL IN --> | per dist |
| (iv) relative imports in test files | 343 / 231 files | <!-- FILL IN --> | expected 0 changes |
| (v) dotted string targets | 68 | <!-- FILL IN --> | 4592 / 4593 |
| (vi) `tests/mcp` shadowing `mcp` | 1 | <!-- FILL IN --> | 4594 |

## 5. Open question from round 2

**Does `packages/ai-parrot`'s `--collect-only` exit 4 pre-exist strategy (a)?**

<!-- FILL IN: answer from §1 vs §2 — bounded by spec §8 Q1. If it pre-exists, it
     is NOT this feature's to fix: say so and name it for a separate issue. -->

## 6. Revert confirmation

```
$ git status --porcelain
<!-- FILL IN: must show ONLY sdd/state/FEAT-720/spike-collect.md -->
```

## 7. Verdict

<!-- FILL IN: exactly one of the two lines below, nothing else — bounded by AC10.
     STRATEGY (a) CONFIRMED
     STRATEGY (a) REFUTED — <why>
-->
```
**Why this shape**: the two matrices in §1/§2 are what AC2 compares, so they must
share a column layout and cover the same 28 roots; §3's classification is the
input TASK-4592–4594 are scoped from, so a row that fits no class must stop the
feature rather than be filed under a near-miss; §7's verdict is parsed by a human
before TASK-4591 starts, so it is a bare line with no hedging around it.

### FILL IN checklist
- [ ] §1 baseline matrix — all 28 roots; bounded by AC2
- [ ] §2 after matrix — identical command and columns; bounded by AC2
- [ ] §3 new errors classified into (i)–(vi); a new class stops the feature
- [ ] §4 per-class tally vs round 2
- [ ] §5 `ai-parrot` exit-4 attribution; bounded by spec §8 Q1
- [ ] §6 revert confirmation showing only the evidence file
- [ ] §7 verdict line; bounded by AC10

---

## Acceptance Criteria

- [ ] `sdd/state/FEAT-720/spike-collect.md` exists with all seven sections filled.
- [ ] The baseline matrix covers all 28 `packages/*/tests` roots.
- [ ] Every new error in §3 is classified into (i)–(vi), or the task reports a
      new class and stops.
- [ ] §5 answers whether `ai-parrot`'s exit 4 pre-exists the change, with both
      matrices as evidence.
- [ ] §6 shows `git status --porcelain` listing **only** the evidence file —
      no `pyproject.toml` change, no deleted `__init__.py`.
- [ ] §7 carries exactly one verdict line (AC10).
- [ ] `python -m pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`
      still passes 15/15 after the revert.

---

## Validation Commands

- `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`

---

## Test Specification

No test code. The deliverable is evidence. The one automated check is the
Validation Command above, which proves the revert restored a working tree.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt-2 --feature-id FEAT-720`)
2. **Read the spec** §2 for the six breakage classes before classifying anything
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run each command in "Verified facts"
   and correct the task file first if a number has moved
5. **Update status** in `sdd/tasks/index/tests-test-wheel-layout-tech-debt-2.json`
   → `"in-progress"` (set `started_at`), commit only that index file
6. **Measure, apply, measure, classify, revert** — in that order
7. **Verify** every acceptance criterion, especially the revert
8. **Commit the evidence file only** — `git add sdd/state/FEAT-720/spike-collect.md`
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4590 tests-test-wheel-layout-tech-debt-2 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
