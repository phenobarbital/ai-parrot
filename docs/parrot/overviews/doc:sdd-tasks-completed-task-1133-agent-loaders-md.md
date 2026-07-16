---
type: Wiki Overview
title: 'TASK-1133: Agent Loading — Standalone & Server'
id: doc:sdd-tasks-completed-task-1133-agent-loaders-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: call `configure()` if not already done
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.cli.loaders
  rel: mentions
- concept: mod:parrot.registry
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

# TASK-1133: Agent Loading — Standalone & Server

**Feature**: FEAT-168 — Console CLI Agents
**Spec**: `sdd/specs/console-cli-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1131
**Assigned-to**: unassigned

---

## Context

> Implements Module 2 from the spec: agent loading strategies.
> `StandaloneAgentLoader` wraps `AgentRegistry.get_instance()` with error
> handling, fuzzy name matching, and `questionary.select()` picker.
> `ServerAgentProxy` connects to a running server via HTTP to list and
> interact with agents.

---

## Scope

- Create `packages/ai-parrot/src/parrot/cli/loaders.py`
- Implement `StandaloneAgentLoader`:
  - `async load(name: str) -> AbstractBot` — lookup via `AgentRegistry.get_instance()`,
    call `configure()` if not already done
  - `async list_agents() -> List[BotMetadata]` — iterate `_registered_agents`
  - Fuzzy name matching when agent not found (suggest closest matches using
    `difflib.get_close_matches()`)
  - `async select_agent() -> str` — use `questionary.select()` to let user pick
    from registered agents when name is omitted
- Implement `ServerAgentProxy`:
  - `__init__(server_url: str)` — store URL, create `aiohttp.ClientSession`
  - `async load(name: str) -> AbstractBot` — NOT a real bot instance; create a
    thin proxy object that forwards `ask()` calls via HTTP POST
  - `async list_agents() -> List[dict]` — GET server agent listing endpoint
  - `async close()` — close the HTTP session
- Define `AgentLoadError` exception for loading failures

**NOT in scope**: REPL loop, slash commands, rendering

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/loaders.py` | CREATE | StandaloneAgentLoader + ServerAgentProxy |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import agent_registry         # parrot/registry/__init__.py:7
from parrot.registry.registry import AgentRegistry, BotMetadata  # registry.py:228,42
from parrot.bots.abstract import AbstractBot       # bots/abstract.py:146
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
class AgentRegistry:  # line 228
    _registered_agents: Dict[str, BotMetadata]  # line 275

    async def get_instance(
        self,
        name: str,
        request: Optional[web.Request] = None,
        **kwargs,
    ) -> Optional[AbstractBot]:  # line 600
        ...

@dataclass(slots=True)
class BotMetadata:  # line 42
    name: str
    factory: Union[Type[AbstractBot], AgentFactory]
    tags: Optional[Set[str]] = field(default_factory=set)
    async def get_instance(self, **kwargs) -> AbstractBot:  # line 78
        # calls await instance.configure() at line 182
        ...

# packages/ai-parrot/src/parrot/registry/__init__.py
agent_registry = AgentRegistry(...)  # line 7 — global singleton
```

### Does NOT Exist
- ~~`AgentRegistry.list_agents()`~~ — no such method; iterate `_registered_agents`
- ~~`AgentRegistry.search(name)`~~ — no fuzzy search method
- ~~`AbstractBot.history`~~ — no history attribute
- ~~`agent_registry.get_bot()`~~ — the method is `get_instance()`, not `get_bot()`

---

## Implementation Notes

### Pattern to Follow
```python
import difflib
import questionary
from parrot.registry import agent_registry

class StandaloneAgentLoader:
    async def load(self, name: str) -> AbstractBot:
        bot = await agent_registry.get_instance(name)
        if bot is None:
            available = list(agent_registry._registered_agents.keys())
            close = difflib.get_close_matches(name, available, n=3)
            raise AgentLoadError(name, suggestions=close)
        return bot

    async def select_agent(self) -> str:
        agents = list(agent_registry._registered_agents.keys())
        if not agents:
            raise AgentLoadError("No agents registered")
        return await questionary.select("Select agent:", choices=agents).ask_async()
```

### Key Constraints
- `AgentRegistry.get_instance()` returns `None` when not found — check the return
- `questionary.select()` must be called with `ask_async()` for async compat
- Server proxy must handle connection errors (timeout, refused) gracefully
- Server proxy uses `aiohttp.ClientSession` — must be closed on exit

---

## Acceptance Criteria

- [ ] `StandaloneAgentLoader.load(name)` returns a configured `AbstractBot`
- [ ] Unknown agent name raises `AgentLoadError` with fuzzy suggestions
- [ ] `select_agent()` presents `questionary.select()` picker
- [ ] `ServerAgentProxy` connects via HTTP and can list agents
- [ ] `ServerAgentProxy` proxies `ask()` calls to server
- [ ] Connection errors produce clear error messages
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/cli/loaders.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/test_loaders.py
import pytest
from unittest.mock import AsyncMock, patch
from parrot.cli.loaders import StandaloneAgentLoader, ServerAgentProxy, AgentLoadError


class TestStandaloneAgentLoader:
    async def test_load_existing_agent(self):
        loader = StandaloneAgentLoader()
        with patch("parrot.cli.loaders.agent_registry") as mock_reg:
            mock_reg.get_instance = AsyncMock(return_value=AsyncMock())
            bot = await loader.load("test_agent")
            assert bot is not None

    async def test_load_unknown_agent_raises(self):
        loader = StandaloneAgentLoader()
        with patch("parrot.cli.loaders.agent_registry") as mock_reg:
            mock_reg.get_instance = AsyncMock(return_value=None)
            mock_reg._registered_agents = {"security_agent": None}
            with pytest.raises(AgentLoadError):
                await loader.load("secrity_agent")

    async def test_fuzzy_match_suggestions(self):
        loader = StandaloneAgentLoader()
        with patch("parrot.cli.loaders.agent_registry") as mock_reg:
            mock_reg.get_instance = AsyncMock(return_value=None)
            mock_reg._registered_agents = {
                "security_agent": None, "hr_assistant": None
            }
            with pytest.raises(AgentLoadError) as exc_info:
                await loader.load("secrity_agent")
            assert "security_agent" in exc_info.value.suggestions
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/console-cli-agents.spec.md` §2 (New Public Interfaces)
2. **Read `packages/ai-parrot/src/parrot/registry/registry.py`** to understand `get_instance()`
3. **Read `packages/ai-parrot/src/parrot/registry/__init__.py`** to confirm `agent_registry` import
4. **Implement** both loaders
5. **Test** with mocked registry

---

## Completion Note

Completed 2026-05-13. Implemented `StandaloneAgentLoader` (uses `agent_registry.get_instance()`
with `difflib.get_close_matches` fuzzy suggestions and `questionary.select` picker),
`ServerAgentProxy` (HTTP proxy via `aiohttp`, includes `load()`, `list_agents()`,
`select_agent()`, `close()`), `AgentLoadError` exception with `suggestions` attribute,
and `_ServerBotProxy` thin proxy implementing the ask/stream interface. All linting passed.
