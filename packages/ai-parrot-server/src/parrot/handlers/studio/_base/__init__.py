"""Studio shared base view — session/ownership/PBAC helpers (FEAT-467 TASK-2511).

``StudioBaseView`` is the common ancestor for every ``handlers/studio/*``
view. It intentionally carries NO endpoint behavior — only the plumbing
every Studio handler needs: session/user resolution, ownership
enforcement (with admin/superuser bypass), traversal-safe path
resolution, and fail-open PBAC checks under the ``astudio:<area>``
resource namespace (spec §2 — PBAC ids namespaced ``astudio:<area>``,
superuser/admin bypasses ownership, fail-open when no PDP is configured).

It is a package since the oversize-module split (owner decision D1): the view
class lives here; the PBAC and storage/access helper groups are mixins in
``_pbac.py`` / ``_storage.py`` and the slug/path helpers + ``StudioUser`` in
``_helpers.py``. Every name importable from the old ``_base.py`` is re-exported.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, ClassVar

from aiohttp import web
from navigator.views import BaseView

from parrot.handlers.scope import RequestScope, get_scope_resolver, has_installed_resolver

from ._helpers import (
    AUTH_SESSION_OBJECT,
    STUDIO_SLUG_RE,
    SUPERUSER_GROUP,
    StudioUser,
    is_valid_slug,
    resolve_safe_path,
)
from ._pbac import _StudioPbacMixin
from ._storage import _StudioStorageMixin

__all__ = [
    "AUTH_SESSION_OBJECT",
    "STUDIO_SLUG_RE",
    "SUPERUSER_GROUP",
    "StudioBaseView",
    "StudioUser",
    "is_valid_slug",
    "resolve_safe_path",
]


class StudioBaseView(_StudioPbacMixin, _StudioStorageMixin, BaseView):
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

    _STUDIO_ENABLED_EXEMPT: ClassVar[bool] = False

    def _opted_in(self) -> bool:
        """Package X9: a scope resolver is installed on the app."""
        return has_installed_resolver(self.request.app)

    async def _scope(self) -> RequestScope:
        """Resolve the caller's scope once per request (lazy; never in ``__init__``)."""
        cached = getattr(self, "_studio_scope_cache", None)
        if cached is not None:
            return cached
        scope = await get_scope_resolver(self.request.app).resolve(self.request)
        if not scope.tenant:
            scope = dataclasses.replace(scope, tenant=None)
        self._studio_scope_cache = scope
        return scope

    @staticmethod
    def _json_error(message: str, code: str) -> dict:
        from ..models import StudioError  # lazy: models imports the manager

        return StudioError(message=message, code=code).model_dump()

    async def _studio_gate(self) -> None:
        """403 ``tenant_mismatch``, then 404 ``studio_disabled`` (unless exempt)."""
        declared = self.request.match_info.get("tenant")
        if declared is None and not self._opted_in():
            return
        scope = await self._scope()
        if declared is not None and declared != scope.tenant:
            raise web.HTTPForbidden(
                text=json.dumps(self._json_error("Tenant mismatch.", "tenant_mismatch")),
                content_type="application/json",
            )
        if not scope.studio_enabled and not self._STUDIO_ENABLED_EXEMPT:
            raise web.HTTPNotFound(
                text=json.dumps(self._json_error("Agent Studio is disabled.", "studio_disabled")),
                content_type="application/json",
            )

    async def _iter(self):  # aiohttp ``web.View`` verb dispatch
        """Run the scope gate before any verb handler (opted-in or ``{tenant}`` routes only)."""
        await self._studio_gate()
        return await super()._iter()

    async def _require_author(self) -> web.Response | None:
        """403 ``authoring_denied`` when the resolved scope may not author; ``None`` otherwise."""
        if not self._opted_in():
            return None
        if (await self._scope()).may_author:
            return None
        return self.json_response(self._json_error("Authoring is not allowed.", "authoring_denied"), status=403)

    def _not_found(self, kind: str, name: str) -> web.Response:
        """One 404 body for invisible and absent records."""
        body = self._json_error(f"{kind.capitalize()} '{name}' not found.", "not_found")
        return self.json_response(body, status=404)

    def _name_taken(self, slug: str) -> web.Response:
        """Non-enumerating 409: no owner, source or tenant."""
        body = self._json_error(f"Name '{slug}' is not available.", "name_taken")
        return self.json_response(body, status=409)

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
        user = StudioUser(
            user_id=str(user_id),
            email=userinfo.get("email"),
            username=userinfo.get("username"),
            groups=list(userinfo.get("groups", []) or []),
            is_superuser=self._is_superuser(userinfo, user_obj),
        )
        if not self._opted_in():
            return user
        scope = await self._scope()
        if not scope.user_id:
            raise web.HTTPUnauthorized(reason="User ID not found in scope.")
        return dataclasses.replace(
            user,
            user_id=str(scope.user_id),
            is_superuser=scope.is_superuser,
            groups=sorted(scope.groups),
            tenant=scope.tenant,
            may_author=scope.may_author,
            may_administer=scope.may_administer,
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
