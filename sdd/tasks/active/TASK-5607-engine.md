# TASK-5607: Experience briefing and authored capture in engine attempts

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5593, TASK-5599, TASK-5606
**Assigned-to**: unassigned

## Context

Implement Module 9 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Implement _experience_briefing_for and _record_lessons at exact construction/return sites. Refresh off-hook, populate both TaskScopedBrief and NativePrep, record returned lessons as authored candidates with actual attempt session/seat. Keep coder_feedback byte-identical. Fail experience operations open without masking original task errors.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from parrot.flows.dev_loop.models.base import DevelopmentOutput
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import PlannedTask
from parrot.knowledge.wiki.experience.service import ExperienceService
from pathlib import Path
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._feedback_for` — `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2743`
```python
    async def _feedback_for(self, ctx: _FeatureCtx, task: PlannedTask, backend: str, model: str) -> str:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#_FeatureCtx` — `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:277`
```python
class _FeatureCtx:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#DevelopmentOutput` — `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:527`
```python
class DevelopmentOutput(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#PlannedTask` — `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:331`
```python
class PlannedTask(BaseModel):
```

### Dependency Interfaces

engine: TASK-5593: consumes the service contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/service.py; TASK-5599: consumes the cli contract in packages/ai-parrot/src/parrot/sdd/scripts/experience_cli.py, packages/ai-parrot/src/parrot/sdd/cli.py; TASK-5606: consumes the output-models contract in packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py, packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#DevelopmentOutput",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._feedback_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#_FeatureCtx",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#PlannedTask"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Implement _experience_briefing_for and _record_lessons at exact construction/return sites. Refresh off-hook, populate both TaskScopedBrief and NativePrep, record returned lessons as authored candidates with actual attempt session/seat. Keep coder_feedback byte-identical. Fail experience operations open without masking original task errors.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:3865 at 0c5acf0915.
# Anchor: validation_verdict=verdict or "",
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2622 at 0c5acf0915.
# Anchor: return NativePrep(
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:3975 at 0c5acf0915.
# Anchor: return record, output, error, manager, branch, path
from parrot.flows.dev_loop.sdd_coder.models import PlannedTask
from parrot.flows.dev_loop.models.base import DevelopmentOutput
from parrot.knowledge.wiki.experience.service import ExperienceService

async def _experience_briefing_for(self, ctx: _FeatureCtx, task: PlannedTask) -> str:
    """Return task-scoped known pitfalls, or empty text on disabled/error paths."""
    # FILL IN: extract actual title/files, refresh off-hook, then brief; AC1-AC3.

async def _record_lessons(self, ctx: _FeatureCtx, task: PlannedTask, output: DevelopmentOutput,
                          *, session: str, seat: str) -> int:
    """Persist authored candidate drafts from an attempt; return stored count."""
    # FILL IN: actual attempt identity, fail-open per draft; AC1-AC3.

# Pass experience_briefing as a separate keyword in TaskScopedBrief and NativePrep.
# Invoke _record_lessons before the existing attempt return, after output is available.
# Do not append to coder_feedback or alter review-exposure accounting.
```

**Why**: This file owns the engine behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py:19 at 0c5acf0915.
# Anchor: class FakeDispatcher:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

@pytest.mark.asyncio
async def test_record_lessons_from_output(tmp_path: Path) -> None:
    """Verify record lessons from output. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_engine_briefing_both_seats(tmp_path: Path) -> None:
    """Verify engine briefing both seats. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_engine_feedback_unchanged(tmp_path: Path) -> None:
    """Verify engine feedback unchanged. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the engine behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: MCP and native briefing fields, disabled/error/no-plane branches, authored candidate capture, attempt identity, unchanged feedback and output return behavior.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`

## Test Specification

Required behavioral cases: MCP and native briefing fields, disabled/error/no-plane branches, authored candidate capture, attempt identity, unchanged feedback and output return behavior.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5607` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
