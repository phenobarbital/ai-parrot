"""Canonical PBAC ``EvalContext`` builder for AI-Parrot (FEAT-446).

Consolidates the three eval-context builders that previously lived
independently in ``parrot/auth/agent_guard.py``,
``parrot-server/handlers/bots.py`` (``_PBACHandlerMixin``), and
``parrot-server/handlers/agent.py`` into a single implementation so S1
(FEAT-442 program) has exactly one place to inject ``tenant_id``.

Public API:
    - ``build_eval_context``: Build a navigator-auth ``EvalContext`` from
      an aiohttp request's authenticated session (fail-open ``None`` when
      the session or navigator-auth is unavailable).
"""
from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger("parrot.auth.eval_context")


async def build_eval_context(request: web.Request) -> object | None:
    """Build a navigator-auth ``EvalContext`` from an aiohttp request.

    Reads the authenticated session (populated by Guardian middleware on
    ``request.session``, falling back to ``navigator_session.get_session``)
    and constructs the ``EvalContext`` navigator-auth's ``PolicyEvaluator``
    expects: it is a required-positional-args constructor —
    ``EvalContext(request, user, userinfo, session, *, org_id=None,
    client_id=None)`` — and ``PolicyEvaluator._build_user_context`` reads
    ``ctx.userinfo`` / ``ctx.user`` (not flat ``username``/``groups``/
    ``roles`` kwargs) to resolve the evaluation subject.

    Args:
        request: The incoming aiohttp request with a Guardian-populated
            session (or one resolvable via ``navigator_session.get_session``).

    Returns:
        An ``EvalContext`` instance, or ``None`` if navigator-auth is not
        installed, the session is unavailable, or construction fails
        (fail-open — callers must handle ``None``).
    """
    try:
        from navigator_auth.abac.context import EvalContext
    except ImportError as exc:
        logger.debug(
            "eval_context: navigator-auth ABAC module not available (fail-open): %s",
            exc,
        )
        return None

    try:
        session = getattr(request, "session", None)
        if session is None:
            try:
                from navigator_session import get_session
                session = await get_session(request)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug(
                    "eval_context: could not retrieve session (fail-open): %s", exc
                )
                return None
        if session is None:
            return None

        try:
            from navigator_auth.conf import (
                AUTH_SESSION_OBJECT as _AUTH_SESSION,
            )
        except ImportError:
            _AUTH_SESSION = "userinfo"

        userinfo = session.get(_AUTH_SESSION, {}) if hasattr(session, "get") else {}
        user = session.decode("user") if hasattr(session, "decode") else None
        if user is None and isinstance(userinfo, dict) and userinfo:
            user = userinfo

        return EvalContext(
            request=request,
            user=user,
            userinfo=userinfo,
            session=session,
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "eval_context: failed to build EvalContext (fail-open): %s", exc
        )
        return None
