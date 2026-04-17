# TASK-726: Integration Tests

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-717, TASK-718, TASK-719, TASK-720, TASK-721, TASK-722, TASK-723, TASK-724, TASK-725
**Assigned-to**: unassigned

---

## Context

Implements spec Module 10. End-to-end integration tests covering the full lifecycle: conversation creation, turn saving, artifact persistence, API endpoints, auto-save, graceful degradation, and cascade deletion.

---

## Scope

- Create integration test suite in `tests/storage/test_integration_artifact_persistence.py`
- Test full conversation lifecycle: create thread → add turns → list → load → delete
- Test artifact lifecycle: save → list → get → update → delete
- Test S3 overflow: large artifact → verify S3 upload + DynamoDB ref
- Test cascade deletion: delete thread → verify both tables cleaned
- Test graceful degradation: mock DynamoDB unavailable → verify warnings, no crash
- Test API endpoints end-to-end (if test infrastructure supports it)
- All tests use mocked DynamoDB and S3 (no real AWS calls)

**NOT in scope**: Performance benchmarks, load testing, real AWS integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/storage/test_integration_artifact_persistence.py` | CREATE | Integration test suite |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.storage import ChatStorage
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.dynamodb import ConversationDynamoDB
from parrot.storage.s3_overflow import S3OverflowManager
from parrot.storage.models import (
    Artifact, ArtifactType, ArtifactCreator, ArtifactSummary,
    ThreadMetadata, CanvasDefinition, CanvasBlock, CanvasBlockType,
)
```

---

## Acceptance Criteria

- [ ] All integration tests pass: `pytest tests/storage/test_integration_artifact_persistence.py -v`
- [ ] Full conversation lifecycle tested
- [ ] Full artifact lifecycle tested
- [ ] S3 overflow tested
- [ ] Cascade deletion tested
- [ ] Graceful degradation tested
- [ ] No real AWS calls (all mocked)

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — ALL prior tasks must be completed
2. **Read** the completed implementations to understand actual interfaces
3. **Write** comprehensive integration tests
4. **Run**: `pytest tests/storage/ -v` to verify everything works together

---

## Completion Note

*(Agent fills this in when done)*
