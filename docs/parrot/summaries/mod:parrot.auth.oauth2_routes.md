---
type: Wiki Summary
title: parrot.auth.oauth2_routes
id: mod:parrot.auth.oauth2_routes
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generic OAuth 2.0 callback routes for AI-Parrot.
relates_to:
- concept: func:parrot.auth.oauth2_routes.handle_mcp_oauth2_callback
  rel: defines
- concept: func:parrot.auth.oauth2_routes.make_oauth2_callback
  rel: defines
- concept: func:parrot.auth.oauth2_routes.register_a2a_resume_hook
  rel: defines
- concept: func:parrot.auth.oauth2_routes.setup_mcp_oauth2_callback
  rel: defines
- concept: func:parrot.auth.oauth2_routes.setup_oauth2_routes
  rel: defines
- concept: mod:parrot.auth.oauth2.service
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.mcp.oauth2_state
  rel: references
---

# `parrot.auth.oauth2_routes`

Generic OAuth 2.0 callback routes for AI-Parrot.

Each :class:`parrot.auth.oauth2_base.AbstractOAuth2Manager` subclass mounts
a single callback route via :func:`setup_oauth2_routes`. The handler:

- Validates ``code`` and ``state`` query parameters.
- Locates the per-provider manager on the aiohttp app
  (``app[f"oauth2_manager_{provider_id}"]``).
- Delegates the token exchange to ``manager.handle_callback(code, state)``.
- For the web channel, persists the credential via
  :class:`parrot.auth.oauth2.service.IntegrationsService` and
  renders the existing ``web_oauth_success.html`` postMessage page.
- For the **A2A channel** (FEAT-260 / TASK-1645): when
  ``state_payload["a2a_interaction_id"]`` is present, calls the registered
  A2A resume hook — typically
  :meth:`~parrot.a2a.server.A2AServer.resume_from_oauth_callback` — to
  reload the suspended execution and call ``agent.resume()``.  The hook is
  stored on the aiohttp app under ``app["a2a_oauth_resume_hook"]`` via
  :func:`register_a2a_resume_hook`.  The package boundary (core ai-parrot
  vs. satellite ai-parrot-server) is respected: no direct import of
  :class:`~parrot.a2a.server.A2AServer` in this module.

The Jira-specific callback at ``/api/auth/jira/callback`` remains unchanged
(decision: parallel infrastructure, no Jira refactor in this branch).

## Functions

- `def register_a2a_resume_hook(app: web.Application, hook: Callable[[str], Coroutine[Any, Any, None]]) -> None` — Register an async callable to resume suspended A2A tasks after OAuth.
- `def make_oauth2_callback(provider_id: str)` — Return a request handler bound to ``provider_id``.
- `def setup_oauth2_routes(app: web.Application, provider_id: str, callback_path: str) -> None` — Attach the OAuth2 callback route for ``provider_id`` to *app*.
- `async def handle_mcp_oauth2_callback(request: web.Request) -> web.Response` — Handle OAuth2 callback for MCP server authorization code flows.
- `def setup_mcp_oauth2_callback(app: web.Application) -> None` — Register the MCP OAuth2 callback route on *app*.
