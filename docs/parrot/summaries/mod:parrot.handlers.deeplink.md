---
type: Wiki Summary
title: parrot.handlers.deeplink
id: mod:parrot.handlers.deeplink
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: A2UI deep-link web resume route (FEAT-273 Module 8, web channel).
relates_to:
- concept: class:parrot.handlers.deeplink.DeepLinkResumeHandler
  rel: defines
- concept: func:parrot.handlers.deeplink.build_structured_message
  rel: defines
- concept: func:parrot.handlers.deeplink.setup_deeplink_routes
  rel: defines
- concept: mod:parrot.outputs.a2ui.deeplink
  rel: references
---

# `parrot.handlers.deeplink`

A2UI deep-link web resume route (FEAT-273 Module 8, web channel).

Receives a deep-link click, consumes the single-use token via
:class:`~parrot.outputs.a2ui.deeplink.DeepLinkService`, and injects the action as a
**structured user message** into the original session through the AgentTalk POST flow.

The route is thin: token → ``consume()`` → structured message → resume invoker. Expired
or replayed tokens map to a friendly "session expired" response (no payload echo, no
stack trace). Registration is via :func:`setup_deeplink_routes` (call it wherever the
app registers ``AgentTalk``; the web resume path is ``/api/v1/a2ui/resume/web``).

## Classes

- **`DeepLinkResumeHandler`** — Web resume handler for A2UI deep links.

## Functions

- `def build_structured_message(payload: ResumePayload) -> str` — Serialize a resumed action into a structured user-message query string.
- `def setup_deeplink_routes(app: web.Application, service: DeepLinkService, invoker: ResumeInvoker, *, path: str='/api/v1/a2ui/resume/web') -> DeepLinkResumeHandler` — Register the web resume routes on ``app`` and return the handler.
