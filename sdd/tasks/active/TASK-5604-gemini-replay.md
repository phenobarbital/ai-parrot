# TASK-5604: Gemini fallback command-outcome replay

**Feature**: FEAT-887 — SDD Experience Memory (experience.pitfall)
**Spec**: `sdd/specs/sdd-experience-memory.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5601
**Assigned-to**: unassigned

## Context

Implement Module 8 of the approved spec, with §2 behavioral contracts and §4 regression coverage. This task is a bounded portion of that module; its file table is authoritative.

## Scope

Pair tool_call arguments with tool_response in instance stream loop; map explicit error/status only and keep absent status unknown. Use per-attempt outcomes/session environment and replay once on exit. Preserve display projections and provider schema validation. Gemini gets no hook registration.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from collections.abc import Mapping
from parrot.flows.dev_loop.dispatchers.gemini import GeminiCodeDispatcher
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.fastpath import redact
from parrot.knowledge.wiki.experience.models import CommandOutcome
from pathlib import Path
from typing import Any
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py#GeminiCodeDispatcher.dispatch` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py:80`
```python
    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: Any,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
        labels: Optional[DispatchLabels] = None,
    ) -> T:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py#GeminiCodeDispatcher._stream_stdout_events` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py:286`
```python
    async def _stream_stdout_events(
        self,
        stdout: Any,
        *,
        stream_key: str,
        run_id: str,
        node_id: str,
    ) -> str:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py#GeminiCodeDispatcher._create_process` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py:276`
```python
    async def _create_process(self, command: Sequence[str], cwd: str) -> Any:
```

### Dependency Interfaces

gemini-replay: TASK-5601: consumes the interceptor contract in packages/ai-parrot/src/parrot/flows/dev_loop/experience.py, packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py#GeminiCodeDispatcher._create_process",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py#GeminiCodeDispatcher._stream_stdout_events",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py#GeminiCodeDispatcher.dispatch"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Pair tool_call arguments with tool_response in instance stream loop; map explicit error/status only and keep absent status unknown. Use per-attempt outcomes/session environment and replay once on exit. Preserve display projections and provider schema validation. Gemini gets no hook registration.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py:384 at 0c5acf0915.
# Anchor: elif event_type == "tool_response":
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py:286 at 0c5acf0915.
# Anchor:     async def _stream_stdout_events(
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py:276 at 0c5acf0915.
# Anchor:     async def _create_process(
from typing import Any
from collections.abc import Mapping
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.models import CommandOutcome
from parrot.knowledge.wiki.experience.fastpath import redact

def _experience_outcome(event: Mapping[str, Any], *, command: str, observation_id: str) -> CommandOutcome:
    """Map explicit Gemini outcome fields, retaining absence as unknown."""
    status = event.get("status")
    error = event.get("error")
    ok: bool | None = None
    if status == "error" or error:
        ok = False
    elif status == "success" or ("error" in event and error is False):
        ok = True
    return CommandOutcome(
        command=command, ok=ok,
        error=redact(str(event.get("result") or ""))[:400],
        observation_id=observation_id,
    )

# In dispatch: allocate local outcomes, tool-call argument map and interceptor.
# Extend _stream_stdout_events with optional per-attempt context. Pair tool_call
# and tool_response by the actual stream tool ID; only run_command is eligible.
# In the instance loop call _experience_outcome with the retained CommandLine;
# leave static display projection unchanged. No structured status -> unknown.
# Extend _create_process with optional env: copy os.environ and set the attempt
# PARROT_EXPERIENCE_SESSION without mutating parent process environment.
# In finally: await interceptor.replay(outcomes) exactly once and retain cleanup.
# FILL IN: confirm fixture keys against current stream mapping; AC1-AC3.
```

**Why**: This file owns the gemini-replay behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py:23 at 0c5acf0915.
# Anchor: class _AsyncBytesStream:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.dispatchers.gemini import GeminiCodeDispatcher

@pytest.mark.asyncio
async def test_gemini_outcomes_collected(tmp_path: Path) -> None:
    """Verify gemini outcomes collected. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_gemini_unknown_outcome(tmp_path: Path) -> None:
    """Verify gemini unknown outcome. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_gemini_replays_failed_attempt(tmp_path: Path) -> None:
    """Verify gemini replays failed attempt. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the gemini-replay behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/gemini.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: paired command arguments, explicit failed/success/unknown statuses, missing call correlation, per-attempt isolation and replay on exceptional exit.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_gemini_dispatcher.py -q`

## Test Specification

Required behavioral cases: paired command arguments, explicit failed/success/unknown statuses, missing call correlation, per-attempt isolation and replay on exceptional exit.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5604` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
