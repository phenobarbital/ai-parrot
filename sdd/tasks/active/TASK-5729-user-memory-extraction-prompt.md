# TASK-5729: Constrain extraction to lasting user statements

**Feature**: FEAT-904 - Working automatic recall for user and episodic memory, proven end to end
**Spec**: `sdd/specs/user-memory-recall-e2e.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1–2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true

## Context

Bounded deliverable from approved FEAT-904, spec §§2–5. Implement M4's exact prompt-only change and deterministic assertion. Preserve parsing, provenance and identity restrictions.

## Scope

- Implement M4's exact prompt-only change and deterministic assertion. Preserve parsing, provenance and identity restrictions.

**NOT in scope**: Other tasks' targets; clients/base.py, conversation memory, review admission, storage schemas or new dependencies.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/user/extraction.py` | MODIFY | Constrain extraction to lasting user statements |
| `packages/ai-parrot/tests/memory/user/test_extraction.py` | MODIFY | Regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against `5012f298d91f06025f0900b7c84df1f5ad4f3db7`; recheck after dependency commits.

### Verified Imports

Standard-library imports are built-in. Pytest/Pydantic/aiosqlite are already declared in the workspace. Preserve existing imports in modified modules; add the listed verified imports used by new test functions (including Path/pytest) when missing.

```python
import pytest
from parrot.memory.user.extraction import extract_user_knowledge
```

### Dependency-created Imports

No unimplemented import is assumed before its dependency is complete.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/memory/user/extraction.py#extract_user_knowledge` — `packages/ai-parrot/src/parrot/memory/user/extraction.py:73`: `async def extract_user_knowledge(event: MemoryEvent, *, client: AbstractClient, model: str | None=None) -> list[UserKnowledgeCandidate]`
- `sym:packages/ai-parrot/tests/memory/user/test_extraction.py#FakeClient` — `packages/ai-parrot/tests/memory/user/test_extraction.py:18`: `class FakeClient()`
- `sym:packages/ai-parrot/tests/memory/user/test_extraction.py#_event` — `packages/ai-parrot/tests/memory/user/test_extraction.py:34`: `def _event(user_id: str | None='u1', **payload: Any) -> MemoryEvent`

### Does NOT Exist

- No separate task-instruction classifier or translation API is introduced.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/user/extraction.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/user/test_extraction.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/user/extraction.py#extract_user_knowledge",
    "sym:packages/ai-parrot/tests/memory/user/test_extraction.py#FakeClient",
    "sym:packages/ai-parrot/tests/memory/user/test_extraction.py#_event"
  ]
}
```

## Implementation Notes

Independent writer of user/extraction.py and its own test module.

Keep I/O async and close owned resources in finally. New Python uses strict hints, Google-style docstrings and black (120 columns). Store logs in artifacts/logs/. Do not change dependency manifests or shared conftest.py.



## Implementation Blueprint

Planning scaffolds intentionally leave bounded FILL IN decisions. Completed implementation files must contain no placeholders.

### Steps (in order)

1. Verify contracts and dependency outputs — upstream commits can move anchors.
2. Apply each declared block and complete bounded logic — keep behavior traceable to this task's acceptance criteria.
3. Implement the listed behavior tests and run validation — code inspection alone does not prove acceptance.
4. Inspect the diff and retain evidence — stage only declared implementation targets.

### `packages/ai-parrot/src/parrot/memory/user/extraction.py` (MODIFY)

```python
# Anchor: _SYSTEM_PROMPT = (
# occurrences: 1; grep -F -c verified at packages/ai-parrot/src/parrot/memory/user/extraction.py:25
# APPEND before 'Return [] when nothing qualifies.'; retain existing prompt sentences.
"Record only lasting statements about the user as a person. A request or instruction for the "
"current task (store this, name it that, do this now) is not user knowledge. "
"Write every value in the language the user used. "
```

**Why**: Task instructions are not durable preferences, and values should retain the user's language.

### `packages/ai-parrot/tests/memory/user/test_extraction.py` (MODIFY)

```python
# Anchor: class FakeClient:
# occurrences: 1; grep -F -c verified at packages/ai-parrot/tests/memory/user/test_extraction.py:18
# INSERT at module scope; reuse existing FakeClient and _event.
@pytest.mark.asyncio
async def test_extraction_prompt_rejects_task_instructions_and_keeps_language() -> None:
    """Verify the actual extraction call receives both rules without changing parsing."""
    client = FakeClient("[]")
    await extract_user_knowledge(_event(), client=client)
    # FILL IN: assert all added sentences in client.calls[0]["system_prompt"].
    # Retain the existing identity-exclusion and bounded JSON-output rules.
```

**Why**: Inspect the delivered prompt through the existing fake client; offline text checks do not prove model compliance.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/user/extraction.py`: complete the bounded block and satisfy all relevant ACs.
- [ ] `packages/ai-parrot/tests/memory/user/test_extraction.py`: complete the bounded block and satisfy all relevant ACs.

## Acceptance Criteria

- [ ] **AC-1**: All specified sentences occur before the empty-result instruction in the actual delivered prompt.
- [ ] **AC-2**: Existing malformed-output/cancellation/provenance/identity tests pass unchanged.
- [ ] **AC-3**: Live extraction-noise observations remain reporting only, not a deterministic acceptance claim.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/user/test_extraction.py -q`

## Test Specification

Use named blueprint cases as the acceptance matrix. Cover the adversarial boundaries in Scope/ACs and preserve existing regressions.

## Agent Instructions

1. Use the host session and feature worktree provisioned by `parrot sdd worktree ensure --slug user-memory-recall-e2e --feature-id FEAT-904`; never implement on dev.
2. Read the spec and confirm every dependency is done in `sdd/tasks/index/user-memory-recall-e2e.json`.
3. Re-verify contracts and use sdd-start lifecycle; never silently expand target files.
4. Activate the shared venv and set PYTHONPATH=packages/ai-parrot/src for worktree tests; never uv sync there.
5. Run scoped validation and applicable lint; retain logs in artifacts/logs/.
6. Commit implementation, then use parrot sdd task finalize with real TaskCompletionEvidence and exact implementation HEAD.
7. Inspect generated Completion Note and active-to-completed move; commit only task SDD state. Do not hand-edit completion state or push from the worker.

## Completion Note

Pending; the task finalizer generates this after implementation and validation.
