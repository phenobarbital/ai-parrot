"""Shared in-process state for MCP OAuth2 callback coordination.

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
"""
from __future__ import annotations

import asyncio
from typing import Dict, Tuple

# State value: (event, result_dict)
# - event: asyncio.Event set by the callback route when the code arrives
# - result_dict: populated with {"code": ..., "state": ...} by the callback
_pending_mcp_callbacks: Dict[str, Tuple[asyncio.Event, Dict[str, str]]] = {}


def register_pending_callback(state: str) -> Tuple[asyncio.Event, Dict[str, str]]:
    """Register a pending OAuth2 callback for the given state parameter.

    The transport layer calls this to get the event/result pair before
    opening the browser.  The callback route calls
    :func:`resolve_pending_callback` when the code arrives.

    Args:
        state: OAuth2 state parameter (must be unique per flow).

    Returns:
        Tuple of (asyncio.Event, result_dict).  The event is set when
        the callback is received; result_dict is populated with
        ``{"code": ..., "state": ...}``.
    """
    event: asyncio.Event = asyncio.Event()
    result: Dict[str, str] = {}
    _pending_mcp_callbacks[state] = (event, result)
    return event, result


def resolve_pending_callback(
    state: str,
    code: str,
) -> bool:
    """Resolve a pending OAuth2 callback by signalling the event.

    Called by the Navigator callback route after validating the incoming
    redirect.  Pops the entry from the dict (preventing replay) and sets
    the event so the waiting transport coroutine can continue.

    Args:
        state: OAuth2 state parameter identifying the pending flow.
        code: Authorization code from the authorization server.

    Returns:
        ``True`` if the callback was found and resolved, ``False`` if the
        state was unknown or already consumed.
    """
    entry = _pending_mcp_callbacks.pop(state, None)
    if entry is None:
        return False
    event, result = entry
    result["code"] = code
    result["state"] = state
    event.set()
    return True


def is_pending(state: str) -> bool:
    """Return ``True`` if there is a pending callback for the given state.

    Args:
        state: OAuth2 state parameter.

    Returns:
        ``True`` if the state is registered, ``False`` otherwise.
    """
    return state in _pending_mcp_callbacks


def deregister_pending_callback(state: str) -> None:
    """Remove a pending callback entry without signalling it.

    Call this when the transport times out waiting for the callback, to prevent
    the abandoned state entry from accumulating in ``_pending_mcp_callbacks``
    indefinitely.

    Args:
        state: OAuth2 state parameter to remove.
    """
    _pending_mcp_callbacks.pop(state, None)
