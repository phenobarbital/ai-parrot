---
type: Wiki Overview
title: 'TASK-1242: Run `tag_yaml_fixtures.py` and commit retagged YAML form fixtures'
id: doc:sdd-tasks-completed-task-1242-apply-bulk-tagger-to-fixtures-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'One-shot data step: now that the tagger script exists (TASK-1241), execute'
---

# TASK-1242: Run `tag_yaml_fixtures.py` and commit retagged YAML form fixtures

**Feature**: FEAT-183 — FormRegistry Multi-Tenancy
**Spec**: `sdd/specs/formregistry-multi-tenancy.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1241
**Assigned-to**: unassigned

---

## Context

One-shot data step: now that the tagger script exists (TASK-1241), execute
it against the repo's YAML form fixtures so every fixture under
`packages/parrot-formdesigner/tests/`, `examples/forms/`, and any other
fixture root carries `tenant: navigator`. This unblocks the rest of the
test suite once `require_tenant=True` becomes the default registry behavior
(landed by TASK-1239).

The diff produced by this task is intentionally large but mechanical — each
modified YAML file gains one line.

---

## Scope

- Run `python -m scripts.sdd.tag_yaml_fixtures --dry-run` first; review the
  list of files that would be tagged. Spot-check 3-5 of them by opening the
  file to confirm the change makes sense (i.e. they are real form fixtures,
  not unrelated YAML).
- Run `python -m scripts.sdd.tag_yaml_fixtures` (no flags) to apply.
- Run `python -m scripts.sdd.tag_yaml_fixtures --dry-run` again to confirm
  idempotency — the second dry-run must report zero `tagged` files.
- Stage the changed YAML files and commit them with the message
  `sdd: tag form fixtures with tenant: navigator (FEAT-183)`.
- Do NOT touch any non-YAML file. Do NOT stage `scripts/sdd/tag_yaml_fixtures.py`
  (it was committed by TASK-1241).
- Run the existing test suite once after committing to confirm no regression:
  `pytest packages/parrot-formdesigner/tests/ -x -q` (early-exit + quiet).
- If any tests fail due to the added `tenant:` line (for example, a test
  that compares the full YAML body byte-for-byte), file the failures in
  the Completion Note and fix the affected tests in a small follow-up
  before completing this task.

**NOT in scope**:
- Modifying the tagger script (TASK-1241).
- Adding tenant to any non-form YAML (CI configs, etc.) — the script's
  `form_id`-presence heuristic already filters that out.
- Updating handlers/routers/tools (TASK-1243, TASK-1244).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/**/*.yaml` (subset) | MODIFY | Mechanically tagged with `tenant: navigator`. Exact list determined by running the script. |
| `examples/forms/**/*.yaml` (if present) | MODIFY | Same. |
| `tests/forms/**/*.yaml` (if present) | MODIFY | Same. |

No new files. No script edits.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

N/A — this is an execution-and-commit task; no imports added.

### Existing Signatures to Use

- `scripts/sdd/tag_yaml_fixtures.py:main()` — entry point delivered by TASK-1241.
  Signature: `def main(argv: list[str] | None = None) -> int`.

### Does NOT Exist

- ~~A separate `--commit` flag on the tagger~~ — the script does NOT commit.
  Staging and committing is a manual step in this task.
- ~~An auto-runner in CI~~ — out of scope.

---

## Implementation Notes

### Pattern to Follow

```bash
# 1. Dry-run first
python -m scripts.sdd.tag_yaml_fixtures --dry-run | tee /tmp/tag_dry.log
# Review /tmp/tag_dry.log for unexpected files (e.g. non-form YAMLs).

# 2. Apply
python -m scripts.sdd.tag_yaml_fixtures

# 3. Re-run dry to confirm idempotency
python -m scripts.sdd.tag_yaml_fixtures --dry-run
# Expected summary: tagged=0, already=<N>, ...

# 4. Stage ONLY the YAML diff
git reset HEAD
git status --porcelain | awk '/\.ya?ml$/ {print }' | xargs git add
git diff --cached --name-only   # verify only *.yaml / *.yml files staged

# 5. Run the package's tests
pytest packages/parrot-formdesigner/tests/ -x -q

# 6. Commit
git commit -m "sdd: tag form fixtures with tenant: navigator (FEAT-183)"
```

### Key Constraints

- Idempotency check is mandatory before committing.
- Verify the staged diff contains ONLY YAML files. The unrelated
  modifications in the working tree (per the spec author's working state)
  must NOT enter this commit.
- If tests fail due to YAML byte-comparison, the fix is one of:
  - Update the test to use a structural compare (deserialize-then-compare).
  - Update the test's expected fixture to include `tenant: navigator`.
  Pick the minimal change.

### References in Codebase

- `scripts/sdd/tag_yaml_fixtures.py` (created by TASK-1241).
- `packages/parrot-formdesigner/tests/` — test root that contains most
  form YAML fixtures.

---

## Acceptance Criteria

- [ ] All YAML form fixtures (files with `form_id:` at root) under the
      default roots carry a `tenant:` line.
- [ ] `python -m scripts.sdd.tag_yaml_fixtures --dry-run` reports zero
      `tagged` after the apply.
- [ ] The commit contains ONLY YAML file changes (no script changes, no
      unrelated source changes).
- [ ] `pytest packages/parrot-formdesigner/tests/ -x -q` passes (or any
      regressions are fixed in this task).
- [ ] Commit message: `sdd: tag form fixtures with tenant: navigator (FEAT-183)`.

---

## Test Specification

No unit tests added by this task — TASK-1241 covered the tagger's behavior.
This task's verification is the dry-run idempotency check plus the package
test suite.

---

## Agent Instructions

1. **Read the spec** §3 Module 3.
2. **Check dependencies**: TASK-1239 and TASK-1241 done.
3. **Activate the venv** per CLAUDE.md: `source .venv/bin/activate`.
4. **Dry-run** the tagger and inspect output.
5. **Apply** and verify idempotency with a second dry-run.
6. **Stage YAML-only** files; verify staged set.
7. **Run** the package tests; fix any regressions inline (minimal-diff).
8. **Commit** with the prescribed message.
9. **Move this file** to `sdd/tasks/completed/`.
10. **Update index** → `done`.
11. **Fill in the Completion Note** with the count of files tagged and
    any regressions encountered.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Files tagged: 0. No YAML form fixtures exist in the default roots
(packages/parrot-formdesigner/tests/, examples/forms/, tests/forms/). Consistent
with spec's resolved Open Question: "No forms currently exist in production."
Dry-run confirmed 0 tagged files. Second dry-run also 0 (idempotency trivially met).
No regressions — all 554 unit tests pass (1 pre-existing unrelated failure).

**Deviations from spec**: None. No YAML form fixture files needed tagging.
