# TASK-5597: Idempotent graduation and owning-ledger retirement

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5593
**Assigned-to**: unassigned

## Context

Implement Module 10 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Implement graduation_issue_id and graduate using the existing ledger. Require confirmed current-revision thresholds, compute deterministic ID, get before open, then append graduation. Repair an issue-open/event-write crash. Retire only closed issues owned by this shared-root ledger. Serialize the operation under index.lock without nested lock deadlocks.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/tests/knowledge/wiki/experience/test_graduation.py` | CREATE | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from parrot.knowledge.wiki.experience.graduation import graduate, graduation_issue_id
from parrot.knowledge.wiki.experience.models import Lesson
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.ledger.events import compute_issue_id
from parrot.knowledge.wiki.ledger.service import LedgerService
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#compute_issue_id` — `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:96`
```python
def compute_issue_id(kind: str, title: str, discovered_from: str) -> str:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService` — `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:149`
```python
class LedgerService:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.get_issue` — `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:336`
```python
    async def get_issue(self, issue_id: str) -> dict[str, Any] | None:
```

- `sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.open_issue` — `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:243`
```python
    async def open_issue(
        self,
        title: str,
        body: str,
        kind: IssueKind = "bug",
        severity: str = "minor",
        discovered_from: str = "",
        about: list[str] | None = None,
        actor: str = "agent:sdd",
    ) -> str:
```

### Dependency Interfaces

graduation: TASK-5593: consumes the service contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/knowledge/wiki/experience/test_graduation.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/experience/test_graduation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#compute_issue_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.get_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.open_issue"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Implement graduation_issue_id and graduate using the existing ledger. Require confirmed current-revision thresholds, compute deterministic ID, get before open, then append graduation. Repair an issue-open/event-write crash. Retire only closed issues owned by this shared-root ledger. Serialize the operation under index.lock without nested lock deadlocks.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py` (CREATE)

```python
"""Host-only graduation with deterministic ledger identity."""
from __future__ import annotations
from parrot.knowledge.wiki.experience.models import Lesson
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.ledger.events import compute_issue_id
from parrot.knowledge.wiki.ledger.service import LedgerService

def graduation_issue_id(lesson: Lesson) -> str:
    """Return the deterministic recurring-pitfall issue ID."""
    trigger = lesson.draft.trigger
    title = f"Recurring pitfall {lesson.lesson_id}: {trigger.executable} {trigger.subcommand}"
    return compute_issue_id("tech_debt", title, f"experience:{lesson.lesson_id}")

async def graduate(service: ExperienceService, ledger: LedgerService, *, ledger_name: str) -> list[str]:
    """Open qualifying issues and retire closed issues owned by this ledger."""
    # FILL IN: serialize, get before open, append only after success; AC1-AC3.
    # FILL IN: current-revision thresholds, crash repair and ownership; §2 Graduation.
```

**Why**: This file owns the graduation behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/knowledge/wiki/experience/test_graduation.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.knowledge.wiki.experience.graduation import graduate, graduation_issue_id

@pytest.mark.asyncio
async def test_graduate_opens_one_issue(tmp_path: Path) -> None:
    """Verify graduate opens one issue. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_graduate_recovers_after_crash(tmp_path: Path) -> None:
    """Verify graduate recovers after crash. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_graduate_foreign_ledger_not_retired(tmp_path: Path) -> None:
    """Verify graduate foreign ledger not retired. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_closed_issue_retires_lesson(tmp_path: Path) -> None:
    """Verify closed issue retires lesson. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the graduation behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/experience/graduation.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/experience/test_graduation.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: threshold boundaries, retry and crash repair, exact issue identity, foreign ledger never retires, local closed issue retirement and current revision accounting.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/experience/test_graduation.py -q`

## Test Specification

Required behavioral cases: threshold boundaries, retry and crash repair, exact issue identity, foreign ledger never retires, local closed issue retirement and current revision accounting.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5597` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
