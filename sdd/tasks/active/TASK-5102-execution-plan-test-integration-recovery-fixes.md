# TASK-5102: Version plan-node writes when no turn session is bound

**Feature**: FEAT-789 execution-plan-test-integration-recovery-fixes
**Spec**: `sdd/specs/execution-plan-test-integration-recovery-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:ca325f05ae53`

## Context
Implements M1 of the spec. Fresh-process plan recovery restores nothing because plan-node writes made
outside a turn session drop the version that the enabled catalog created.

## Scope
- `PlanToolNode._store`: split the fallback branch — `catalog is None` → unchanged `store_result`;
  enabled catalog without session/producer → `await catalog.aput_generic(...)` and return
  `_Written(estimate_bytes(payload), str(_evidence_ref(v.artifact_id, v.version)), False)`.
- Regression test for AC-2/AC-3 next to the existing execution-plan tests.

**NOT in scope**: opening turn sessions for background runs; test-file warnings.

## Files to Modify
- `packages/ai-parrot/src/parrot/bots/flows/plan/node.py`
- `packages/ai-parrot/tests/tools/execution_plan/test_store_versions_without_session.py` (new)

## Codebase Contract
- `PlanToolNode._store(self, key, payload, *, index, producer_call_id=None, tool=None) -> _Written` (node.py:515)
- `PlanToolNode._enabled_catalog()` (node.py:659); `_current_session()` (node.py:1078); `_evidence_ref(artifact_id, version)` (node.py)
- `_Written(byte_size, version, degraded)` NamedTuple (node.py:986)
- `PlanWorkingMemoryCatalog.aput_generic(key, data, *, entry_type=None, description, metadata, ...)` → entry with `.version_metadata.artifact_id/.version` (working_memory/internals.py:1074)
- Does NOT exist: any turn session opened by `ExecutionPlanToolkit._run_plan`.

## Acceptance Criteria
Spec AC-1..AC-4.

## Validation Commands
```bash
PYTHONPATH=$PWD/packages/ai-parrot/src pytest packages/ai-parrot/tests/tools/execution_plan -q
ruff check packages/ai-parrot/src/parrot/bots/flows/plan/node.py packages/ai-parrot/tests/tools/execution_plan/test_store_versions_without_session.py
```

## Completion Note
