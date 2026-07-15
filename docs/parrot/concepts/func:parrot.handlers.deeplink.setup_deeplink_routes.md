---
type: Concept
title: setup_deeplink_routes()
id: func:parrot.handlers.deeplink.setup_deeplink_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register the web resume routes on ``app`` and return the handler.
---

# setup_deeplink_routes

```python
def setup_deeplink_routes(app: web.Application, service: DeepLinkService, invoker: ResumeInvoker, *, path: str='/api/v1/a2ui/resume/web') -> DeepLinkResumeHandler
```

Register the web resume routes on ``app`` and return the handler.

Registers ``GET`` (confirm landing, no consume) and ``POST`` (consume + inject) at the
same path. Call this alongside the ``AgentTalk`` registration; ``invoker`` should wrap
the AgentTalk POST flow (``agent_name``/``query``/``session_id``/``user_id``).
