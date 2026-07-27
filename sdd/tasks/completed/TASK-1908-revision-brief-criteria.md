# TASK-1908: RevisionBrief carries acceptance criteria — revision QA beyond lint

**Feature**: FEAT-377 — Graph Engineering Hardening
**Spec**: `sdd/specs/graphindex-as-engineering-devloop.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 item 3 (spec §3). `RevisionBrief` does not carry the original
feature's acceptance criteria, so `run_revision` synthesizes a lint-only
`WorkBrief` (comment at `runner.py:653`) — revision runs verify almost
nothing.

---

## Scope

- Add `acceptance_criteria: Optional[List[AcceptanceCriterion]] = None` to
  `RevisionBrief` (`models.py:283-305`). `None` preserves legacy lint-only
  behavior exactly.
- In `run_revision` (`runner.py:594-673`): when `brief.acceptance_criteria`
  is a non-empty list, build the synthetic `WorkBrief` with those criteria
  PLUS the existing lint `ShellCriterion`; when `None`/empty, keep today's
  lint-only synthesis byte-for-byte.
- Update the revision-trigger path(s) that construct `RevisionBrief` (grep
  for `RevisionBrief(` call sites) to pass criteria through when available —
  if no caller has them available yet, leave callers unchanged and note it
  (graph memory write-back, TASK-1915, is the future source).
- Unit tests: with-criteria and without-criteria paths.

**NOT in scope**: persisting criteria in graph memory (TASK-1915);
revision-mode topology changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` | MODIFY | new optional field on `RevisionBrief` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `run_revision` criteria pass-through |
| `packages/ai-parrot/tests/flows/dev_loop/test_runner_revision.py` | MODIFY/CREATE | both paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import RevisionBrief, AcceptanceCriterion, WorkBrief
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:283-305
class RevisionBrief(BaseModel):
    repo_path: str; branch: str; pr_number: int; repository: str
    jira_issue_key: str; feedback: str; head_sha: str   # ALL currently required

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:138,180
class WorkBrief(BaseModel):
    acceptance_criteria: List[AcceptanceCriterion]   # min_length=1 — the synthetic
    # brief must ALWAYS have >= 1 criterion (lint counts)

# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:594-599
async def run_revision(self, brief: RevisionBrief, *, run_id: Optional[str] = None) -> FlowResult:
# line 653 comment: "criteria are not carried on RevisionBrief, so QA re-runs a lint gate"
# line ~673: synthesizes ShellCriterion(name="lint", command="ruff check .")
```

### Does NOT Exist
- ~~`RevisionBrief.acceptance_criteria`~~ — this task adds it
- ~~a criteria store the revision trigger can read~~ — run snapshots/graph memory land in TASK-1915; do not invent one

### Contract correction (found during implementation, 2026-07-26)
- The test-file scope named `test_runner_revision.py` (MODIFY/CREATE), but
  no such file exists; the real `run_revision` end-to-end coverage lives in
  `test_revision_mode.py` (verified via `ls`/grep). Extended that file
  in place with the two both-paths tests instead of creating a duplicate
  new file.

---

## Implementation Notes

### Key Constraints
- Backward compatible: existing constructors of `RevisionBrief` must keep
  working without the new field.
- `WorkBrief.acceptance_criteria` has `min_length=1` — appending the lint
  criterion to carried criteria satisfies it in both paths.
- Update the `runner.py:653` comment to reflect the new behavior.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/models.py` — `AcceptanceCriterion` union (flowtask/shell/manual kinds; check `CriterionResult.kind` Literal at line 475)

---

## Acceptance Criteria

- [ ] `RevisionBrief(acceptance_criteria=[...])` → revision QA runs those criteria + lint
- [ ] `RevisionBrief()` without the field → behavior identical to today (lint-only)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/` clean

---

## Test Specification

```python
async def test_run_revision_with_criteria(stub_flow):
    """Carried criteria appear in the synthesized WorkBrief alongside lint."""

async def test_run_revision_without_criteria(stub_flow):
    """None → single lint ShellCriterion, exactly as before."""
```

---

## Agent Instructions

1. **Read the spec** for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/graphindex-as-engineering-devloop.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill the Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-26
**Notes**:
- Added `RevisionBrief.acceptance_criteria: Optional[List[AcceptanceCriterion]]
  = None` (default preserves legacy behavior exactly).
- `run_revision` now builds the synthetic `WorkBrief.acceptance_criteria`
  as `[*(brief.acceptance_criteria or []), ShellCriterion(name="lint", ...)]`
  — carried criteria run alongside lint when present, lint-only otherwise.
  Updated the stale `runner.py` comment above the construction site.
- Checked all `RevisionBrief(` call sites (grep): only
  `webhook.py::RevisionWebhookHandler._build_brief` constructs one, from a
  webhook payload with no criteria data available — left unchanged per the
  task's explicit fallback instruction ("if no caller has them available
  yet, leave callers unchanged and note it"); TASK-1915's graph memory
  write-back is the intended future source.
- Tests added to `test_revision_mode.py` (see Codebase Contract correction
  above for the filename discrepancy): `test_run_revision_with_criteria`
  and `test_run_revision_without_criteria`, both driving the real
  `run_revision()` through a capturing fake dispatcher and inspecting the
  `_QABrief.acceptance_criteria` actually handed to the `sdd-qa` dispatch
  (2 entries carried+lint vs. 1 entry lint-only).
- `pytest packages/ai-parrot/tests/flows/dev_loop/ -m "not live"` (minus
  the pre-existing `hypothesis`-missing file): 652 passed, 1 skipped, same
  one pre-existing unrelated test-order-dependent failure noted in
  TASK-1906/1907.
- `ruff check` clean on all touched files.

**Deviations from spec**: none beyond the test-file-location correction above.
