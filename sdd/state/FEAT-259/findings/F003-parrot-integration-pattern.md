---
id: F003
query: "ai-parrot existing integration patterns"
type: codebase_research
---

## Integration Architecture

Location: `packages/ai-parrot-integrations/src/parrot/integrations/`

### Existing Platforms

| Platform | Wrapper Class | Pattern |
|----------|--------------|---------|
| Telegram | `TelegramAgentWrapper` | Aiogram + polling |
| MS Teams | `MSTeamsAgentWrapper(ActivityHandler)` | BotBuilder SDK + ActivityHandler |
| WhatsApp | `WhatsAppAgentWrapper` | Webhook REST |
| Slack    | `SlackAgentWrapper` | Bolt SDK + Socket/Webhook |
| Matrix   | Custom | A2A events |

### Wrapper Contract (Implicit)

```python
class {Platform}AgentWrapper:
    def __init__(self, agent: AbstractBot, config: {Platform}Config, app: web.Application):
        self.agent = agent
        self.config = config
        self.route = f"/api/{platform}/{safe_id}/messages"
        self.app.router.add_post(self.route, self.handle_request)
    
    async def handle_request(self, request: web.Request) -> web.Response:
        # 1. Parse platform payload
        # 2. Extract message, user_id, session_id
        # 3. response = await self.agent.ask(text, session_id=..., user_id=...)
        # 4. Format response for platform
        # 5. Return web.json_response()
```

### Agent Interface

All integrations call:
```python
response = await agent.ask(
    question=text,
    session_id=conversation_id,
    user_id=user_id,
    **kwargs
) -> AIMessage  # .content, .metadata
```

### Registration

1. Config model in `models.py` (dispatched by `kind` field)
2. `_start_{platform}_bot()` in `IntegrationBotManager`
3. Manager `startup()` iterates config and instantiates wrappers
4. Config from `integrations_bots.yaml`

### Key Files

- Config parsing: `integrations/models.py`
- Manager: `integrations/manager.py`
- Bot interface: `parrot/bots/abstract.py` (ask() at ~line 3693)
- MS Teams reference: `integrations/msteams/wrapper.py`
