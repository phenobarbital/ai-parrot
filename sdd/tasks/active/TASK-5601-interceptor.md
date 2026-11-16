# TASK-5601: In-process experience advice and replay

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5595
**Assigned-to**: unassigned

## Context

Implement Module 7 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Implement ExperienceInterceptor after/replay, scoped per attempt. Read structured ok/exit_code only; call shared transitions through bounded non-blocking integration. Attach advice under experience_advice on run_command results. Replay missing observations in order, skip hook-covered observation aliases individually, return appended event count and mark mined source. Never infer success from text or mutate global process environment. Use a synchronous closure over loaded trigger stubs for on_outcome; never pass ExperienceService.match_failure directly because it is async.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/experience.py` | CREATE | Scoped deliverable |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py` | CREATE | Task-specific regression coverage |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from __future__ import annotations
from collections.abc import Mapping, Sequence
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.models import CommandOutcome
from parrot.knowledge.wiki.experience.service import ExperienceService
from parrot.knowledge.wiki.experience.transitions import on_outcome
from pathlib import Path
from typing import Any
import logging
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._run_tool` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:1520`
```python
    async def _run_tool(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        cwd: str,
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._tool_run_command` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:1956`
```python
    async def _tool_run_command(
        self,
        cwd: str,
        args: Dict[str, Any],
        profile: LLMCodeDispatchProfile,
    ) -> Dict[str, Any]:
```

### Dependency Interfaces

interceptor: TASK-5595: consumes the transitions contract in packages/ai-parrot/src/parrot/knowledge/wiki/experience/transitions.py

### Does NOT Exist

- `packages/ai-parrot/src/parrot/flows/dev_loop/experience.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py` — absent at 0c5acf0915; supplied by this task or its declared predecessor.
- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/experience.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._run_tool",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._tool_run_command"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Implement ExperienceInterceptor after/replay, scoped per attempt. Read structured ok/exit_code only; call shared transitions through bounded non-blocking integration. Attach advice under experience_advice on run_command results. Replay missing observations in order, skip hook-covered observation aliases individually, return appended event count and mark mined source. Never infer success from text or mutate global process environment. Use a synchronous closure over loaded trigger stubs for on_outcome; never pass ExperienceService.match_failure directly because it is async.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/flows/dev_loop/experience.py` (CREATE)

```python
"""Per-attempt interception and fallback replay."""
from __future__ import annotations
import logging
from collections.abc import Mapping, Sequence
from typing import Any
from parrot.knowledge.wiki.experience.models import CommandOutcome
from parrot.knowledge.wiki.experience.transitions import on_outcome
from parrot.knowledge.wiki.experience.service import ExperienceService

class ExperienceInterceptor:
    """Fail-open command advice and missing-observation replay."""
    def __init__(self, *, session: str, cwd: str, seat: str) -> None:
        """Bind immutable attempt identity and the shared-root service."""
        self.logger = logging.getLogger(__name__)
        # FILL IN: retain session/cwd/seat and unavailable-plane state; AC1.
    async def after(self, tool_name: str, tool_args: Mapping[str, Any], tool_result: Mapping[str, Any]) -> list[str]:
        """Observe structured run_command outcomes and return advisory data."""
        # FILL IN: exact run_command result semantics, unknown no-op; AC1-AC3.
    async def replay(self, outcomes: Sequence[CommandOutcome]) -> int:
        """Replay only hook-missed observations and count appended events."""
        # FILL IN: ordered replay, source mined and occurrence alias reconciliation; AC3.
```

**Why**: This file owns the interceptor behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:589 at 0c5acf0915.
# Anchor: tool_result = await self._run_tool(
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:595 at 0c5acf0915.
# Anchor: if tool_result.get("ok") is False:
from parrot.flows.dev_loop.experience import ExperienceInterceptor
# Create an interceptor per dispatch attempt, with actual session/cwd/seat.
# Immediately after the awaited _run_tool call and before error handling:
advice = await interceptor.after(tool_name, tool_args, tool_result)
if advice:
    tool_result = {**tool_result, "experience_advice": advice}
# FILL IN: use actual loop locals; preserve original result and error flow; AC1-AC3.
```

**Why**: This file owns the interceptor behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py` (CREATE)

```python
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.experience import ExperienceInterceptor

@pytest.mark.asyncio
async def test_interceptor_attaches_advice(tmp_path: Path) -> None:
    """Verify interceptor attaches advice. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_interceptor_structured_outcome_only(tmp_path: Path) -> None:
    """Verify interceptor structured outcome only. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the interceptor behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py:28 at 0c5acf0915.
# Anchor: class _Function:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.experience import ExperienceInterceptor

@pytest.mark.asyncio
async def test_interceptor_replay_per_observation(tmp_path: Path) -> None:
    """Verify interceptor replay per observation. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the interceptor behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/experience.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: tool result preservation, only run_command intercepted, structured/unknown outcomes, one hook-covered and one missed observation, codex repeated-command aliases, cancellation/error isolation and no-plane no-op.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_experience_interceptor.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -q`

## Test Specification

Required behavioral cases: tool result preservation, only run_command intercepted, structured/unknown outcomes, one hook-covered and one missed observation, codex repeated-command aliases, cancellation/error isolation and no-plane no-op.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5601` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
