---
type: Wiki Overview
title: 'TASK-1389: SpawnSubAgentTool implementation'
id: doc:sdd-tasks-completed-task-1389-spawn-subagent-tool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This is the core deliverable: a tool that an agent can invoke to spawn an'
relates_to:
- concept: mod:parrot.bots.base
  rel: mentions
- concept: mod:parrot.handlers.models.users_bots
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.agent
  rel: mentions
- concept: mod:parrot.tools.spawn
  rel: mentions
---

# TASK-1389: SpawnSubAgentTool implementation

**Feature**: FEAT-208 — Spawn Ephemeral Sub-Agent Tool
**Spec**: `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1388
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 of FEAT-208 (§3).

This is the core deliverable: a tool that an agent can invoke to spawn an
ephemeral sub-agent, execute a single task with a restricted tool subset
and timeout, then tear down the sub-agent — all in one tool call.

The tool orchestrates the existing `BotManager` methods (generalized in
TASK-1387/TASK-1388) in the pattern: create → poll-ready → invoke(timeout) → discard.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/spawn.py` with:
  - `SpawnSubAgentInput(BaseModel)` — args schema (task, tools, model, system_prompt, timeout, ttl_seconds).
  - `SpawnSubAgentTool(AbstractTool)` — the tool implementation.
- Implement `_execute()`:
  1. Build a `config` dict compatible with `BotManager.create_ephemeral_user_bot()`,
     injecting the tool subset via `tools_config`.
  2. `await bot_manager.create_ephemeral_user_bot(owner_id=..., owner_kind="agent", ...)`.
  3. Poll `get_ephemeral_status()` until `phase == "ready"` (with `asyncio.sleep` loop).
  4. Resolve the sub-agent from `bot_manager.get_bots()[chatbot_id]`.
  5. `await asyncio.wait_for(sub.invoke(question=task), timeout=timeout)`.
  6. `finally`: `await bot_manager.discard_ephemeral_user_bot(chatbot_id, owner_id=...)`.
  7. Return the result text (serialized `AIMessage.content` or string).
- Tool subset enforcement: intersect requested `tools[]` names with
  `allowed_tools` (constructor param from the parent agent). Resolve tool names
  to `tools_config` dicts.
- Set `routing_meta` prepared for future `requires_grant` (without enforcement).
- **Never** call `promote_user_bot`.
- Write comprehensive tests (happy path, timeout, teardown, subset enforcement).

**NOT in scope**: export/registration in `__init__.py` (TASK-1390), HTTP handler
changes, grants enforcement.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/spawn.py` | CREATE | `SpawnSubAgentTool` + `SpawnSubAgentInput` |
| `packages/ai-parrot/tests/tools/test_spawn_subagent.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Tool base class
from parrot.tools.abstract import AbstractTool          # verified: tools/abstract.py:81

# Reference pattern (wraps an agent as a tool)
from parrot.tools.agent import AgentTool                # verified: tools/agent.py:52

# Bot invoke method
from parrot.bots.base import BaseBot                    # verified: bots/base.py:38
# BaseBot.invoke(question: str, ...) -> AIMessage      # verified: bots/base.py:492

# BotManager (from ai-parrot-server — runtime dependency)
# Imported conditionally or via constructor injection:
# from parrot.manager.manager import BotManager         # verified: manager.py:95
# BotManager.create_ephemeral_user_bot(...)             # line 888
# BotManager.get_ephemeral_status(...)                  # line 1147 (SYNC)
# BotManager.discard_ephemeral_user_bot(...)            # line 1163
# BotManager.get_bots() -> Dict[str, AbstractBot]       # line 857

# UserBotModel (for config construction)
# from parrot.handlers.models.users_bots import UserBotModel  # verified: users_bots.py:26
# UserBotModel.set_tools_config(value)                  # line 152
# UserBotModel.get_tools_config() -> List[dict]         # line 142
# UserBotModel.to_bot_kwargs() -> dict                  # line 165
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):              # line 81
    args_schema: Type[BaseModel] = AbstractToolArgsSchema  # line 98
    routing_meta: Dict = None                            # line 100
    async def _execute(self, **kwargs) -> Any: ...       # line 239 (implement this)
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # line 473 (public wrapper — DO NOT override)

# packages/ai-parrot/src/parrot/tools/agent.py
class AgentTool(AbstractTool):                           # line 52
    # Reference pattern: wraps a bot, implements _execute, has args_schema

# packages/ai-parrot/src/parrot/bots/base.py
class BaseBot:                                           # line 38
    async def invoke(self, question: str, session_id=None, user_id=None,
                     use_conversation_history=True, memory=None, ctx=None,
                     response_model=None, **kwargs) -> AIMessage:  # line 492
    async def ask(self, ...) -> ...                      # line 718

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                        # line 95
    def get_bots(self) -> Dict[str, AbstractBot]         # line 857
    # After TASK-1388, create/get_status/discard accept owner_id/owner_kind
```

### Does NOT Exist
- ~~`parrot.tools.spawn`~~ — module does not exist yet; this task creates it.
- ~~`BotManager.spawn_sub_agent()`~~ — does not exist; the tool orchestrates the lifecycle.
- ~~`BasicBot.run()` / `BasicBot.execute_task()`~~ — not real methods. Use `invoke(question=...)` or `ask(...)`.
- ~~`tools_config` as a list of tool names~~ — it's `List[dict]` of tool config dicts (with `seal`/`unseal`). Map names → dicts.

---

## Implementation Notes

### Pattern to Follow
Follow `AgentTool` (tools/agent.py:52) for the class structure:

```python
class SpawnSubAgentTool(AbstractTool):
    name: str = "spawn_sub_agent"
    description: str = "Spawn an ephemeral sub-agent to execute a single task."
    args_schema = SpawnSubAgentInput

    def __init__(self, bot_manager, owner_id: str, *,
                 allowed_tools: Optional[list[str]] = None,
                 name: str = "spawn_sub_agent",
                 description: Optional[str] = None,
                 routing_meta: Optional[dict] = None):
        super().__init__(name=name, description=description or self.description,
                         routing_meta=routing_meta or {})
        self._bot_manager = bot_manager
        self._owner_id = owner_id
        self._allowed_tools = allowed_tools or []

    async def _execute(self, **kwargs) -> Any:
        # 1. Build config
        # 2. Create ephemeral bot
        # 3. Poll ready
        # 4. Invoke with timeout
        # 5. Finally: discard
        ...
```

### Key Constraints
- `BotManager` is injected via constructor (not from `app`) — testable without aiohttp.
- `get_ephemeral_status` is **synchronous** — the poll loop is `while True: status = ...; if ready: break; await asyncio.sleep(0.5)`.
- Tool subset: intersect `kwargs["tools"]` with `self._allowed_tools`. If a
  requested tool is not in the allowlist, exclude it (log a warning, don't error).
- Mapping tool names → `tools_config` dicts is an open question (spec §8). Options:
  (a) resolve from a tool registry/manager on the parent, or (b) accept `tools_config`
  dicts directly. Choose the simplest path that works for tests.
- `asyncio.wait_for` wraps the `invoke()` call. On `asyncio.TimeoutError`, log
  and re-raise as a descriptive error (don't swallow).
- **`finally` block**: always discard, even on timeout/error. Assert in tests.
- Never import `promote_user_bot` or call it.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/agent.py` — `AgentTool` class structure
- `packages/ai-parrot/src/parrot/tools/abstract.py` — `AbstractTool` base class

---

## Acceptance Criteria

- [ ] `SpawnSubAgentTool._execute` completes the full lifecycle: create → poll → invoke → discard
- [ ] Sub-agent receives only the tools in the requested subset (intersected with allowlist)
- [ ] `asyncio.wait_for` enforces the `timeout` — test with a slow mock
- [ ] Teardown guaranteed: after success/error/timeout, `bot_manager.get_bots()` and
      `_ephemeral_registry` do NOT contain the `chatbot_id`
- [ ] The tool **never** calls `promote_user_bot`
- [ ] `routing_meta` is set (prepared for `requires_grant`, no enforcement)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/test_spawn_subagent.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/spawn.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_spawn_subagent.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from parrot.tools.spawn import SpawnSubAgentTool, SpawnSubAgentInput


@pytest.fixture
def mock_bot_manager():
    """BotManager mock with app=None behavior (phase='ready' immediate)."""
    bm = MagicMock()
    bm.get_bots.return_value = {}
    return bm


@pytest.fixture
def tool(mock_bot_manager):
    return SpawnSubAgentTool(
        bot_manager=mock_bot_manager,
        owner_id="agent:test-parent",
        allowed_tools=["get_weather", "search_docs"],
    )


class TestSpawnSubAgentTool:
    @pytest.mark.asyncio
    async def test_happy_path(self, tool, mock_bot_manager):
        """Sub-agent is created, invoked, result returned, then discarded."""
        # Setup mocks for create → get_status → invoke → discard
        ...

    @pytest.mark.asyncio
    async def test_timeout_discards(self, tool, mock_bot_manager):
        """When invoke exceeds timeout, sub-agent is still discarded."""
        ...

    @pytest.mark.asyncio
    async def test_teardown_on_error(self, tool, mock_bot_manager):
        """When invoke raises, sub-agent is still discarded."""
        ...

    def test_tool_subset_enforcement(self, tool):
        """Requested tools outside allowlist are excluded."""
        ...

    def test_never_calls_promote(self, tool, mock_bot_manager):
        """promote_user_bot is never called during the lifecycle."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-208-spawn-ephemeral-subagent-tool.spec.md` §2-§3 (M3), §7
2. **Check dependencies** — TASK-1388 must be in `sdd/tasks/completed/`
3. **Read** `packages/ai-parrot/src/parrot/tools/agent.py` as the reference pattern
4. **Verify the Codebase Contract** — confirm all signatures
5. **Update status** in `sdd/tasks/index/spawn-ephemeral-subagent-tool.json` → `"in-progress"`
6. **Implement** `spawn.py` following the scope
7. **Run**: `pytest packages/ai-parrot/tests/tools/test_spawn_subagent.py -v`
8. **Verify** all acceptance criteria
9. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-06-01
**Notes**: Created `SpawnSubAgentInput(BaseModel)` with all spec fields. Created
`SpawnSubAgentTool(AbstractTool)` with constructor injecting `bot_manager` and
`owner_id`. `_execute` implements the full create→poll-ready→invoke(timeout)→discard
lifecycle. Tool subset enforcement via `_compute_effective_tools` (intersection with
allowlist). Tools mapped to `tools_config_plain` dicts. `routing_meta.requires_grant=False`
prepared for future HITL grant enforcement. `finally` block guarantees discard on
success/error/timeout. 21 tests, all passing.

**Deviations from spec**: For §8 open question on tools_config mapping, chose option
(b): pass `[{"name": tool_name}]` minimal dicts as tools_config_plain. This is
sufficient for the test suite and avoids requiring a full ToolManager reference.
