# TASK-878: `ClaudeCodeDispatcher` core class

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-874, TASK-875, TASK-876, TASK-877
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** — the heart of FEAT-129. The dispatcher is the
thin orchestration layer between an `AgentsFlow` node and Claude Code:

1. Resolves a `ClaudeCodeDispatchProfile` into a populated
   `ClaudeAgentRunOptions` (incl. programmatic `agents=`,
   `setting_sources`, `cwd`, `permission_mode`, `allowed_tools`,
   `extra_args` for JSON-schema output).
2. Acquires a global `asyncio.Semaphore` sized by
   `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`.
3. Calls `LLMFactory.create("claude-agent:<model>")` to obtain a
   `ClaudeAgentClient`.
4. Iterates `client.ask_stream(...)`, wraps each event in a
   `DispatchEvent`, `XADD`s to `flow:{run_id}:dispatch:{node_id}` with
   `MAXLEN ~ floor(ttl_seconds/60)`.
5. On final `ResultMessage`, parses the concatenated `TextBlock` text
   from the last `AssistantMessage(s)` as JSON and validates against
   `output_model`. Raises `DispatchOutputValidationError` on failure.
6. Defense-in-depth: refuses dispatch when `cwd` is not under
   `WORKTREE_BASE_PATH` (spec §7 R4).

Spec sections: §2 "Overview" + "Component Diagram", §3 Module 2, §7
R1-R10, §6 "Codebase Contract".

---

## Scope

- Implement `parrot/flows/dev_loop/dispatcher.py` containing:
  - `class DispatchExecutionError(Exception)`
  - `class DispatchOutputValidationError(Exception)` with attribute
    `raw_payload: str` for the audit log.
  - `class ClaudeCodeDispatcher` with:
    - `__init__(*, max_concurrent: int, redis_url: str,
       stream_ttl_seconds: int)` — instantiates `asyncio.Semaphore`,
      stores config, lazily connects to Redis on first dispatch.
    - `async dispatch(*, brief: BaseModel, profile:
       ClaudeCodeDispatchProfile, output_model: Type[T], run_id: str,
       node_id: str, cwd: str) -> T`.
    - Internal `_resolve_run_options(profile, cwd) ->
      ClaudeAgentRunOptions` builder — public-but-underscore so unit
      tests can call it without dispatching.
    - Internal `_publish_event(stream_key, kind, payload) -> None`
      (XADD with MAXLEN approximation).
    - Internal `_validate_output(messages, output_model) -> T`.
- Use **best-effort JSON parsing first**, then **JSON-schema CLI flag**
  via `extra_args={"output-format": "json", "json-schema": <path>}`
  when `output_model` is supplied (resolves spec §8 open question:
  JSON-schema in v1). If the SDK does not honor the flag, fall back to
  best-effort parsing transparently. Document the fallback in code
  comments.
- The programmatic subagent dict is built from
  `_subagent_defs.load_subagent_definition(profile.subagent)` (TASK-877)
  wrapped in an `AgentDefinition` (lazily imported from
  `claude_agent_sdk.types`).
- Raise `DispatchExecutionError` on any uncaught exception from
  `ask_stream`; emit a `dispatch.failed` event before re-raising.

**NOT in scope**:
- The flow factory (TASK-886).
- The streaming multiplexer reading these events (TASK-879).
- Anything node-specific (TASKs 880-885).
- Resume on session crash — explicitly out of scope per spec §7 R8.
- A retry loop — explicitly out of scope per spec §1 Non-Goals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py` | CREATE | Dispatcher class + exceptions. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Re-export `ClaudeCodeDispatcher`, `DispatchExecutionError`, `DispatchOutputValidationError`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` | CREATE | Unit tests using mocked `ClaudeAgentClient`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from parrot.clients.factory import LLMFactory      # factory.py:38
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile, DispatchEvent,
)
from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

# Lazy SDK imports — only inside methods, never at module level.
# Type hints use forward refs:
if TYPE_CHECKING:
    from claude_agent_sdk.types import (
        AgentDefinition, AssistantMessage, ResultMessage, TextBlock,
        ToolUseBlock, ToolResultBlock,
    )

# Redis (asyncio) — already in core deps
import redis.asyncio as aioredis
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:                                  # factory.py:38
    @classmethod
    def create(cls, model_id: str, **kwargs) -> AbstractClient: ...
    # "claude-agent:claude-sonnet-4-6" returns a ClaudeAgentClient

# packages/ai-parrot/src/parrot/clients/claude_agent.py — AFTER TASK-875
class ClaudeAgentRunOptions(BaseModel):
    allowed_tools: Optional[List[str]]
    disallowed_tools: Optional[List[str]]
    permission_mode: Optional[str]                 # "default"|"acceptEdits"|"plan"|"bypassPermissions"
    cwd: Optional[str]
    agents: Optional[Dict[str, "AgentDefinition"]]
    setting_sources: Optional[List[str]]
    extra_args: Optional[Dict[str, Optional[str]]]
    system_prompt: Optional[str]

class ClaudeAgentClient(AbstractClient):
    async def ask_stream(
        self, prompt: str, *, options: Optional[ClaudeAgentRunOptions] = None,
        ...,
    ) -> AsyncIterator[Any]: ...    # yields AssistantMessage / UserMessage / SystemMessage / ResultMessage

# claude_agent_sdk.types (lazy-imported)
class AgentDefinition:
    description: str
    prompt: str
    tools: list[str] | None
    model: str | None
```

### Does NOT Exist

- ~~`ClaudeAgentClient.dispatch_subagent(...)`~~ — subagent binding is
  done via `ClaudeAgentRunOptions.agents={...}`, not a custom client
  method.
- ~~`ClaudeCodeDispatcher.retry()`~~ — retry semantics are out of scope.
- ~~`output_model.parse_raw(...)`~~ — Pydantic v1 name. Use
  `output_model.model_validate_json(text)`.
- ~~`redis.Redis(...)` (sync)~~ — must use `redis.asyncio.from_url(...)`.
- ~~`ClaudeAgentRunOptions.subagent`~~ — not a real field. Use
  `agents={profile.subagent: AgentDefinition(...)}`.

---

## Implementation Notes

### Profile → ClaudeAgentRunOptions resolver

Pseudocode (TASK-875 must be done):

```python
def _resolve_run_options(self, profile, cwd):
    self._enforce_cwd_under_worktree_base(cwd)         # spec §7 R4

    agents_dict = None
    system_prompt = None
    if profile.subagent is not None:
        # Lazy SDK import
        from claude_agent_sdk.types import AgentDefinition
        body = load_subagent_definition(profile.subagent)
        agents_dict = {
            profile.subagent: AgentDefinition(
                description=f"SDD {profile.subagent} subagent",
                prompt=body,
                tools=profile.allowed_tools or None,
                model=profile.model,
            )
        }
    else:
        system_prompt = profile.system_prompt_override

    extra_args = None
    if self._json_schema_path is not None:
        extra_args = {"output-format": "json",
                      "json-schema": self._json_schema_path}

    return ClaudeAgentRunOptions(
        cwd=cwd,
        permission_mode=profile.permission_mode,
        allowed_tools=profile.allowed_tools or None,
        agents=agents_dict,
        setting_sources=profile.setting_sources,
        extra_args=extra_args,
        system_prompt=system_prompt,
    )
```

The `_json_schema_path` is materialized once per dispatch call by
calling `output_model.model_json_schema()` and writing it to a tempfile.
On exception or completion the dispatcher cleans up the tempfile.

### Best-effort JSON parsing

Concatenate `TextBlock.text` from every `AssistantMessage` (in stream
order). Locate the last `{ ... }` JSON object via a balanced-brace
scanner (NOT regex — see brainstorm note about embedded braces).
`output_model.model_validate_json(text)`. On `ValidationError`, raise
`DispatchOutputValidationError(raw_payload=text)`.

### XADD + TTL

```python
maxlen = max(1, self.stream_ttl_seconds // 60)
await self._redis.xadd(stream_key, fields, maxlen=maxlen, approximate=True)
```

### cwd safety check

```python
def _enforce_cwd_under_worktree_base(self, cwd: str) -> None:
    base = os.path.abspath(config.WORKTREE_BASE_PATH)
    target = os.path.abspath(cwd)
    if os.path.commonpath([base, target]) != base:
        raise DispatchExecutionError(
            f"cwd {cwd!r} is not under WORKTREE_BASE_PATH={base!r}"
        )
```

### Event emission order

1. `dispatch.queued` — before semaphore acquire.
2. `dispatch.started` — after acquire, before `ask_stream`.
3. `dispatch.message` / `dispatch.tool_use` / `dispatch.tool_result` —
   one per relevant SDK message.
4. Either `dispatch.completed` (on success) or `dispatch.output_invalid`
   (on validation failure) or `dispatch.failed` (on exception).
5. Always release the semaphore in a `finally:` block.

### Key Constraints

- Async throughout; no blocking IO.
- Redis client lazily constructed and reused across dispatches.
- `self.logger = logging.getLogger(__name__)` — no print statements.
- Tests must run without `claude-agent-sdk` installed (mock
  `LLMFactory.create` to return a stub client whose `ask_stream` yields
  pre-canned messages — see fixture in spec §4 `fake_dispatch_messages`).

### References in Codebase

- `parrot/clients/factory.py:38` — `LLMFactory.create`.
- `parrot/clients/claude_agent.py` — extended in TASK-875.
- `parrot/flows/dev_loop/_subagent_defs.py` — TASK-877.

---

## Acceptance Criteria

- [ ] `from parrot.flows.dev_loop import ClaudeCodeDispatcher,
  DispatchExecutionError, DispatchOutputValidationError` succeeds.
- [ ] Importing the module does NOT trigger any
  `claude_agent_sdk` import (lazy guard).
- [ ] `_resolve_run_options(profile, cwd)` produces options with the
  documented shape (verified by `test_dispatch_profile_to_run_options`).
- [ ] `subagent=None` + `system_prompt_override="..."` produces
  `agents=None`, `system_prompt="..."` (verified by
  `test_dispatch_profile_generic_session_fallback`).
- [ ] Semaphore enforces cap (4th concurrent call blocks until a
  slot frees — `test_dispatcher_acquires_and_releases_semaphore`).
- [ ] Three `DispatchEvent`s published per single-message stream:
  `started` → `message` → `completed` (`test_dispatcher_publishes_dispatch_events`).
- [ ] Invalid JSON payload raises `DispatchOutputValidationError` and
  publishes `dispatch.output_invalid` event
  (`test_dispatcher_validates_output_model`).
- [ ] Mid-stream exception publishes `dispatch.failed` and re-raises
  `DispatchExecutionError` (`test_dispatcher_propagates_session_failure`).
- [ ] Dispatch with `cwd` outside `WORKTREE_BASE_PATH` raises
  `DispatchExecutionError` BEFORE any SDK call.
- [ ] All unit tests pass:
  `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -v`.

---

## Test Specification

See spec §4 for the canonical list. Key tests this task owns:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher, ClaudeCodeDispatchProfile,
    DispatchExecutionError, DispatchOutputValidationError,
    ResearchOutput,
)


@pytest.fixture
def dispatcher():
    return ClaudeCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )


class TestProfileResolution:
    def test_dispatch_profile_to_run_options(self, dispatcher, tmp_path):
        profile = ClaudeCodeDispatchProfile(
            subagent="sdd-worker",
            allowed_tools=["Read", "Edit", "Bash"],
            permission_mode="acceptEdits",
        )
        # cwd must be under WORKTREE_BASE_PATH for the safety check;
        # tests configure that via env or monkeypatch.
        opts = dispatcher._resolve_run_options(profile, str(tmp_path))
        assert opts.cwd == str(tmp_path)
        assert opts.permission_mode == "acceptEdits"
        assert opts.agents is not None
        assert "sdd-worker" in opts.agents
        assert opts.setting_sources == ["project"]

    def test_generic_session_fallback(self, dispatcher, tmp_path):
        profile = ClaudeCodeDispatchProfile(
            subagent=None, system_prompt_override="be terse",
        )
        opts = dispatcher._resolve_run_options(profile, str(tmp_path))
        assert opts.agents is None
        assert opts.system_prompt == "be terse"


class TestSemaphore:
    async def test_acquires_and_releases(self, dispatcher):
        # see spec §4 test_dispatcher_acquires_and_releases_semaphore
        ...


class TestEvents:
    async def test_publishes_three_events_on_happy_path(self, dispatcher):
        ...


class TestValidation:
    async def test_output_model_validation_failure(self, dispatcher):
        ...


class TestSessionFailure:
    async def test_propagates_failure(self, dispatcher):
        ...


class TestCwdSafetyCheck:
    async def test_cwd_outside_worktree_base_rejected(self, dispatcher):
        with pytest.raises(DispatchExecutionError):
            await dispatcher.dispatch(
                brief=...,
                profile=ClaudeCodeDispatchProfile(),
                output_model=ResearchOutput,
                run_id="r", node_id="n",
                cwd="/etc",
            )
```

---

## Agent Instructions

1. Confirm TASK-874, TASK-875, TASK-876, TASK-877 are in
   `sdd/tasks/completed/`.
2. Read FEAT-124 implementation in `parrot/clients/claude_agent.py` end
   to end. Confirm the new fields from TASK-875 are merged.
3. Update index → `"in-progress"`.
4. Implement; mock all SDK and Redis access in tests.
5. Run lint and tests:
   `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py`
   `pytest packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py -v`.
6. Move to completed; update index; fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-27
**Notes**: Implemented `ClaudeCodeDispatcher` with `_resolve_run_options`,
`_enforce_cwd_under_worktree_base`, `_materialize_json_schema`,
`_validate_output` (best-effort JSON via balanced-brace scanner that
respects strings + escapes), and Redis publication helpers. Re-exported
the dispatcher and exception classes from `parrot.flows.dev_loop`. The
SDK (`claude_agent_sdk.types.AgentDefinition`) is lazy-imported inside
`_resolve_run_options` with a dict-shape fallback when the [claude-agent]
extra is missing. JSON-schema is materialized to a tempfile and unlinked
in the dispatch's `finally:` block. 9 unit tests cover profile resolution,
generic-session fallback, cwd safety, JSON extraction with embedded
braces, happy-path event sequence, validation failure, session failure
propagation, and semaphore concurrency cap.
**Deviations from spec**: None functional. The brief is JSON-encoded into
the prompt by `_build_prompt`; the spec's pseudocode left the prompt
construction implicit, so this is an inferred but consistent decision.
