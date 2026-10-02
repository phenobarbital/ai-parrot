"""Storage/access mixin of :class:`StudioBaseView` — partition, record access, guarded writes, error mapping."""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import AsyncIterator
from typing import Any

from aiohttp import web
from pydantic import ValidationError


class _StudioStorageMixin:
    """Database-mode plumbing shared by every Studio view (partition, access, TOCTOU-safe writes, X14 errors)."""

    async def _studio_partition(self) -> Any:
        """Storage partition: GLOBAL without a resolver; the caller's tenant when opted in (X5)."""
        from ..access import StudioTenantRequired
        from ..storage.models import StudioPartition

        if not self._opted_in():
            return StudioPartition.GLOBAL
        scope = await self._scope()
        if scope.tenant is None:
            raise StudioTenantRequired
        return StudioPartition.from_scope(scope)

    async def _tenantless(self) -> bool:
        """An opted-in caller whose scope carries no tenant (it can see no tenant-bound record)."""
        return self._opted_in() and (await self._scope()).tenant is None

    async def _access(self) -> Any:
        """Per-request :class:`StudioAccess` (lazy)."""
        from ..access import StudioAccess  # local import: access.py must never import _base

        if self._opted_in():
            return StudioAccess(await self._scope(), opted_in=True, app=self.request.app)
        user = await self._get_user()
        scope = dataclasses.replace(
            await self._scope(), user_id=user.user_id, is_superuser=user.is_superuser, groups=frozenset(user.groups)
        )
        return StudioAccess(scope, opted_in=False, app=self.request.app)

    async def _check_record_access(
        self, access: Any, rec: Any, kind: str, name: str, *, manage: bool = False
    ) -> web.Response | None:
        """404 when absent or invisible (one body, AC5); 403 when ``manage`` and not can_manage (AC6)."""
        if rec is None or not access.can_see(rec):
            return self._not_found(kind, name)
        if manage and not access.can_manage(rec):
            body = self._json_error("You do not have permission to modify this resource.", "forbidden")
            return self.json_response(body, status=403)
        return None

    def _tenant_required(self) -> web.Response:
        """422 ``tenant_required``."""
        return self.json_response(self._json_error("A tenant scope is required.", "tenant_required"), status=422)

    _VISIBILITY_MESSAGES = {
        "tenant_required": "A tenant scope is required for this visibility.",
        "groups_required": "allowed_groups is required when visibility is 'groups'.",
        "groups_not_allowed": "allowed_groups must be a subset of your own groups.",
    }

    def _visibility_refusal(self, access: Any, visibility: str, allowed_groups: Any) -> web.Response | None:
        """422 ``tenant_required`` / ``groups_required`` / ``groups_not_allowed`` for a requested visibility."""
        code = access.validate_visibility(visibility=visibility, allowed_groups=list(allowed_groups))
        if code is None:
            return None
        return self.json_response(self._json_error(self._VISIBILITY_MESSAGES[code], code), status=422)

    @contextlib.asynccontextmanager
    async def _bound_scope(self, agent: Any = None) -> AsyncIterator[None]:
        """Bind a ``RequestContext`` for the block (FEAT-622 M5): ``studio_scope`` only when a resolver is installed.

        With no resolver nothing is bound beyond the request itself, so a tenant-bound tool refuses ``no_scope``.
        The context is reset on exit, whatever the block did.
        """
        from parrot.utils.helpers import RequestContext, _current_ctx

        from ..access import build_tool_scope

        kwargs = {"studio_scope": build_tool_scope(await self._scope(), agent)} if self._opted_in() else {}
        token = _current_ctx.set(RequestContext(request=self.request, app=self.request.app, **kwargs))
        try:
            yield
        finally:
            _current_ctx.reset(token)

    def _scope_refusal(self, cls: Any, slug: str) -> web.Response | None:
        """403 ``tool_scope_unavailable`` (``details.reason``) when a tenant-bound ``cls`` has no valid scope.

        Runs before any construction / vault read: a refused request has no side effect (FEAT-622 M3b, R-b).
        """
        from parrot.tools.scope import ToolScopeUnavailable, ensure_tool_scope

        try:
            ensure_tool_scope(cls, tool_name=slug)
        except ToolScopeUnavailable as exc:
            return self._scope_error_response(str(exc), exc.reason)
        return None

    def _scope_error_response(self, message: str, reason: str) -> web.Response:
        """The 403 body of a scope refusal (``code`` + ``details.reason``)."""
        from ..models import StudioError  # lazy: models imports the manager

        body = StudioError(message=message, code="tool_scope_unavailable", details={"reason": reason})
        return self.json_response(body.model_dump(), status=403)

    def _studio_storage(self) -> Any:
        """The resolved ``StudioStorage`` memoised on the app."""
        from ..storage.models import StudioStorageUnavailable

        storage = self.request.app.get("studio_storage")
        if storage is None:   # the startup hook did not run → 503 studio_storage_unavailable
            raise StudioStorageUnavailable("studio storage was not resolved at startup")
        return storage

    def _reauthorize(self, kind: str, name: str, *, manage: bool = True, key: str = "agent_id"):
        """A ``reauthorize(rec)`` callback: the caller's access decision re-run on a freshly read record."""
        from ..access import _store_record  # local import: access.py must never import _base

        async def check(rec: Any) -> web.Response | None:
            access = await self._access()
            return await self._check_record_access(
                access, _store_record(kind, getattr(rec, key), rec), kind, name, manage=manage
            )

        return check

    async def _studio_write(self, write, *, record, reread, reauthorize, expected_version: int | None):
        """Run ``write(guard)`` under the version of ``record`` (the one the access decision authorized).

        On a stale authorization the record is re-read and the access decision is re-run on it
        (``reauthorize``): a refusal is returned (a ``web.Response``, nothing written); otherwise the write is
        retried once under the re-read version. A second stale authorization is a 409 ``version_conflict``.
        """
        from ..storage.models import StudioNotFound, StudioStaleAuthorization, StudioVersionConflict, StudioWriteGuard

        for attempt in (1, 2):
            guard = StudioWriteGuard.for_record(record, expected_version=expected_version)
            try:
                return await write(guard)
            except StudioStaleAuthorization as exc:
                if attempt == 2:
                    raise StudioVersionConflict("authorization went stale twice") from exc
                record = await reread()
                if record is None:
                    raise StudioNotFound("record vanished before the write") from exc
                if (denied := await reauthorize(record)) is not None:
                    return denied

    def _studio_error(self, exc: Exception) -> web.Response:
        """Map a storage/service exception to its X14 code and status (unmapped: logged, 500)."""
        from ..access import StudioTenantRequired
        from ..storage import models as m
        from ..storage.services._common import StudioValidationError

        table = (
            (m.StudioStorageUnavailable, 503, "studio_storage_unavailable"),
            ((m.StudioVersionConflict, m.StudioStaleAuthorization), 409, "version_conflict"),
            (m.StudioNameConflict, 409, "name_taken"),  # X14: never "duplicate"
            (m.StudioNotFound, 404, "not_found"),
            (m.StudioToolingRefused, 422, "tooling_not_permitted"),
            (m.StudioAssetTooLarge, 413, getattr(exc, "code", "asset_too_large")),
            (StudioValidationError, getattr(exc, "status", 422), getattr(exc, "code", "validation_error")),
        )
        if isinstance(exc, StudioTenantRequired):
            return self._tenant_required()
        if isinstance(exc, ValidationError):
            return self.json_response(self._json_error(f"Invalid request: {exc}", "validation_error"), status=422)
        for kinds, status, code in table:
            if isinstance(exc, kinds):
                message = "The name is not available." if code == "name_taken" else (str(exc) or code)   # non-enumerating
                return self.json_response(self._json_error(message, code), status=status)
        self.logger.error("Studio: unexpected storage error: %r", exc, exc_info=exc)
        return self.json_response(self._json_error("Internal server error.", "internal_error"), status=500)

    @staticmethod
    def _expected_version(source: Any) -> int | None:
        """``expected_version`` from a body mapping or a query; a non-integer is a 400."""
        from ..storage.services._common import StudioValidationError

        raw = source.get("expected_version") if hasattr(source, "get") else None
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise StudioValidationError("expected_version must be an integer", code="invalid_expected_version",
                                        status=400) from exc

    def _refuse_expected_version(self, source: Any) -> web.Response | None:
        """400 ``expected_version_unsupported`` when an unsupported route was sent one; ``None`` otherwise."""
        if not hasattr(source, "get") or source.get("expected_version") is None:
            return None
        body = self._json_error("expected_version is not supported on this route.", "expected_version_unsupported")
        return self.json_response(body, status=400)
