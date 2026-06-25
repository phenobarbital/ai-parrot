---
id: F001
query: "Microsoft 365 Agents SDK Python architecture"
type: web_research
---

## Microsoft 365 Agents SDK for Python

- **Repo**: github.com/microsoft/Agents-for-python (MIT, v0.9.0, Apr 2026)
- **Python**: >= 3.10, namespace `microsoft_agents`
- **Replaces**: legacy `botbuilder-*` packages (Bot Framework SDK v4)

### Core Protocol

```python
class Agent(Protocol):
    async def on_turn(self, context: TurnContext): ...
```

Single-method protocol. This is the only contract a third-party must satisfy.

### Key Classes

| Class | Role |
|-------|------|
| `Agent` (Protocol) | Root abstraction — single `on_turn` method |
| `Activity` (Pydantic v2) | Universal message envelope (~50 fields) |
| `TurnContext` | Per-turn context: activity, adapter, send_activity() |
| `ActivityHandler` | Inheritance-based dispatcher (on_message, on_event, etc.) |
| `AgentApplication[StateT]` | Decorator-based routing (modern approach) |
| `CloudAdapter` | aiohttp-specific adapter |
| `ChannelServiceAdapter` | Manages ConnectorClient, auth, process_activity() |

### Packages (modular PyPI)

- `microsoft-agents-activity` — Activity Pydantic model
- `microsoft-agents-hosting-core` — Agent protocol, TurnContext, adapters, auth
- `microsoft-agents-hosting-aiohttp` — aiohttp integration
- `microsoft-agents-hosting-teams` — Teams-specific handlers
- `microsoft-agents-hosting-dialogs` — multi-turn dialog system
