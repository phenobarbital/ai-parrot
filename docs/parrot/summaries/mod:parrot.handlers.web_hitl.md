---
type: Wiki Summary
title: parrot.handlers.web_hitl
id: mod:parrot.handlers.web_hitl
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Web HITL (Human-in-the-Loop) support for AI-Parrot.
relates_to:
- concept: class:parrot.handlers.web_hitl.HITLResponseBody
  rel: defines
- concept: class:parrot.handlers.web_hitl.HITLResponseHandler
  rel: defines
- concept: class:parrot.handlers.web_hitl.SuspendingWebHumanTool
  rel: defines
- concept: class:parrot.handlers.web_hitl.WebHumanTool
  rel: defines
- concept: func:parrot.handlers.web_hitl.get_current_web_session
  rel: defines
- concept: func:parrot.handlers.web_hitl.reset_current_web_session
  rel: defines
- concept: func:parrot.handlers.web_hitl.set_current_web_session
  rel: defines
- concept: func:parrot.handlers.web_hitl.setup_web_hitl
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.human
  rel: references
- concept: mod:parrot.human.channels.base
  rel: references
- concept: mod:parrot.human.channels.web
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.handlers.web_hitl`

Web HITL (Human-in-the-Loop) support for AI-Parrot.

This module provides:

1. **ContextVar helpers** — ``current_web_session`` stores the active WebSocket
   channel ID (typically the user's ``session_id``) so that tools invoked by an
   agent during a web request can resolve the correct recipient without being
   explicitly passed the value.

2. **WebHumanTool** — a :class:`~parrot.human.tool.HumanTool` subclass that
   lazily resolves the ``HumanInteractionManager`` and the target web session at
   invocation time, mirroring ``TelegramHumanTool``.

3. **HITLResponseBody / HITLResponseHandler** — a Pydantic model and an
   aiohttp :class:`~navigator.views.BaseView` that expose the
   ``POST /api/v1/agents/hitl/respond`` endpoint through which the frontend
   submits human answers back to the waiting agent.

4. **setup_web_hitl** — idempotent bootstrap function called from
   :class:`~parrot.manager.manager.BotManager` that ensures a process-wide
   :class:`~parrot.human.manager.HumanInteractionManager` and
   :class:`~parrot.human.channels.web.WebHumanChannel` are initialised at
   application startup.

## Classes

- **`WebHumanTool(HumanTool)`** — A :class:`~parrot.human.tool.HumanTool` that auto-resolves manager
- **`SuspendingWebHumanTool(WebHumanTool)`** — WebHumanTool variant wired for stateless REST suspend/resume (FEAT-204).
- **`HITLResponseBody(BaseModel)`** — Request body for ``POST /api/v1/agents/hitl/respond``.
- **`HITLResponseHandler(BaseView)`** — HTTP handler for ``POST /api/v1/agents/hitl/respond``.

## Functions

- `def get_current_web_session() -> Optional[str]` — Return the active web session ID for the current request context.
- `def set_current_web_session(session: Optional[str]) -> Token` — Set the active web session ID for the current request context.
- `def reset_current_web_session(token: Token) -> None` — Reset the web session ContextVar to its previous value.
- `async def setup_web_hitl(app: web.Application) -> None` — Bootstrap a process-wide HumanInteractionManager with a WebHumanChannel.
