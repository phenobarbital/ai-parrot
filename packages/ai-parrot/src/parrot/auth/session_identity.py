"""Backend-independent resolution of the authenticated user's id.

navigator-auth does **not** guarantee a flat ``user_id`` anywhere. What a
backend puts in the session is driven by its own ``userid_attribute``, which
differs per backend — ``user_id`` (BasicAuth / Troc / Django), ``id``
(Azure), ``login`` (GitHub), ``upn`` (ADFS), ``object_id`` (SAML),
``userid`` (NoAuth) — and by the deployment-level ``AUTH_USERID_ATTRIBUTE``
setting. Reading ``session["user_id"]`` therefore only works for the
BasicAuth-shaped backends; nothing at all sets ``request["user_id"]``.

The one field EVERY backend populates is ``Identity.id`` on the
:class:`navigator_auth.identities.AuthUser` object that the auth middleware
and ``@user_session()`` attach to ``request.user`` (and, for class-based
views, to ``self.user``). ``Identity.id`` is typed ``Any``: an ``int``
primary key for DB-backed users, a string for token/external identities —
so callers that key caches, memory, or permission principals by it must
normalize it to ``str``, which :func:`resolve_user_id` does.

Public API:
    - :func:`resolve_session_user`: the ``AuthUser``/``Identity`` object.
    - :func:`resolve_user_id`: that object's id as a string.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("parrot.auth.session_identity")

__all__ = ["resolve_session_user", "resolve_user_id"]

# Attribute names carrying an id on an ``Identity``/``AuthUser``, most
# canonical first. ``id`` is ``Identity``'s own required column; the rest
# cover backends that also expose their native attribute on the object.
_IDENTITY_ID_ATTRS: tuple[str, ...] = ("id", "user_id", "userid", "object_id", "upn", "username")


def _conf(name: str, fallback: str) -> str:
    """Read a navigator-auth conf value, falling back when it is unavailable.

    Args:
        name: The ``navigator_auth.conf`` attribute to read.
        fallback: Value to use when navigator-auth is not installed.

    Returns:
        The configured value, or ``fallback``.
    """
    try:
        import navigator_auth.conf as _auth_conf

        return getattr(_auth_conf, name, fallback)
    except ImportError:  # pragma: no cover - navigator-auth always present in server
        return fallback


def resolve_session_user(request: Any) -> Any | None:
    """Return the ``AuthUser``/``Identity`` navigator-auth attached, if any.

    The auth middleware sets both ``request.user`` (attribute) and
    ``request["user"]`` (mapping key, ``SESSION_USER_PROPERTY``); the
    ``@user_session()`` decorator sets the same object on the view. Both
    forms are checked because a handler may run behind either.

    Args:
        request: The incoming aiohttp request.

    Returns:
        The identity object, or ``None`` when the request is unauthenticated.
    """
    user = getattr(request, "user", None)
    if user is None:
        try:
            user = request.get("user")
        except (AttributeError, TypeError):
            user = None
    return user


def _first_attr(obj: Any, names: tuple[str, ...]) -> Any | None:
    """Return the first non-empty attribute/key of ``obj`` among ``names``."""
    for name in names:
        value = getattr(obj, name, None)
        if value is None and isinstance(obj, dict):
            value = obj.get(name)
        if value not in (None, ""):
            return value
    return None


def resolve_user_id(request: Any, session: Any = None) -> str | None:
    """Resolve the authenticated user's id as a string, backend-independently.

    Resolution order (first non-empty wins):

    1. ``request.user`` / ``request["user"]`` -> ``Identity.id`` (the only
       field every navigator-auth backend sets), then that object's native
       id attributes and finally its ``username``.
    2. The session's flat ``AUTH_USERID_ATTRIBUTE`` key (``user_id`` by
       default) — what BasicAuth-shaped backends write.
    3. The same key nested under ``AUTH_SESSION_OBJECT`` — navigator-auth's
       own fallback for external/OAuth2 backends (see
       ``backends/external.py``, which does exactly this two-step lookup).

    Args:
        request: The incoming aiohttp request.
        session: An already-resolved session (``SessionData``), when the
            caller has one. Optional — steps 2 and 3 are skipped without it.

    Returns:
        The user id as ``str``, or ``None`` when no identity can be
        resolved. Non-string ids (an ``int`` primary key, a ``UUID``) are
        coerced, so the value is safe to use as a cache/memory key or a
        permission principal.
    """
    user = resolve_session_user(request)
    user_id = _first_attr(user, _IDENTITY_ID_ATTRS) if user is not None else None

    if user_id in (None, "") and session is not None:
        userid_attr = _conf("AUTH_USERID_ATTRIBUTE", "user_id")
        session_object = _conf("AUTH_SESSION_OBJECT", "session")
        try:
            user_id = session.get(userid_attr) or session.get("user_id")
            if user_id in (None, ""):
                nested = session.get(session_object) or {}
                if isinstance(nested, dict):
                    user_id = nested.get(userid_attr) or nested.get("user_id")
        except (AttributeError, TypeError) as exc:
            logger.debug("session identity lookup failed (fail-open): %s", exc)
            user_id = None

    if user_id in (None, ""):
        return None
    return str(user_id)
