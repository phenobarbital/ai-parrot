---
id: F004
query: "ai-parrot existing MS Teams integration"
type: codebase_research
---

## Existing MS Teams Integration

Location: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/`

### Architecture

- `MSTeamsAgentWrapper(ActivityHandler, MessageHandler)` — subclasses BotBuilder's ActivityHandler
- Uses the **old** `botbuilder-*` packages (Bot Framework SDK v4)
- The Microsoft Agent SDK (v0.9.0) is the **successor** to botbuilder

### Key Files

| File | Purpose |
|------|---------|
| `wrapper.py` (57KB) | Main integration, message routing, forms |
| `adapter.py` | BotBuilder adapter + Teams API |
| `handler.py` | Base message handler |
| `models.py` | MSTeamsAgentConfig |
| `hitl_adapter.py` | Human-in-the-Loop |
| `proactive.py` | Proactive notifications |
| `dialogs/` | Multi-step form orchestration |
| `commands/` | Slash command routing |

### Config

```yaml
agents:
  TeamsSales:
    kind: msteams
    chatbot_id: sales_agent
    client_id: "${MICROSOFT_APP_ID}"
    client_secret: "${MICROSOFT_APP_PASSWORD}"
```

### Relationship to Microsoft Agent SDK

The existing integration uses `botbuilder-core` / `botbuilder-integration-aiohttp`.
The new Microsoft Agent SDK (`microsoft-agents-*`) is the official successor with:
- Same Activity model (but now Pydantic v2 instead of custom serialization)
- Same ActivityHandler pattern (but modernized)
- New AgentApplication decorator approach
- New auth system (same Azure AD, but cleaner API)
- Copilot Studio integration built-in

**Migration path**: Eventually replace botbuilder-based integration with microsoft-agents-based one.
**Coexistence**: Both can run simultaneously on different routes.
