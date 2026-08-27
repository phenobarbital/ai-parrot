"""Studio shared base view — session/ownership/PBAC helpers (FEAT-467 TASK-2511).

``StudioBaseView`` is the common ancestor for every ``handlers/studio/*``
view. It intentionally carries NO endpoint behavior — only the plumbing
every Studio handler needs: session/user resolution, ownership
enforcement (with admin/superuser bypass), traversal-safe path
resolution, and fail-open PBAC checks under the ``astudio:<area>``
resource namespace (spec §2 — PBAC ids namespaced ``astudio:<area>``,
superuser/admin bypasses ownership, fail-open when no PDP is configured).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web
from navigator.views import BaseView

try:
    from navigator_auth.conf import AUTH_SESSION_OBJECT
except ImportError:  # pragma: no cover — navigator-auth always installed in prod
    AUTH_SESSION_OBJECT = "userinfo"

# PBAC (Policy-Based Access Control) — optional, fail-open if absent.
# Mirrors handlers/bots.py `_PBACHandlerMixin` exactly.
try:
    from navigator_auth.abac.policies.resources import ResourceType as _ResourceType

    _PBAC_AVAILABLE = True
except ImportError:
    _ResourceType = None
    _PBAC_AVAILABLE = False

# Canonical PBAC EvalContext builder (FEAT-446) — single source of truth.
from parrot.auth.eval_context import build_eval_context as _core_build_eval_context

# Superuser/admin group convention — mirrors
# navigator_auth.decorators.SUPERUSER_GROUP / `_check_superuser` (private
# helpers in that module; the check is small enough to replicate here
# rather than reach into navigator_auth internals).
SUPERUSER_GROUP = "superuser"

# Studio agent/asset slug convention — same regex as
# handlers/bots.py `_AGENT_SLUG_RE` (:85).
STUDIO_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


def is_valid_slug(value: str) -> bool:
    """Return ``True`` if ``value`` matches the Studio slug convention.

    Args:
        value: Candidate slug (agent name, skill name, draft name, ...).

    Returns:
        ``True`` when ``value`` matches ``^[a-z0-9_-]+$`` and is non-empty.
    """
    return bool(value) and bool(STUDIO_SLUG_RE.match(value))


def resolve_safe_path(base_dir: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``base_dir``, rejecting traversal escapes.

    Rejects absolute paths, ``..`` segments, and symlink escapes — any
    path that would resolve outside ``base_dir`` once both are fully
    resolved. Used by file/draft-management Studio endpoints (TASK-2513/
    TASK-2514) to keep on-disk writes sandboxed to their intended
    directory.

    Args:
        base_dir: The directory the resolved path MUST stay inside.
        relative: The caller-supplied relative path/filename.

    Returns:
        The resolved, safe ``Path``.

    Raises:
        ValueError: ``relative`` is empty, absolute, contains a ``..``
            segment, or resolves outside ``base_dir`` (including via a
            symlink escape).
    """
    if not relative:
        raise ValueError("Path must not be empty.")
    rel_path = Path(relative)
    if rel_path.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {relative!r}")
    if ".." in rel_path.parts:
        raise ValueError(f"Path traversal is not allowed: {relative!r}")

    base_resolved = Path(base_dir).resolve()
    candidate = (base_resolved / rel_path).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        raise ValueError(f"Resolved path escapes the sandboxed directory: {relative!r}") from None
    return candidate


@dataclass(slots=True)
class StudioUser:
    """Resolved caller identity for a Studio request.

    Attributes:
        user_id: The session's authenticated user id (always a string).
        email: Best-effort email from session userinfo, if present.
        username: Best-effort username from session userinfo, if present.
        groups: Group memberships from session userinfo (empty list if none).
        is_superuser: Derived admin/superuser flag — bypasses ownership
            checks in :meth:`StudioBaseView._require_owner`.
    """

    user_id: str
    email: str | None = None
    username: str | None = None
    groups: list[str] = field(default_factory=list)
    is_superuser: bool = False


class StudioBaseView(BaseView):
    """Shared base for every ``/api/v1/astudio/*`` handler.

    Subclasses are expected to be decorated ``@is_authenticated()`` +
    ``@user_session()`` at the class definition site (pattern:
    ``CredentialsHandler`` credentials.py:69-71, ``VectorStoreHandler``
    handler.py:35-37) — this base class does NOT apply those decorators
    itself so concrete handlers control (and make visible) their own auth
    requirements.

    Unlike ``AbstractModel``-based views, plain ``BaseView`` subclasses do
    NOT get ``self._session`` populated automatically (that only happens
    for ``AbstractModel`` — see ``navigator/views/abstract.py:395-397``,
    and the equivalent gotcha documented at
    ``handlers/comm_center.py:670-676``). Every helper below resolves the
    session explicitly via ``await self.session()``.
    """

    _logger_name = "Parrot.AgentStudio"

    async def _resolve_session(self) -> Any:
        """Resolve the current session, decorated or not.

        ``navigator_auth.decorators.user_session()``'s class-method wrapper
        OVERWRITES ``self.session`` with the already-resolved session
        VALUE (a dict/mapping) before the handler body runs — it does not
        leave the inherited ``BaseView.session()`` coroutine method in
        place. Concrete Studio handlers are always decorated
        ``@user_session()`` (see :class:`StudioBaseView` docstring), so by
        the time a real handler calls this, ``self.session`` is that
        already-resolved value. Undecorated/programmatic callers (unit
        tests instantiating a view directly) still see the original
        callable ``BaseView.session`` method — call it in that case.

        Returns:
            The resolved session (a dict/mapping), or whatever
            ``self.session()`` returns for undecorated call sites.
        """
        session_attr = self.session
        if callable(session_attr):
            return await session_attr()
        return session_attr

    async def _get_user(self) -> StudioUser:
        """Resolve the authenticated caller's identity from the session.

        Returns:
            A :class:`StudioUser` with ``user_id`` set from the session,
            plus best-effort ``email``/``username``/``groups`` and the
            derived ``is_superuser`` flag.

        Raises:
            web.HTTPUnauthorized: No usable session, or no ``user_id`` in it.
        """
        session = await self._resolve_session()
        if not session:
            raise web.HTTPUnauthorized(reason="Session not available.")
        user_id = await self.get_userid(session)
        if not user_id:
            raise web.HTTPUnauthorized(reason="User ID not found in session.")
        userinfo = session.get(AUTH_SESSION_OBJECT, {}) if hasattr(session, "get") else {}
        if not isinstance(userinfo, dict):
            userinfo = {}
        user_obj = None
        if hasattr(session, "decode"):
            try:
                user_obj = session.decode("user")
            except (AttributeError, TypeError, RuntimeError):
                user_obj = None
        return StudioUser(
            user_id=str(user_id),
            email=userinfo.get("email"),
            username=userinfo.get("username"),
            groups=list(userinfo.get("groups", []) or []),
            is_superuser=self._is_superuser(userinfo, user_obj),
        )

    @staticmethod
    def _is_superuser(userinfo: dict, user: Any = None) -> bool:
        """Derive admin/superuser status from session userinfo.

        Mirrors ``navigator_auth.decorators._check_superuser``: ``True``
        when ``userinfo["superuser"]``/``userinfo["is_superuser"]`` is
        ``True``, or the caller belongs to the ``superuser`` group (via
        ``userinfo["groups"]`` or ``user.groups``). Matches the existing
        convention used at ``handlers/agents/abstract.py:508``
        (``self._superuser = userinfo.get('superuser', False)``).

        Args:
            userinfo: The session's ``AUTH_SESSION_OBJECT`` dict.
            user: The decoded session user object, if any.

        Returns:
            ``True`` if the caller has superuser/admin privileges.
        """
        if userinfo.get("superuser") is True or userinfo.get("is_superuser") is True:
            return True
        groups = userinfo.get("groups")
        # Membership only on a real collection: `in` on a str is SUBSTRING
        # matching (same guard as navigator_auth._check_superuser).
        if isinstance(groups, (list, tuple, set, frozenset)) and SUPERUSER_GROUP in groups:
            return True
        if user is not None and hasattr(user, "groups"):
            for g in user.groups:
                name = getattr(g, "group", None) or getattr(g, "group_name", None)
                if name == SUPERUSER_GROUP:
                    return True
        return False

    def _require_owner(self, resource_owner: Any, user: StudioUser) -> None:
        """Raise 403 unless ``user`` owns the resource or is a superuser.

        Args:
            resource_owner: The resource's recorded owner (any
                stringifiable id — compared as strings so int/str/UUID
                owners all work).
            user: The resolved caller (see :meth:`_get_user`).

        Raises:
            web.HTTPForbidden: ``user`` is neither the owner nor a superuser.
        """
        if user.is_superuser:
            return
        if resource_owner is None or str(resource_owner) != str(user.user_id):
            raise web.HTTPForbidden(reason="You do not have permission to modify this resource.")

    # ------------------------------------------------------------------
    # PBAC (fail-open; pattern: handlers/bots.py `_PBACHandlerMixin`)
    # ------------------------------------------------------------------

    def _get_pbac_evaluator(self):
        """Return the PDP evaluator from ``app['abac']``, or ``None`` (fail-open).

        Returns:
            ``PolicyEvaluator`` instance when PBAC is configured, ``None``
            otherwise.
        """
        if not _PBAC_AVAILABLE:
            return None
        pdp = self.request.app.get("abac")
        return getattr(pdp, "_evaluator", None) if pdp is not None else None

    async def _build_eval_context(self):
        """Build the navigator-auth ``EvalContext`` for the current request.

        Returns:
            ``EvalContext`` instance, or ``None`` if unavailable
            (fail-open — callers must handle ``None``).
        """
        if not _PBAC_AVAILABLE:
            return None
        return await _core_build_eval_context(self.request)

    async def _pbac_allowed(self, resource: str, action: str) -> bool:
        """Fail-open PBAC check for a Studio resource id.

        Args:
            resource: Studio area, e.g. ``"agents"`` — namespaced
                internally to ``astudio:<resource>`` (spec §2: PBAC ids
                are ``astudio:<area>``, e.g. ``astudio:agents``,
                ``astudio:skills``, ``astudio:keys``).
            action: The action string, e.g. ``"astudio:agents:create"``.

        Returns:
            ``True`` when access is allowed OR when no PDP is configured
            (fail-open — same posture as ``_PBACHandlerMixin``); ``False``
            only on an explicit deny from a configured evaluator.
        """
        evaluator = self._get_pbac_evaluator()
        if evaluator is None:
            return True
        ctx = await self._build_eval_context()
        if ctx is None:
            return True
        resource_name = f"astudio:{resource}"
        try:
            result = evaluator.check_access(ctx, _ResourceType.URI, resource_name, action)
            return bool(getattr(result, "allowed", True))
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "Studio PBAC: evaluator error for resource=%s action=%s, " "failing open: %s",
                resource_name,
                action,
                exc,
            )
            return True
