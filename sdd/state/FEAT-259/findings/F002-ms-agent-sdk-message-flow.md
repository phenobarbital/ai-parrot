---
id: F002
query: "Microsoft Agent SDK message flow and HTTP setup"
type: web_research
---

## Message Flow

```
Channel (Teams/Webchat/Copilot Studio)
  → POST /api/messages (Activity JSON + Bearer JWT)
  → jwt_authorization_middleware (validates JWT, sets ClaimsIdentity)
  → CloudAdapter.process(request, agent)
    → HttpAdapterBase.process_request()
      → Parses JSON → Activity.model_validate(body)
      → ChannelServiceAdapter.process_activity(claims, activity, agent.on_turn)
        → Creates ConnectorClient (outbound)
        → Creates TurnContext(adapter, activity, identity)
        → run_pipeline(context, agent.on_turn) ← middleware chain
          → agent.on_turn(context) ← USER CODE
            → context.send_activity("response")
              → ConnectorClient.reply_to_activity()
                → POST to service_url (channel callback)
```

## HTTP Server Setup (aiohttp)

```python
from aiohttp.web import Application, run_app
from microsoft_agents.hosting.aiohttp import jwt_authorization_middleware, CloudAdapter

APP = Application(middlewares=[jwt_authorization_middleware])
APP.router.add_post("/api/messages", entry_point)
APP["agent_configuration"] = auth_configuration
APP["agent_app"] = agent_application
APP["adapter"] = agent_application.adapter
run_app(APP, host="localhost", port=3978)
```

## Authentication

- **Anonymous**: `None` config for local dev
- **Azure AD**: CLIENT_ID + TENANT_ID + CLIENT_SECRET from Azure AD App Registration
- **JWT validation**: Bearer token → verify signature, audience, issuer, expiry
- **Production requires**: Azure AD App Registration + Azure Bot Service resource

## Copilot Studio Connection

1. Deploy agent with public HTTPS endpoint (`/api/messages`)
2. In Copilot Studio → Add agent → Connect to external agent → M365 Agents SDK
3. Enter endpoint URL + auth config
4. Agent becomes a callable sub-agent within Copilot Studio orchestrator
