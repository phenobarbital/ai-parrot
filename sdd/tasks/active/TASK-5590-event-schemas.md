# TASK-5590: Per-kind event schemas and revision identity

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5588, TASK-5589
**Assigned-to**: unassigned

## Context

Implement Module 1 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Extend domain models with every ExperienceEventKind, ExperienceEvent, seven payload classes, EVENT_PAYLOADS, validate_event and solution_rev_for. Re-redact all textual fields before identity; reject unknown envelope/payload fields, unknown kinds, invalid versions and serialized overflow. Source provenance is not trusted from serialized fields. Add a nonserialized Pydantic PrivateAttr named _shared_attestation, default False, to ExperienceEvent. Only the trusted source loader sets it after validation; JSON cannot author it.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from collections.abc import Mapping
from parrot.knowledge.wiki.experience import models
from parrot.knowledge.wiki.experience.fastpath import leading_command, normalize_error, redact
from pathlib import Path
from pydantic import PrivateAttr
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

No existing class/function is consumed beyond the standard library and declared dependencies. Existing edit anchors are quoted per file below.

### Dependency Interfaces

event-schemas: TASK-5588: consumes the fastpath contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py, packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py; TASK-5589: serializes writes to packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py, packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Extend domain models with every ExperienceEventKind, ExperienceEvent, seven payload classes, EVENT_PAYLOADS, validate_event and solution_rev_for. Re-redact all textual fields before identity; reject unknown envelope/payload fields, unknown kinds, invalid versions and serialized overflow. Source provenance is not trusted from serialized fields. Add a nonserialized Pydantic PrivateAttr named _shared_attestation, default False, to ExperienceEvent. Only the trusted source loader sets it after validation; JSON cannot author it.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` (MODIFY)

```python
# Planned dependency-created anchor; not present at decomposition HEAD.
# Verify after TASK-5589 lands; do not claim a current occurrence count.
# Append event declarations after existing domain classes.
from collections.abc import Mapping
from pydantic import PrivateAttr
from parrot.knowledge.wiki.experience.fastpath import leading_command, normalize_error, redact

ExperienceEventKind = Literal['lesson.recorded', 'failure.observed', 'lesson.injected', 'lesson.validated', 'lesson.refuted', 'lesson.confirmed', 'lesson.quarantined', 'lesson.graduated', 'lesson.retired']
class ExperienceEvent(BaseModel):
    """extra='forbid'. The reducer drops any line that fails validation."""
    model_config = ConfigDict(extra='forbid')
    _shared_attestation: bool = PrivateAttr(default=False)
    schema_version: int = 1
    event_id: str
    kind: ExperienceEventKind
    lesson_id: str = ''
    session: str
    observation_id: str = ''
    actor: str
    seat: str = ''
    ts: str
    payload: dict[str, Any] = Field(default_factory=dict)
class RecordedPayload(BaseModel):
    """RecordedPayload schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    draft: LessonDraft
    solution_rev: str
    tier: LessonTier
    source: LessonSource
class FailurePayload(BaseModel):
    """FailurePayload schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    executable: str
    subcommand: str
    error_signature: str
    error_excerpt: str = ''
class InjectionPayload(BaseModel):
    """InjectionPayload schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    solution_rev: str
    state_at_injection: LessonState
class EvidencePayload(BaseModel):
    """EvidencePayload schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    solution_rev: str
    via: Literal['trigger_family', 'fix_family', 'rediscovery']
class AttestationPayload(BaseModel):
    """AttestationPayload schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    solution_rev: str
class GraduatedPayload(BaseModel):
    """GraduatedPayload schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    solution_rev: str
    issue_id: str
    ledger: str
class RetiredPayload(BaseModel):
    """RetiredPayload schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    reason: str
EVENT_PAYLOADS: dict[str, type[BaseModel]] = {
    "lesson.recorded": RecordedPayload,
    "failure.observed": FailurePayload,
    "lesson.injected": InjectionPayload,
    "lesson.validated": EvidencePayload,
    "lesson.refuted": EvidencePayload,
    "lesson.confirmed": AttestationPayload,
    "lesson.quarantined": AttestationPayload,
    "lesson.graduated": GraduatedPayload,
    "lesson.retired": RetiredPayload,
}

def validate_event(line: Mapping[str, Any]) -> ExperienceEvent | None:
    """Validate envelope and payload and re-redact every text field."""
    # FILL IN: exact per-kind schemas, limits and source-independent identity; AC1-AC3.

def solution_rev_for(draft: LessonDraft) -> str:
    """Hash normalized solution and the parsed fix family to eight hex characters."""
    # FILL IN: canonical UTF-8 identity from §2; AC1-AC3.
```

**Why**: This file owns the event-schemas behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` (MODIFY)

```python
# Planned dependency-created anchor; not present at decomposition HEAD.
# Verify after TASK-5589 lands; do not claim a current occurrence count.
# Append the new event-schema tests; preserve domain tests.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience import models

def test_validate_event_schemas(tmp_path: Path) -> None:
    """Verify validate event schemas. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_event_redaction_before_identity(tmp_path: Path) -> None:
    """Verify event redaction before identity. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_solution_revision_identity(tmp_path: Path) -> None:
    """Verify solution revision identity. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the event-schemas behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: all nine kinds, malformed envelope/payload combinations, re-redaction, UTF-8 byte limits, solution/fix-family revision identity.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py -q`

## Test Specification

Required behavioral cases: all nine kinds, malformed envelope/payload combinations, re-redaction, UTF-8 byte limits, solution/fix-family revision identity.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5590` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
