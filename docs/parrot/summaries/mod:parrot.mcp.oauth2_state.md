---
type: Wiki Summary
title: parrot.mcp.oauth2_state
id: mod:parrot.mcp.oauth2_state
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared in-process state for MCP OAuth2 callback coordination.
relates_to:
- concept: func:parrot.mcp.oauth2_state.deregister_pending_callback
  rel: defines
- concept: func:parrot.mcp.oauth2_state.is_pending
  rel: defines
- concept: func:parrot.mcp.oauth2_state.register_pending_callback
  rel: defines
- concept: func:parrot.mcp.oauth2_state.resolve_pending_callback
  rel: defines
---

# `parrot.mcp.oauth2_state`

Shared in-process state for MCP OAuth2 callback coordination.

When a user starts an OAuth2 authorization code flow, the MCP transport
creates an ``asyncio.Event`` and places it in ``_pending_mcp_callbacks``
keyed by the OAuth2 ``state`` parameter.  Once the Navigator callback
route receives the redirect from the authorization server, it looks up
the event by state and signals it so the transport can complete the
token exchange.

Both the transport layer (``parrot.mcp.transports.http``) and the
callback route (``parrot.auth.oauth2_routes``) import from this module
so they share the same ``_pending_mcp_callbacks`` dict.

Note: This is an in-process dict; it does not survive restarts and is not
safe for multi-process deployments.  A Redis-backed alternative can replace
it without changing the public API.

## Functions

- `def register_pending_callback(state: str) -> Tuple[asyncio.Event, Dict[str, str]]` — Register a pending OAuth2 callback for the given state parameter.
- `def resolve_pending_callback(state: str, code: str) -> bool` — Resolve a pending OAuth2 callback by signalling the event.
- `def is_pending(state: str) -> bool` — Return ``True`` if there is a pending callback for the given state.
- `def deregister_pending_callback(state: str) -> None` — Remove a pending callback entry without signalling it.
