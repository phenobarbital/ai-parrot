---
type: Wiki Entity
title: AgentTalk
id: class:parrot.handlers.agent.AgentTalk
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: AgentTalk Handler - Universal agent conversation interface.
---

# AgentTalk

Defined in [`parrot.handlers.agent`](../summaries/mod:parrot.handlers.agent.md).

```python
class AgentTalk(BaseView)
```

AgentTalk Handler - Universal agent conversation interface.

Endpoints:
    PATCH /api/v1/agents/chat/{agent_id} - Configure tools/MCP servers (session-scoped)
    POST /api/v1/agents/chat/{agent_id} - Main chat endpoint with format negotiation

Features:
- POST to /api/v1/agents/chat/{agent_id} to interact with agents
- PATCH to /api/v1/agents/chat/{agent_id} to configure tools/MCP servers
- Uses BotManager to retrieve the agent
- Supports multiple output formats (JSON, HTML, Markdown, Terminal)
- Session-scoped ToolManager: PATCH persists tools under '{agent_id}_tool_manager'
- POST temporarily swaps user's ToolManager onto the agent and restores it after
- Leverages OutputMode for consistent formatting
- Session-based conversation management

## Methods

- `def user_objects_handler(self) -> UserObjectsHandler` — Lazy-initialized UserObjectsHandler for session-scoped managers.
- `def post_init(self, *args, **kwargs)`
- `async def post(self)` — POST handler for agent interaction. PBAC-guarded via requires_permission.
- `async def patch(self)` — PATCH /api/v1/agents/chat/{agent_id} — PBAC-guarded via agent:configure.
- `async def put(self)` — PUT /api/v1/agents/chat/{agent_id}
- `async def get(self)` — GET /api/v1/agents/chat/
- `async def debug_agent(self, agent)`
