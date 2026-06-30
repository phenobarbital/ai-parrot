"""OOB Fireflies API-key capture route for the MSAgentSDK example.

FEAT-264 / TASK-1677

This module mounts a minimal aiohttp handler at ``/auth/fireflies/capture``
(GET for the form, POST for submission).  When the user submits their
Fireflies.ai API key:

1. The key is stored per-user via :meth:`FirefliesCredentialResolver.store_key`.
2. If a ``nonce`` query parameter is present (embedded by
   :meth:`~parrot.integrations.msagentsdk.agent.ParrotM365Agent._handle_message`
   when the turn was suspended), the agent is proactively resumed via
   :meth:`~parrot.integrations.msagentsdk.agent.ParrotM365Agent.resume_by_nonce`.

Usage::

    from examples.msagent.capture import register_capture_routes
    register_capture_routes(app, fireflies_resolver=resolver, m365_agent=wrapper.m365_agent)

The capture page is intentionally minimal (no CSS / JS) — it is a demo, not
a production UI.  Operators replace it with their own front-end.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Optional

from aiohttp import web

logger = logging.getLogger(__name__)


def register_capture_routes(
    app: web.Application,
    fireflies_resolver: Any,
    m365_agent: Optional[Any] = None,
) -> None:
    """Register the Fireflies OOB capture GET/POST routes on *app*.

    Args:
        app: The running aiohttp :class:`web.Application`.
        fireflies_resolver: A :class:`~parrot.integrations.mcp.fireflies_a2a.FirefliesCredentialResolver`
            (or any object with an async ``store_key(user_id, api_key)`` method).
        m365_agent: Optional :class:`~parrot.integrations.msagentsdk.agent.ParrotM365Agent`
            — when supplied, a successful key submission triggers proactive resume via
            :meth:`resume_by_nonce` (FEAT-264 / TASK-1674).
    """
    app["_fireflies_resolver"] = fireflies_resolver
    app["_m365_agent"] = m365_agent

    app.router.add_get("/auth/fireflies/capture", _capture_get)
    app.router.add_post("/auth/fireflies/capture", _capture_post)
    logger.info("Fireflies capture routes registered: GET/POST /auth/fireflies/capture")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _capture_get(request: web.Request) -> web.Response:
    """Render the API-key submission form.

    Query parameters:
        nonce: Optional per-interaction nonce (for proactive resume).
        user_id: Optional user identity hint (pre-fills the form for UX).

    Returns:
        HTML response with a minimal submission form.
    """
    nonce = request.rel_url.query.get("nonce", "")
    user_id = request.rel_url.query.get("user_id", "")

    # Escape any user-supplied values before embedding in HTML.
    safe_nonce = html.escape(nonce)
    safe_user_id = html.escape(user_id)

    body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Authorise Fireflies.ai</title></head>
<body>
  <h2>Authorise Fireflies.ai</h2>
  <p>Paste your <strong>Fireflies.ai API key</strong> below.
     You can find it at <a href="https://app.fireflies.ai/login#apikey"
     target="_blank">app.fireflies.ai → API Keys</a>.</p>
  <form method="POST" action="/auth/fireflies/capture">
    <input type="hidden" name="nonce" value="{safe_nonce}">
    <label>Your canonical user ID (email / Entra OID):
      <input type="text" name="user_id" value="{safe_user_id}"
             placeholder="user@example.com" required>
    </label><br><br>
    <label>Fireflies API key:
      <input type="password" name="api_key" placeholder="Paste your API key" required>
    </label><br><br>
    <button type="submit">Save &amp; continue</button>
  </form>
</body>
</html>"""
    return web.Response(text=body, content_type="text/html")


async def _capture_post(request: web.Request) -> web.Response:
    """Process the submitted API key.

    Form fields:
        user_id: Canonical user identity (email / Entra OID).
        api_key: The Fireflies.ai API key.
        nonce: Optional per-interaction nonce for proactive resume.

    Returns:
        HTML confirmation page.
    """
    try:
        data = await request.post()
    except Exception as exc:
        logger.warning("Fireflies capture: failed to parse form data: %s", exc)
        return web.Response(text="Bad request", status=400)

    user_id: str = data.get("user_id", "").strip()  # type: ignore[assignment]
    api_key: str = data.get("api_key", "").strip()  # type: ignore[assignment]
    nonce: str = data.get("nonce", "").strip()  # type: ignore[assignment]

    if not user_id or not api_key:
        return web.Response(
            text="Missing user_id or api_key. Please go back and fill in both fields.",
            status=400,
        )

    # Store the key per-user.
    resolver = request.app.get("_fireflies_resolver")
    if resolver is None:
        logger.error("Fireflies capture: no resolver configured on app")
        return web.Response(text="Server misconfiguration. Contact the administrator.", status=500)

    try:
        await resolver.store_key(user_id, api_key)
        logger.info(
            "Fireflies capture: API key stored for user=%s (key redacted)", user_id
        )
    except Exception as exc:
        logger.error("Fireflies capture: store_key failed for user=%s: %s", user_id, exc)
        return web.Response(
            text="Failed to store your API key. Please try again.", status=500
        )

    # Proactive resume (FEAT-264 / TASK-1674): if a nonce was embedded in the
    # capture URL (by ParrotM365Agent on suspension), resume the chat turn.
    resumed = False
    m365_agent = request.app.get("_m365_agent")
    if m365_agent is not None and nonce:
        try:
            resumed = await m365_agent.resume_by_nonce(nonce)
            if resumed:
                logger.info(
                    "Fireflies capture: proactive resume triggered for nonce=%s user=%s",
                    nonce,
                    user_id,
                )
        except Exception as exc:
            logger.warning(
                "Fireflies capture: resume_by_nonce failed for nonce=%s: %s",
                nonce,
                exc,
            )

    # Render confirmation page.
    resume_note = (
        "<p><strong>Your chat session is resuming</strong> — the bot will send your "
        "result shortly.</p>"
        if resumed
        else "<p>You can return to the chat and retry your request — the bot now has "
        "access to your Fireflies data.</p>"
    )
    body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Fireflies.ai Authorised</title></head>
<body>
  <h2>Fireflies.ai Authorised</h2>
  <p>Your API key has been saved. Fireflies.ai is now available for your account.</p>
  {resume_note}
</body>
</html>"""
    return web.Response(text=body, content_type="text/html")
