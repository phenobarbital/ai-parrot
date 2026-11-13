# TASK-5603: Agy command-outcome replay with shared parser

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

Reuse landed FEAT-888 parse_agy_tool_step and AgyToolStep in instance stream loop. Accept DONE run_command only, dedup step updates, derive status from fastpath.agy_exit_code(step.output or '') rather than step.exit_code. Preserve unknown command/output/index conservatively; use conversationId:stepIdx aliases consistent with hook observations and exported attempt session. Replay on every exit.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from collections.abc import Mapping
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher, parse_agy_tool_step
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.fastpath import agy_exit_code, redact
from parrot.knowledge.wiki.experience.models import CommandOutcome
from pathlib import Path
from typing import Any
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher.dispatch` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:236`
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

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._stream_stdout_events` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:527`
```python
    async def _stream_stdout_events(
        self,
        stdout: Any,
        *,
        stream_key: str,
        run_id: str,
        node_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._create_process` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:509`
```python
    async def _create_process(self, command: Sequence[str], cwd: str) -> Any:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#AgyToolStep` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:68`
```python
class AgyToolStep(BaseModel):
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#parse_agy_tool_step` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:116`
```python
def parse_agy_tool_step(step_update: Any) -> Optional[AgyToolStep]:
```

### Dependency Interfaces

agy-replay: TASK-5601: consumes the interceptor contract in packages/ai-parrot/src/parrot/flows/dev_loop/experience.py, packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#AgyToolStep",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._create_process",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher._stream_stdout_events",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#GoogleCodingDispatcher.dispatch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py#parse_agy_tool_step"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Reuse landed FEAT-888 parse_agy_tool_step and AgyToolStep in instance stream loop. Accept DONE run_command only, dedup step updates, derive status from fastpath.agy_exit_code(step.output or '') rather than step.exit_code. Preserve unknown command/output/index conservatively; use conversationId:stepIdx aliases consistent with hook observations and exported attempt session. Replay on every exit.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:674 at 0c5acf0915.
# Anchor: elif step_type == "tool_response":
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:527 at 0c5acf0915.
# Anchor:     async def _stream_stdout_events(
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:509 at 0c5acf0915.
# Anchor:     async def _create_process(
from typing import Any
from collections.abc import Mapping
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.models import CommandOutcome
from parrot.knowledge.wiki.experience.fastpath import agy_exit_code, redact

def _experience_outcome(event: Mapping[str, Any], *, conversation_id: str) -> CommandOutcome | None:
    """Convert a terminal agy tool step using the shared FEAT-888 parser."""
    step = parse_agy_tool_step(event.get("step_update"))
    if step is None or not step.done or step.name != "run_command":
        return None
    if step.step_index is None or not step.command:
        return None
    code = agy_exit_code(step.output or "")
    return CommandOutcome(
        command=step.command,
        ok=None if code is None else code == 0,
        error=redact(step.command_output or "")[:400],
        observation_id=f"{conversation_id}:{step.step_index}",
    )

# In dispatch: use local per-attempt outcomes, seen step indices and interceptor.
# Pass this context into _stream_stdout_events using optional keyword arguments,
# preserving existing callers. Call _experience_outcome before display publication.
# Capture the stream's actual conversation identity; do not substitute an attempt
# ID for the conversationId portion of an observation. With no identity, do not
# invent a colliding observation; retain enough pending context until known.
# Dedup DONE updates by step_index. Do not use AgyToolStep.exit_code/is_error.
# Extend _create_process with optional env; copy os.environ and set
# PARROT_EXPERIENCE_SESSION=attempt_uid. Preserve DEVNULL stdin and stream limits.
# In finally: await interceptor.replay(outcomes) once, preserving cleanup/errors.
# FILL IN: exact dispatch-local plumbing and exception tests; AC1-AC3.
```

**Why**: This file owns the agy-replay behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py:27 at 0c5acf0915.
# Anchor: class _AsyncBytesStream:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher, parse_agy_tool_step

@pytest.mark.asyncio
async def test_agy_tool_step_outcomes_collected(tmp_path: Path) -> None:
    """Verify agy tool step outcomes collected. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_agy_outcome_header_cannot_be_spoofed(tmp_path: Path) -> None:
    """Verify agy outcome header cannot be spoofed. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_agy_replay_attempt_identity(tmp_path: Path) -> None:
    """Verify agy replay attempt identity. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the agy-replay behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: ACTIVE/DONE repeated updates, output spoofing, missing headers/optional output, parser reuse, stable observation IDs, child environment and exception replay.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -q`

## Test Specification

Required behavioral cases: ACTIVE/DONE repeated updates, output spoofing, missing headers/optional output, parser reuse, stable observation IDs, child environment and exception replay.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5603` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
