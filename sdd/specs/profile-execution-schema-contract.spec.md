# FEAT-596: Pin profile_execution.py event/transcript schema contract

---
type: feature
base_branch: dev
feature_id: FEAT-596
status: approved
---

## 1. Problem Statement

`scripts/sdd/profile_execution.py` (FEAT-584 / TASK-3574) deliberately avoids importing
`WorkflowEvent` from `parrot.flows.dev_loop.sdd_coder.optimization_models` to keep the
offline profiler framework-decoupled. However, the event and transcript row schemas it
duck-types are entirely coder-invented — documented only in the module docstring and inline
comments, with no formal contract or drift-detection mechanism.

If `WorkflowEvent` adds, renames, or removes fields, the profiler silently drifts. The same
risk applies to the transcript row shape consumed from host transcripts.

## 2. Proposed Solution

Pin the profiler's expected schemas via:

1. **`TypedDict` definitions** in `profile_execution.py` for the event record and
   transcript row shapes the profiler consumes. These serve as in-module documentation
   and type-checking anchors without introducing a runtime import of the framework.

2. **A contract parity test** (`test_execution_profile.py`) that imports both
   `WorkflowEvent` (the authoritative Pydantic model) and the profiler's `TypedDict`
   definitions, then asserts that every field the profiler expects exists on
   `WorkflowEvent` with a compatible type. This test breaks on drift.

The profiler continues to duck-type at runtime (no `WorkflowEvent` import in production
code), but the contract is now machine-verified on every test run.

## 3. Modules

### M1: Schema TypedDicts + parity test

**Files**:
- `scripts/sdd/profile_execution.py` — MODIFY: add `ProfileEventRecord` and
  `ProfileTranscriptRow` TypedDicts capturing the expected field names and types.
  Update internal helpers to use these as type annotations where practical.
- `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_profile.py` — MODIFY:
  add `test_event_schema_parity_with_workflow_event` that validates the profiler's
  `ProfileEventRecord` fields are a subset of `WorkflowEvent.model_fields`, and
  `test_transcript_row_schema_documents_expected_fields` that validates the transcript
  TypedDict keys are present in existing test fixtures.

## 4. Acceptance Criteria

- [ ] AC1: `ProfileEventRecord` TypedDict in `profile_execution.py` names every field
  the module reads from event records (kind, execution_id, task_id, attempt_uid, job_id,
  timestamp, source, payload).
- [ ] AC2: `ProfileTranscriptRow` TypedDict names every field the module reads from
  transcript rows (role, request_id, message_id, timestamp, tool_name, tool_input, usage,
  process_id, is_tool_result).
- [ ] AC3: A parity test imports `WorkflowEvent` and asserts that every key in
  `ProfileEventRecord.__required_keys__ | ProfileEventRecord.__optional_keys__` (excluding
  profiler-only fields like `message_id`) exists in `WorkflowEvent.model_fields`.
- [ ] AC4: Existing profiler tests still pass unchanged.
- [ ] AC5: No runtime import of `optimization_models` or any `parrot.*` module in
  `profile_execution.py`.

## 5. Out of Scope

- Changing the profiler's runtime behavior or output schema.
- Modifying `WorkflowEvent` or `optimization_models.py`.
- Adding transcript schema to `optimization_models.py` (transcript is host-specific,
  not an sdd_coder contract).

## 6. Risks

- Low: the TypedDicts add ~20 lines of type annotations to an already-documented module.

## 7. Ledger

- Resolves `issue:c18364799aa9` (tech_debt/minor: "profile_execution.py event/transcript
  schema is coder-invented, not a pinned contract").
