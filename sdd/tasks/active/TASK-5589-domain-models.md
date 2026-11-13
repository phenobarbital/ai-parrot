# TASK-5589: Lesson domain models and experience configuration

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5588
**Assigned-to**: unassigned

## Context

Implement Module 1 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Create the category/state/tier/source aliases, LessonTrigger, LessonDraft, Lesson, CommandOutcome and ExperienceConfig exactly as §2. Use Pydantic v2, extra=forbid except Lesson, and default factories for lists. Keep normalization in the later event-schema task.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from parrot.knowledge.wiki.experience import models
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

No existing class/function is consumed beyond the standard library and declared dependencies. Existing edit anchors are quoted per file below.

### Dependency Interfaces

domain-models: TASK-5588: consumes the fastpath contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/__init__.py, packages/ai-parrot/src/parrot/knowledge/wiki/experience/fastpath.py

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
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py",
      "action": "CREATE"
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
2. Apply the per-file starting points and complete the scoped behavior — Create the category/state/tier/source aliases, LessonTrigger, LessonDraft, Lesson, CommandOutcome and ExperienceConfig exactly as §2. Use Pydantic v2, extra=forbid except Lesson, and default factories for lists. Keep normalization in the later event-schema task.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` (CREATE)

```python
"""Experience domain schemas."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

LessonCategory = Literal['pitfall']
LessonState = Literal['candidate', 'confirmed', 'quarantined', 'retired']
LessonTier = Literal['repo', 'global']
LessonSource = Literal['paired', 'authored', 'mined']
class LessonTrigger(BaseModel):
    """LessonTrigger schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    executable: str
    subcommand: str = ''
    error_signature: str = ''
    error_excerpt: str = ''
    command_example: str = ''
class LessonDraft(BaseModel):
    """What an agent or the pairing logic submits. extra='forbid'."""
    model_config = ConfigDict(extra='forbid')
    category: LessonCategory = 'pitfall'
    trigger: LessonTrigger
    symptom: str = ''
    solution: str
    fix_example: str = ''
    scope_paths: list[str] = Field(default_factory=list)
class Lesson(BaseModel):
    """Reduced view; never persisted as a source of truth."""
    lesson_id: str
    draft: LessonDraft
    solution_rev: str
    revisions: list[str]
    tier: LessonTier
    state: LessonState
    hits: int
    validations: int
    refutations: int
    sessions: int
    issue_id: str = ''
    issue_ledger: str = ''
    recorded_by: str
    recorded_at: str
class CommandOutcome(BaseModel):
    """CommandOutcome schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    command: str
    ok: bool | None
    error: str = ''
    observation_id: str = ''
class ExperienceConfig(BaseModel):
    """ExperienceConfig schema for experience memory."""
    model_config = ConfigDict(extra='forbid')
    enabled: bool = True
    confirm_sessions: int = 2
    quarantine_refutations: int = 2
    graduate_hits: int = 5
    graduate_sessions: int = 3
    brief_max_entries: int = 5
    brief_token_budget: int = 400
    inject_min_score: float = 0.35
    advice_cooldown_seconds: int = 600
    max_triggers_bytes: int = 262144
    max_transcript_tail_bytes: int = 262144
    max_session_pending: int = 32
    pairing_excluded_executables: list[str] = ['pytest', 'ruff', 'mypy', 'black', 'pylint', 'vitest', 'cargo', 'grep', 'rg', 'ls', 'cat', 'find', 'test', 'head', 'tail', 'wc']
```

**Why**: This file owns the domain-models behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience import models

def test_domain_defaults_and_factories(tmp_path: Path) -> None:
    """Verify domain defaults and factories. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_domain_extra_fields_forbidden(tmp_path: Path) -> None:
    """Verify domain extra fields forbidden. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

def test_command_outcome_unknown(tmp_path: Path) -> None:
    """Verify command outcome unknown. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the domain-models behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/models.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: all defaults, bounds, independent mutable defaults, unknown fields, tri-state outcomes and exact literal sets.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_models.py -q`

## Test Specification

Required behavioral cases: all defaults, bounds, independent mutable defaults, unknown fields, tri-state outcomes and exact literal sets.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5589` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
