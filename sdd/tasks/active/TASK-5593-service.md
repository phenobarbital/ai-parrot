# TASK-5593: Experience service and confirmed-only briefings

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5592
**Assigned-to**: unassigned

## Context

Implement Module 2 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Provide the exact ExperienceService facade. Route raw drafts before basename normalization; honor repo scope, redact and append candidate revisions. Use deterministic failure matching and bounded escaped data formatting; briefing uses confirmed lessons only, maximum five and configured token budget. Missing plane, disabled configuration and operational errors yield benign results. Refresh on CLI/task-start paths only.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from collections.abc import Sequence
from parrot.knowledge.wiki.experience.fastpath import append_event, leading_command, redact
from parrot.knowledge.wiki.experience.index import ExperienceIndex
from parrot.knowledge.wiki.experience.models import Lesson, LessonDraft, LessonSource, LessonState, LessonTier
from parrot.knowledge.wiki.experience.reducer import match_score
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.identity import authoring_identity
from parrot.knowledge.wiki.project import find_shared_root, WikiProjectConfig
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root` — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:1563`
```python
def find_shared_root(start: Path | None = None) -> Path | None:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig` — `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:589`
```python
class WikiProjectConfig(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/identity.py#authoring_identity` — `packages/ai-parrot/src/parrot/knowledge/wiki/identity.py:7`
```python
def authoring_identity(by: str | None) -> str:
```

### Dependency Interfaces

service: TASK-5592: consumes the index contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/index.py, packages/ai-parrot/src/parrot/knowledge/wiki/project.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/identity.py#authoring_identity",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#find_shared_root"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Provide the exact ExperienceService facade. Route raw drafts before basename normalization; honor repo scope, redact and append candidate revisions. Use deterministic failure matching and bounded escaped data formatting; briefing uses confirmed lessons only, maximum five and configured token budget. Missing plane, disabled configuration and operational errors yield benign results. Refresh on CLI/task-start paths only.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py` (CREATE)

```python
"""Experience service facade; all public methods fail open."""
from __future__ import annotations
from collections.abc import Sequence
from pathlib import Path
from parrot.knowledge.wiki.experience.models import Lesson, LessonDraft, LessonSource, LessonState, LessonTier
from parrot.knowledge.wiki.experience.index import ExperienceIndex
from parrot.knowledge.wiki.experience.reducer import match_score
from parrot.knowledge.wiki.experience.fastpath import append_event, leading_command, redact
from parrot.knowledge.wiki.project import find_shared_root, WikiProjectConfig
from parrot.knowledge.wiki.identity import authoring_identity

class ExperienceService:
    """Facade over the repo-plane index and append-only logs."""
    @classmethod
    def from_root(cls, root: Path | None = None) -> ExperienceService:
        """Resolve the shared-root service, including a benign unavailable state."""
        # FILL IN: establish state and logger; AC1 missing/disabled plane.
    async def refresh(self) -> None:
        """Refresh stale generations off the hook path."""
        # FILL IN: bounded index rebuild; AC2 error isolation.
    async def record(self, draft: LessonDraft, *, session: str, source: LessonSource, seat: str = "") -> str:
        """Append a redacted candidate and return its identity."""
        # FILL IN: route raw scope/executable before normalization; AC3.
    async def match_failure(self, command: str, error: str, *, session: str) -> Lesson | None:
        """Read the best published deterministic match without rebuilding."""
        # FILL IN: family/Jaccard threshold and §2 tie rules; AC3.
    async def brief(self, title: str, files: Sequence[str], *, max_entries: int | None = None) -> str:
        """Return confirmed-only bounded bullets, or an empty string."""
        # FILL IN: FTS ranking, escaped data and token budget; AC3.
    async def list_lessons(self, *, state: LessonState | None = None, tier: LessonTier | None = None) -> list[Lesson]:
        """Return current reduced lessons filtered by state and tier."""
        # FILL IN: published-generation read; AC1.
    async def get_lesson(self, lesson_id: str) -> Lesson | None:
        """Return a reduced lesson if available."""
        # FILL IN: published-generation read; AC1.
    async def retire(self, lesson_id: str, *, reason: str) -> bool:
        """Append terminal retirement without deleting history."""
        # FILL IN: validated redacted retirement event; AC3.
```

**Why**: This file owns the service behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience.service import ExperienceService

@pytest.mark.asyncio
async def test_service_tier_routing(tmp_path: Path) -> None:
    """Verify service tier routing. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_brief_max_five_confirmed_only(tmp_path: Path) -> None:
    """Verify brief max five confirmed only. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_service_missing_plane(tmp_path: Path) -> None:
    """Verify service missing plane. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_match_failure_never_refreshes(tmp_path: Path) -> None:
    """Verify match failure never refreshes. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the service behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: raw tier routing, missing/disabled plane, stable tie ordering, candidate exclusion, token/entry limits, retire, no refresh during match_failure and service error isolation.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_service.py -q`

## Test Specification

Required behavioral cases: raw tier routing, missing/disabled plane, stable tie ordering, candidate exclusion, token/entry limits, retire, no refresh during match_failure and service error isolation.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5593` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
