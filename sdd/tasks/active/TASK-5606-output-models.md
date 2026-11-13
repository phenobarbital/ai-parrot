# TASK-5606: Briefing and authored lesson output fields

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5590
**Assigned-to**: unassigned

## Context

Implement Module 9 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Add TaskScopedBrief.experience_briefing, NativePrep.experience_briefing and DevelopmentOutput.lessons with safe defaults and LessonDraft typing. Preserve existing extra handling and constructor compatibility. Validate generated strict Codex schema includes nested lessons without changing dispatcher behavior.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from parrot.flows.dev_loop.dispatchers.codex import _strict_output_schema
from parrot.flows.dev_loop.models.base import DevelopmentOutput, TaskScopedBrief
from parrot.flows.dev_loop.sdd_coder.models import NativePrep
from parrot.knowledge.wiki.experience.models import LessonDraft
from pathlib import Path
from pydantic import Field
from typing import List
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#TaskScopedBrief` — `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:478`
```python
class TaskScopedBrief(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#DevelopmentOutput` — `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:527`
```python
class DevelopmentOutput(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep` — `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:456`
```python
class NativePrep(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#_strict_output_schema` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:81`
```python
def _strict_output_schema(schema: Any) -> Any:
```

### Dependency Interfaces

output-models: TASK-5590: consumes the event-schemas contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#_strict_output_schema",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#DevelopmentOutput",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#TaskScopedBrief",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#NativePrep"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Add TaskScopedBrief.experience_briefing, NativePrep.experience_briefing and DevelopmentOutput.lessons with safe defaults and LessonDraft typing. Preserve existing extra handling and constructor compatibility. Validate generated strict Codex schema includes nested lessons without changing dispatcher behavior.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:491 at 0c5acf0915.
# Anchor: validation_verdict: str = Field(
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:561 at 0c5acf0915.
# Anchor: merge_performed: bool = Field(
from typing import List
from pydantic import Field
from parrot.knowledge.wiki.experience.models import LessonDraft
# Add inside TaskScopedBrief alongside validation_verdict:
experience_briefing: str = Field("", description="Known pitfalls for this task.")
# Add inside DevelopmentOutput alongside merge_performed:
lessons: List[LessonDraft] = Field(default_factory=list, description="Candidate lessons learned during this attempt.")
```

**Why**: This file owns the output-models behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:470 at 0c5acf0915.
# Anchor: validation_verdict: str = ""
# Add inside NativePrep alongside validation_verdict:
experience_briefing: str = ""
```

**Why**: This file owns the output-models behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py:15 at 0c5acf0915.
# Anchor: def _orchestrator_loop(body: str) -> str:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.models.base import DevelopmentOutput, TaskScopedBrief
from parrot.flows.dev_loop.sdd_coder.models import NativePrep
from parrot.flows.dev_loop.dispatchers.codex import _strict_output_schema

def test_brief_field_reaches_prompt(tmp_path: Path) -> None:
    """Verify brief field reaches prompt. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_lessons_field_in_codex_schema(tmp_path: Path) -> None:
    """Verify lessons field in codex schema. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_output_models_backward_compatible(tmp_path: Path) -> None:
    """Verify output models backward compatible. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the output-models behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: old payload compatibility, independent empty lesson lists, invalid drafts, JSON roundtrip and Codex strict schema.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worker_prompt_orchestrator.py -q`

## Test Specification

Required behavioral cases: old payload compatibility, independent empty lesson lists, invalid drafts, JSON roundtrip and Codex strict schema.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5606` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
