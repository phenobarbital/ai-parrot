# TASK-3674: Add TypedDict schema contracts and parity test to profile_execution.py

**Feature**: FEAT-596 — profile-execution-schema-contract
**Spec**: sdd/specs/profile-execution-schema-contract.spec.md
**Status**: pending
**Priority**: medium
**Depends-on**: none
**Assigned-to**: unassigned

## Context

`profile_execution.py` duck-types the event/transcript JSON schemas without any
formal contract. This task pins the schemas via TypedDicts and adds a parity test
that breaks if `WorkflowEvent` drifts from the profiler's expectations.

## Scope

1. Add `ProfileEventRecord` and `ProfileTranscriptRow` TypedDicts to
   `scripts/sdd/profile_execution.py` capturing every field the module reads.
2. Add `test_event_schema_parity_with_workflow_event` to the existing test file
   that asserts the event TypedDict's keys are a subset of `WorkflowEvent.model_fields`.
3. Add `test_transcript_row_schema_documents_expected_fields` validating transcript
   keys match the test fixtures.

## Files to Create/Modify

- `scripts/sdd/profile_execution.py` — MODIFY: add TypedDicts
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py` — MODIFY: add parity tests

## Acceptance Criteria

- [ ] `ProfileEventRecord` TypedDict names: kind, execution_id, task_id, attempt_uid, job_id, timestamp, source, payload
- [ ] `ProfileTranscriptRow` TypedDict names: role, request_id, message_id, timestamp, tool_name, tool_input, usage, process_id, is_tool_result
- [ ] Parity test imports `WorkflowEvent` and validates event field subset
- [ ] Existing tests pass unchanged
- [ ] No runtime import of `parrot.*` in `profile_execution.py`

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py -v`

## Completion Note

**Completed**: 2026-10-16 — verified, no new code in this task's close.

The implementation had already landed on `dev` in commit `7df515370`
(`feat(FEAT-596): pin profile_execution.py event/transcript schema contract`,
2026-09-23), but the index still showed TASK-3674 as `pending`. `/sdd-start`
confirmed each acceptance criterion against that code instead of re-implementing it:

- `ProfileEventRecord` and `ProfileTranscriptRow` TypedDicts present in
  `scripts/sdd/profile_execution.py` with the required field names.
- `test_event_schema_parity_with_workflow_event` and
  `test_transcript_row_schema_documents_expected_fields` present in
  `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py`.
- `pytest .../test_execution_profile.py` → 5 passed (PYTHONPATH=packages/ai-parrot/src,
  compiled `.so` copied into the worktree).
- No `parrot.*` import in `profile_execution.py`.

Only SDD state (index + this file) changed on this branch.
