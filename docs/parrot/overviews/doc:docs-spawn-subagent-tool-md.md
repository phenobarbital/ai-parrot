---
type: Wiki Overview
title: SpawnSubAgentTool
id: doc:docs-spawn-subagent-tool-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: Spawn ephemeral sub-agents on-the-fly to delegate bounded work, then tear
  them
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.spawn
  rel: mentions
---

# SpawnSubAgentTool

Spawn ephemeral sub-agents on-the-fly to delegate bounded work, then tear them
down automatically. The parent agent retains full control over which tools the
sub-agent may use, how long it may run, and what system prompt it operates under.

---

## Overview

`SpawnSubAgentTool` is an `AbstractTool` that lets an always-on orchestrator
agent create short-lived sub-agents **in process**, execute a single task, and
discard them — all within one tool call. No state is left behind: after the
call completes (success, error, or timeout), the sub-agent is removed from
both `BotManager._bots` and the `EphemeralRegistry`.

**Lifecycle in one diagram:**

```
ParentAgent
   |  (LLM tool call: spawn_sub_agent)
   v
SpawnSubAgentTool._execute()
   |
   |-- 1. Enforce tool subset (intersect with parent allowlist)
   |-- 2. create_ephemeral_user_bot(owner_id, owner_kind="agent", ...)
   |-- 3. Poll get_ephemeral_status() until phase == "ready"
   |-- 4. sub = get_bots()[chatbot_id]
   |-- 5. asyncio.wait_for(sub.invoke(question=task), timeout)
   |-- 6. finally: discard_ephemeral_user_bot(chatbot_id, owner_id)
   |
   v
Result string returned to the parent agent
```

---

## Installation

`SpawnSubAgentTool` ships with the core `ai-parrot` package. No extra
dependencies are needed.

```python
from parrot.tools.spawn import SpawnSubAgentTool, SpawnSubAgentInput

# or from the top-level namespace:
from parrot.tools import SpawnSubAgentTool
```

---

## Quick Start

### Minimal example

```python
from parrot.tools.spawn import SpawnSubAgentTool

# bot_manager is typically app["bot_manager"] in an aiohttp context.
tool = SpawnSubAgentTool(
    bot_manager=bot_manager,
    owner_id="agent:my-orchestrator",
)

# The LLM calls this tool with a task description.
result = await tool.execute(
    task="What is the weather in Madrid?",
    timeout=30,
)
print(result)
```

### With a restricted tool subset

```python
tool = SpawnSubAgentTool(
    bot_manager=bot_manager,
    owner_id="agent:my-orchestrator",
    allowed_tools=["get_weather", "search_docs", "calculator"],
)

# The sub-agent will only receive "search_docs" (intersection with allowlist).
result = await tool.execute(
    task="Find the latest quarterly report for ACME Corp.",
    tools=["search_docs", "send_email"],  # send_email is excluded
    timeout=60,
)
```

### With a custom system prompt and model

```python
result = await tool.execute(
    task="Summarize this contract in 3 bullet points.",
    tools=["search_docs"],
    system_prompt="You are a concise legal analyst. Answer in bullet points only.",
    model="anthropic",
    timeout=90,
    ttl_seconds=120,
)
```

---

## Configuration Reference

### Constructor Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `bot_manager` | `BotManager` | **required** | The `BotManager` instance. Injected via constructor (not from `app`) so the tool is testable without an aiohttp application. |
| `owner_id` | `str` | **required** | Canonical string ID of the parent agent (e.g. `"agent:orchestrator-001"`). Used for ownership checks on the ephemeral registry. |
| `allowed_tools` | `list[str]` | `[]` | Allowlist of tool names the parent authorises for sub-agents. The sub-agent receives only the **intersection** of this list and the `tools` requested per-call. Empty list = no tools. |
| `name` | `str` | `"spawn_sub_agent"` | Tool name visible to the LLM. |
| `description` | `str` | *(auto)* | Tool description visible to the LLM. Override for domain-specific wording. |
| `routing_meta` | `dict` | `{}` | Routing hints for the `CapabilityRegistry`. The key `"requires_grant"` is set to `False` by default (reserved for future HITL grant enforcement). |

### Per-Call Parameters (SpawnSubAgentInput)

These are the arguments the LLM passes when it invokes the tool:

| Parameter | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `task` | `str` | **required** | — | The question or task for the sub-agent. |
| `tools` | `list[str]` | `[]` | — | Tool names requested for the sub-agent. Intersected with the parent's `allowed_tools`. |
| `model` | `str` | `None` | — | LLM model override (e.g. `"openai"`, `"anthropic"`, `"google"`). Inherits the parent's default when not set. |
| `system_prompt` | `str` | `None` | — | System prompt injected into the sub-agent's configuration. |
| `timeout` | `int` | `120` | 1 - 900 | Maximum seconds the sub-agent may run before the call is cancelled. |
| `ttl_seconds` | `int` | `300` | >= 10 | Ephemeral registry TTL. Acts as a safety net — the sub-agent is discarded in the `finally` block well before this expires. |

---

## Integrating with an Agent

### Attach to an agent manually

```python
from parrot.bots.agent import BasicAgent
from parrot.tools.spawn import SpawnSubAgentTool

agent = BasicAgent(
    name="Orchestrator",
    use_llm="anthropic",
    system_prompt="You are an orchestrator. Delegate work to sub-agents.",
)

spawn_tool = SpawnSubAgentTool(
    bot_manager=app["bot_manager"],
    owner_id=f"agent:{agent.name}",
    allowed_tools=["search_docs", "get_weather", "calculator"],
)

# Add the tool to the agent's tool manager.
agent.tool_manager.add_tool(spawn_tool)
```

### Use inside an aiohttp application

```python
async def on_startup(app):
    bot_manager = app["bot_manager"]

    orchestrator = bot_manager.get_bots()["orchestrator"]

    spawn_tool = SpawnSubAgentTool(
        bot_manager=bot_manager,
        owner_id="agent:orchestrator",
        allowed_tools=["search_docs", "summarize", "translate"],
    )

    orchestrator.tool_manager.add_tool(spawn_tool)
```

---

## Tool Subset Enforcement (Defense in Depth)

The tool uses a two-layer authorization model to prevent privilege
escalation:

1. **Parent allowlist** (`allowed_tools` on the constructor) — the
   maximum set of tools any sub-agent spawned by this parent may use.
2. **Per-call request** (`tools` in `SpawnSubAgentInput`) — the LLM
   requests a subset for this specific call.

The sub-agent receives only the **intersection** of these two lists.
Tools requested by the LLM that are not in the parent's allowlist are
silently excluded (with a warning log).

```
allowed_tools = ["search_docs", "get_weather", "calculator"]
requested     = ["search_docs", "send_email"]
                  ↓
effective     = ["search_docs"]          # send_email excluded
```

If `allowed_tools` is empty (or not set), the sub-agent receives **no tools**
regardless of what the LLM requests.

---

## Timeout and Teardown Guarantees

### Timeout

The sub-agent's `invoke()` call is wrapped in `asyncio.wait_for(timeout)`.
If the sub-agent exceeds the timeout, the call is cancelled and a
`TimeoutError` is raised with a descriptive message.

### Guaranteed teardown

The `discard_ephemeral_user_bot()` call lives in a `finally` block. This
means the sub-agent is **always** cleaned up, regardless of the outcome:

| Outcome | Teardown? | Exception propagated? |
|---|---|---|
| Success | Yes | No (result returned) |
| `invoke()` raises | Yes | Yes (original exception) |
| Timeout exceeded | Yes | Yes (`TimeoutError`) |
| Warm-up fails | Yes | Yes (`RuntimeError`) |
| Discard itself fails | Logged as warning | No (original exception preserved) |

After teardown, neither `BotManager._bots` nor `EphemeralRegistry` contain
a reference to the sub-agent's `chatbot_id`.

---

## Ownership Model

The ephemeral subsystem uses typed ownership to track who created each
sub-agent:

| Field | Type | Example | Description |
|---|---|---|---|
| `owner_id` | `str` | `"agent:orchestrator-001"` | Canonical owner identifier |
| `owner_kind` | `Literal["user","agent"]` | `"agent"` | Distinguishes human-owned bots from agent-owned sub-agents |

When `SpawnSubAgentTool` creates a sub-agent, it passes
`owner_kind="agent"` so the ephemeral registry knows this is an
agent-owned bot. This is fully backward-compatible with the existing
HTTP handler (`EphemeralUserAgentHandler`), which continues to pass
`user_id: int` for human-owned bots.

---

## Error Handling

| Error | When | What to do |
|---|---|---|
| `ValueError("either user_id or owner_id is required")` | `owner_id` not provided at construction | Pass `owner_id` to the constructor. |
| `TimeoutError("Sub-agent task timed out after N seconds")` | `invoke()` exceeds `timeout` | Increase `timeout` or simplify the task. |
| `RuntimeError("warm-up failed: ...")` | Sub-agent's `configure()` or MCP validation fails | Check the sub-agent's tools/MCP configuration. |
| `RuntimeError("did not reach phase='ready' within 30s")` | Warm-up takes too long (only with `app != None`) | Check slow MCP servers or RAG builds. |
| `RuntimeError("not found in BotManager._bots")` | Internal inconsistency | Report as a bug. |

All errors are raised to the parent agent's LLM, which can decide how to
handle them (retry, fall back, report to the user).

---

## Testing

### Unit tests without an aiohttp app

When `BotManager.app` is `None`, the warm-up step is skipped and the
sub-agent's phase goes directly to `"ready"`. This makes it easy to test
the tool in isolation:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.tools.spawn import SpawnSubAgentTool


@pytest.fixture
def mock_bot_manager():
    bm = MagicMock()

    # Simulate phase='ready' immediately
    status = MagicMock()
    status.chatbot_id = "test-bot-001"
    status.phase = "ready"

    bm.create_ephemeral_user_bot = AsyncMock(return_value=status)
    bm.get_ephemeral_status = MagicMock(return_value=status)
    bm.discard_ephemeral_user_bot = AsyncMock(return_value=True)

    # Mock sub-agent
    sub_bot = MagicMock()
    response = MagicMock()
    response.content = "Task completed successfully."
    sub_bot.invoke = AsyncMock(return_value=response)
    bm.get_bots.return_value = {"test-bot-001": sub_bot}

    return bm


@pytest.mark.asyncio
async def test_spawn_and_discard(mock_bot_manager):
    tool = SpawnSubAgentTool(
        bot_manager=mock_bot_manager,
        owner_id="agent:test",
        allowed_tools=["search"],
    )

    result = await tool._execute(
        task="Find the answer.",
        tools=["search"],
        timeout=10,
    )

    assert result == "Task completed successfully."
    mock_bot_manager.discard_ephemeral_user_bot.assert_awaited_once()
```

### Running the test suite

```bash
# SpawnSubAgentTool tests (21 tests)
pytest packages/ai-parrot/tests/tools/test_spawn_subagent.py -v

# Import smoke tests (7 tests)
pytest packages/ai-parrot/tests/tools/test_spawn_import.py -v

# Ephemeral ownership tests (14 tests)
pytest packages/ai-parrot-server/tests/test_ephemeral_ownership.py -v

# BotManager ownership tests (9 tests)
pytest packages/ai-parrot-server/tests/test_botmanager_ephemeral_owner.py -v
```

---

## Design Decisions

| Decision | Rationale |
|---|---|
| `BotManager` injected via constructor, not `app["bot_manager"]` | Keeps the tool testable without an aiohttp application. |
| `tools_config_plain` uses minimal `[{"name": name}]` dicts | Sufficient for basic tool registration. Full ToolManager-based resolution deferred to a follow-up. |
| `promote_user_bot` is never called | Sub-agents are ephemeral by design. Persisting them would leak state. |
| `routing_meta["requires_grant"] = False` | Placeholder for future HITL grant enforcement. Set but not enforced in this release. |
| TTL defaults to 300s (5 min), not 86400s (24h) | Sub-agents should be short-lived. The `finally` teardown fires well before TTL expiry. |

---

## Limitations and Future Work

- **Tool config resolution**: Currently maps tool names to minimal
  `{"name": name}` config dicts. A future enhancement could resolve
  full tool configurations from the parent's `ToolManager`.

- **HITL grant enforcement**: The `routing_meta["requires_grant"]` field
  is prepared but not enforced. A future feature will add approval gates
  for tools that perform mutations.

- **AgentFactoryOrchestrator mode**: This release only supports explicit
  configuration (task, tools, model, system_prompt). A future "describe
  and create" mode using an LLM router to design the sub-agent is planned.

- **Durable sub-agents**: Out of scope. This tool always discards the
  sub-agent. If you need persistent agents, use `create_ephemeral_user_bot`
  + `promote_user_bot` directly through the HTTP handler.

---

## API Reference

### `SpawnSubAgentTool`

```python
class SpawnSubAgentTool(AbstractTool):
    def __init__(
        self,
        bot_manager: Any,
        owner_id: str,
        *,
        allowed_tools: Optional[list[str]] = None,
        name: str = "spawn_sub_agent",
        description: Optional[str] = None,
        routing_meta: Optional[dict[str, Any]] = None,
    ) -> None: ...

    async def _execute(self, **kwargs) -> Any: ...
```

### `SpawnSubAgentInput`

```python
class SpawnSubAgentInput(BaseModel):
    task: str
    tools: list[str] = []
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    timeout: int = 120       # 1-900
    ttl_seconds: int = 300   # >= 10
```
