# TASK-1691: Verify jira test suite regression fix (TASK-1689 + TASK-1690 combined)

**Feature**: FEAT-268 — jiraspecialist-prompt-builder-stub-leak
**Spec**: `sdd/specs/jiraspecialist-prompt-builder-stub-leak.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1689, TASK-1690
**Assigned-to**: unassigned

---

## Context

TASK-1689 (scope the conftest `sys.modules` leak) and TASK-1690 (defensive
`getattr` guard in `JiraSpecialist.__init__`) are two independent,
complementary fixes for the `AttributeError: 'JiraSpecialist' object has no
attribute '_prompt_builder'` bug diagnosed in the FEAT-268 spec. This task
verifies the combined fix end-to-end and confirms no regressions were
introduced in either the jira test suite or the broader `packages/ai-parrot`
test suite (since TASK-1689 touches shared test infrastructure used well
beyond the jira tests).

---

## Scope

- Run each of the four previously-failing test files individually and
  confirm all pass:
  ```bash
  pytest packages/ai-parrot/tests/test_jira_assignment.py -v
  pytest packages/ai-parrot/tests/test_jiratoolkit_defaults.py -v
  pytest packages/ai-parrot/tests/test_jira_ticket_created.py -v
  pytest packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py -v
  ```
- Run them all together (order-dependence was part of the original bug —
  confirm it's actually gone, not just hidden by isolation):
  ```bash
  pytest packages/ai-parrot/tests/test_jira_assignment.py \
         packages/ai-parrot/tests/test_jiratoolkit_defaults.py \
         packages/ai-parrot/tests/test_jira_ticket_created.py \
         packages/ai-parrot/tests/test_jiraspecialist_prompt_builder.py \
         packages/ai-parrot/tests/test_jira_transition_dispatch.py -v
  ```
- Confirm FEAT-265's own suite is still green:
  ```bash
  pytest packages/ai-parrot/tests/test_jira_transition_dispatch.py -v
  # expect: 46 passed
  ```
- Run the full `packages/ai-parrot/tests/` suite (or as much of it as
  reasonably completes — note in the Completion Note if pre-existing,
  unrelated collection errors block a full run, per the FEAT-265 post-merge
  review which already found 23 unrelated collection errors on this repo)
  and confirm no NEW failures compared to the pre-FEAT-268 baseline.
- Confirm every test identified by TASK-1689 as depending on the fake stub
  leak still passes after being converted to the opt-in fixture.

**NOT in scope**:
- Fixing any newly-discovered unrelated failures — file a separate follow-up
  if something new turns up that isn't caused by TASK-1689/1690.
- Modifying any code — this is a verification-only task.

---

## Files to Create / Modify

None — this is a verification-only task. No files are created or modified
(aside from this task file itself moving from `active/` to `completed/`).

---

## Codebase Contract (Anti-Hallucination)

N/A — verification task, no new code references needed beyond what TASK-1689
and TASK-1690 already establish.

---

## Acceptance Criteria

- [ ] `test_jira_assignment.py` — all pass, in isolation.
- [ ] `test_jiratoolkit_defaults.py` — all pass, in isolation.
- [ ] `test_jira_ticket_created.py` — all pass, in isolation.
- [ ] `test_jiraspecialist_prompt_builder.py` — all pass, in isolation.
- [ ] All five jira test files above (including
      `test_jira_transition_dispatch.py`) pass when run together in one
      pytest invocation (order-dependence check).
- [ ] `test_jira_transition_dispatch.py` — still 46/46 passing (no FEAT-265 regression).
- [ ] Full `packages/ai-parrot/tests/` suite shows no NEW failures versus the
      pre-FEAT-268 baseline (pre-existing unrelated failures/collection
      errors are out of scope and should be noted, not fixed).

---

## Test Specification

```python
# No new test code. This task runs the existing test suite and reports
# results in the Completion Note below.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/jiraspecialist-prompt-builder-stub-leak.spec.md` for full context.
2. **Check dependencies** — verify TASK-1689 and TASK-1690 are in
   `sdd/tasks/completed/` before starting.
3. **Run the verification commands** listed in Scope above, capturing actual
   output (pass/fail counts) for each.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **If everything passes**: mark this task done, and note in the
   Completion Note that FEAT-268 is fully verified.
6. **If something still fails**: do NOT mark this task (or the feature) done.
   Document exactly what still fails in the Completion Note, and flag
   whether it points back to a gap in TASK-1689 or TASK-1690's
   implementation (in which case those tasks should be reopened) or to a
   genuinely new, unrelated issue (in which case file it separately).
7. **Move this file** to `sdd/tasks/completed/TASK-1691-verify-jira-prompt-builder-fix.md`.
8. **Update the per-spec index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: Actual pytest output/pass-fail counts for each verification
command above.

**Deviations from spec**: none | describe if any
