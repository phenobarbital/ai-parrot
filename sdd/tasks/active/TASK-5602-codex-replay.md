# TASK-5602: Codex command-outcome replay

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

Collect completed command_execution items inside instance stream loop, not display projection. Export per-attempt session in subprocess env, normalize wrapped shell commands, redact aggregated_output, retain unknown exit status. Generate normalized command digest plus occurrence aliases consistent with hook capture. Replay once on every attempt exit, including failures/review profiles, without changing output validation or cancellation cleanup.

**NOT in scope**: Other task-owned files, new dependencies, changing public signatures fixed by the spec, or implementing the future procedure plane.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` | MODIFY | Scoped deliverable |
| `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py` | MODIFY | Task-specific regression coverage |

## Codebase Contract

Verified against `0c5acf0915`. Existing references below were re-read during decomposition. New experience imports are dependency-provided interfaces, not claims of pre-existing code.

### Verified Imports

```python
from collections.abc import Mapping
from hashlib import sha1
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.fastpath import redact
from parrot.knowledge.wiki.experience.models import CommandOutcome
from pathlib import Path
from typing import Any
import pytest
```

Standard-library imports use Python's installed library; Pydantic v2 is declared in packages/ai-parrot/pyproject.toml and pytest in root pyproject.toml. Existing project symbols are anchored below. New symbols are fixed by the matching producer blueprint and must be verified after dependencies land.

### Existing Signatures to Use

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher.dispatch` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:269`
```python
    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: CodexCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
        labels: Optional[DispatchLabels] = None,
    ) -> T:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher._stream_stdout_events` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:662`
```python
    async def _stream_stdout_events(
        self,
        stdout: Any,
        *,
        stream_key: str,
        run_id: str,
        node_id: str,
        codec: Optional[CodexUsageCodec] = None,
    ) -> str:
```

- `sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher._create_process` — `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:600`
```python
    async def _create_process(self, command: Sequence[str]) -> Any:
```

### Dependency Interfaces

codex-replay: TASK-5601: consumes the interceptor contract in packages/ai-parrot/src/parrot/flows/dev_loop/experience.py, packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py

### Does NOT Exist

- `parrot sdd task start` is not a CLI verb; task-start priming is workflow prose.
- Experience functionality is new; imported producer symbols must be rechecked after dependencies land.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher._create_process",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher._stream_stdout_events",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py#CodexCodeDispatcher.dispatch"
  ]
}
```

## Implementation Notes

Use async service calls and bounded IO. Keep stdlib hook imports lazy, preserve the exception/cancellation semantics of callers, and log through the module logger. Blueprint gaps are planning instructions only: delivered code must contain no unfinished placeholders. All tests use temporary roots; do not mutate real global experience data. Each asset writer owns its packaged twins.

## Implementation Blueprint

### Steps (in order)

1. Verify the existing anchors and dependency interfaces — they fix the allowed integration surface.
2. Apply the per-file starting points and complete the scoped behavior — Collect completed command_execution items inside instance stream loop, not display projection. Export per-attempt session in subprocess env, normalize wrapped shell commands, redact aggregated_output, retain unknown exit status. Generate normalized command digest plus occurrence aliases consistent with hook capture. Replay once on every attempt exit, including failures/review profiles, without changing output validation or cancellation cleanup.
3. Exercise the listed failure and boundary cases — these protect the feature's event, sandbox and host contracts.
4. Run the task's validation commands and inspect the diff — commit only declared files and task state.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:783 at 0c5acf0915.
# Anchor: if item_type == "command_execution":
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:662 at 0c5acf0915.
# Anchor:     async def _stream_stdout_events(
# Anchor occurrences: 1; verified packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:600 at 0c5acf0915.
# Anchor:     async def _create_process(
from typing import Any
from collections.abc import Mapping
from hashlib import sha1
from parrot.flows.dev_loop.experience import ExperienceInterceptor
from parrot.knowledge.wiki.experience.models import CommandOutcome
from parrot.knowledge.wiki.experience.fastpath import redact

def _experience_outcome(item: Mapping[str, Any], *, occurrence: int) -> CommandOutcome | None:
    """Convert one completed command item; preserve unknown exit status."""
    if item.get("type") != "command_execution" or not isinstance(item.get("command"), str):
        return None
    command = item["command"]
    # FILL IN: unwrap bash -lc/sh -c before hashing, preserving actual command arguments.
    code = item.get("exit_code")
    return CommandOutcome(
        command=command,
        ok=code == 0 if type(code) is int else None,
        error=redact(str(item.get("aggregated_output") or ""))[:400],
        observation_id=f"{sha1(command.encode()).hexdigest()[:8]}#{occurrence}",
    )

# In dispatch: create a local outcomes list, seen completion-ID set, occurrence
# counters and ExperienceInterceptor(session=attempt_uid, cwd=cwd, seat="codex").
# Extend the instance stream method with optional keyword outcomes/context so
# existing standalone callers retain defaults; never store state across attempts.
# On item.completed in that stream, dedup item.id before incrementing occurrence,
# call _experience_outcome, and append known or unknown outcomes in event order.
# Extend _create_process with an optional env argument; pass a COPY of os.environ
# containing PARROT_EXPERIENCE_SESSION=attempt_uid. Preserve existing subprocess IO.
# In dispatch finally: await interceptor.replay(outcomes) once before cleanup;
# isolate replay errors while retaining original cancellation/error propagation.
# FILL IN: occurrence aliases match hook capture; AC1-AC3 and M8 identity contract.
```

**Why**: This file owns the codex-replay behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py` (MODIFY)

```python
# Anchor occurrences: 1; verified packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py:27 at 0c5acf0915.
# Anchor: class _AsyncBytesStream:
# Add tests beside the existing cases; do not replace the quoted fixture/class.
"""Deterministic experience-memory regression tests."""
from pathlib import Path
import pytest
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher

@pytest.mark.asyncio
async def test_codex_outcomes_collected(tmp_path: Path) -> None:
    """Verify codex outcomes collected. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_codex_review_replays(tmp_path: Path) -> None:
    """Verify codex review replays. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.

@pytest.mark.asyncio
async def test_codex_occurrence_alias_dedup(tmp_path: Path) -> None:
    """Verify codex occurrence alias dedup. """
    # FILL IN: arrange isolated fixtures and assert behavior, including failure paths;
    # use Test Specification and AC1-AC3, never a tautological/mock-only assertion.
```

**Why**: This file owns the codex-replay behavior described in Scope. Preserve its existing callers and complete only the bounded cases in this task.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py` — finish its marked branches/examples using Scope and Test Specification.
- [ ] `packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py` — finish its marked branches/examples using Scope and Test Specification.

## Acceptance Criteria

- [ ] AC1: All declared files implement Scope using the spec's exact public interfaces; existing behavior remains compatible.
- [ ] AC2: The stated no-op, bounded IO, trust and error-handling constraints hold; no new dependency or unrelated file is introduced.
- [ ] AC3: command_execution fields, missing exit code unknown, repeated commands distinct, duplicate completed item dedup, review ignore-user-config replay, per-attempt isolation, child env and replay on error.
- [ ] AC4: All Validation Commands pass; applicable asset twins remain synchronized.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py -q`

## Test Specification

Required behavioral cases: command_execution fields, missing exit code unknown, repeated commands distinct, duplicate completed item dedup, review ignore-user-config replay, per-attempt isolation, child env and replay on error.

Use the spec §4 payload fixtures, with deterministic temporary Git roots and PARROT_HOME. Assert state/events/outputs, including unknown outcomes and failures; mocks alone are not evidence. Each test file listed above belongs to this task. Preserve all existing regression cases in modified tests.

## Agent Instructions

1. Use `$sdd-start TASK-5602` and the feature worktree; do not implement on dev.
2. Verify dependencies are done in `sdd/tasks/index/sdd-experience-memory.json` and recheck this contract after they land.
3. Implement only the declared files, run validation, and commit scoped changes.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; never edit them manually.
