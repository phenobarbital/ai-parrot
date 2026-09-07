"""Control-plane HTTP surface for tenant lifecycle.

These routes are exempt from tenant resolution — they carry the tenant in the
path and are gated by an admin policy — so they are the one place in the SaaS
plane that legitimately spans tenants.

**On error responses.** ``BaseView.error()`` is not used here. It ``raise``s
rather than returns, and its status mapping only covers 400/401/403/404/406/
412/428 — every other status silently becomes ``HTTPBadRequest``. A 409 for a
duplicate slug would therefore reach the client as a 400, and the repository
already contains a case of that mistake (``handlers/threads.py`` asks for 503
and emits 400). Errors here are built with :func:`aiohttp.web.json_response`,
which says what it means.
"""
from __future__ import annotations

from typing import Any, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from pydantic import ValidationError

from ..tenancy.context import TenantStatus
from ..tenancy.models import TenantCreate, TenantUpdate
from ..tenancy.repository import TenantAlreadyExists

#: Key under which ``setup_saas_api`` publishes the tenant repository.
APP_TENANT_REPOSITORY = "saas_tenants"
#: Key under which ``setup_saas_api`` publishes the runtime cache.
APP_TENANT_RUNTIMES = "saas_tenant_runtimes"

logger = logging.getLogger("parrot_saas.handlers.tenants")


def json_error(status: int, code: str, message: str, **extra: Any) -> web.Response:
    """Build a JSON error response with an honest status code.

    Args:
        status: HTTP status to actually emit.
        code: Machine-readable error code.
        message: Human-readable explanation.
        **extra: Additional fields to include.

    Returns:
        The response.
    """
    return web.json_response(
        {"error": code, "message": message, **extra}, status=status
    )


class _TenantViewBase(BaseView):
    """Shared plumbing for the control-plane views."""

    def _repository(self) -> Any:
        """Return the tenant repository published on the app."""
        try:
            return self.request.app[APP_TENANT_REPOSITORY]
        except KeyError as exc:  # pragma: no cover - misconfiguration
            raise RuntimeError(
                "tenant repository is not configured; call setup_saas_api(app)"
            ) from exc

    def _runtimes(self) -> Optional[Any]:
        """Return the runtime cache, when one is configured."""
        return self.request.app.get(APP_TENANT_RUNTIMES)

    async def _body(self) -> tuple[Optional[dict], Optional[web.Response]]:
        """Parse the JSON body, distinguishing absent from malformed.

        ``BaseView.get_json`` swallows a decode error and returns ``None``, so
        an empty body and a broken one are indistinguishable through it. That
        matters for PATCH, where an empty body is legitimate. This reads the
        raw text and decides.

        Returns:
            ``(payload, None)`` on success, or ``(None, response)`` when the
            body could not be parsed.
        """
        import json

        raw = (await self.request.text()).strip()
        if not raw:
            return {}, None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return None, json_error(
                400, "invalid_json", f"request body is not valid JSON: {exc}"
            )
        if not isinstance(payload, dict):
            return None, json_error(
                400, "invalid_json", "request body must be a JSON object"
            )
        return payload, None

    @staticmethod
    def _validation_error(exc: ValidationError) -> web.Response:
        """Render a Pydantic validation failure as a 400."""
        return json_error(
            400,
            "validation_error",
            "the request payload is not valid",
            details=[
                {"field": ".".join(str(p) for p in err["loc"]), "error": err["msg"]}
                for err in exc.errors()
            ],
        )


class TenantCollectionView(_TenantViewBase):
    """List and create tenants."""

    _logger_name: str = "parrot_saas.TenantCollectionView"

    async def get(self) -> web.Response:
        """List tenants across the deployment.

        Query parameters:
            status: Optional lifecycle filter.
            limit: Maximum rows (default 100).
            offset: Rows to skip (default 0).
        """
        args = self.get_arguments(self.request)
        status_raw = args.get("status")
        try:
            status = TenantStatus(status_raw) if status_raw else None
        except ValueError:
            return json_error(
                400,
                "invalid_status",
                f"unknown status {status_raw!r}; expected one of "
                f"{[s.value for s in TenantStatus]}",
            )
        try:
            limit = min(max(int(args.get("limit", 100)), 1), 500)
            offset = max(int(args.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return json_error(
                400, "invalid_paging", "limit and offset must be integers"
            )

        tenants = await self._repository().list_tenants(
            status=status, limit=limit, offset=offset
        )
        return web.json_response(
            {
                "tenants": [t.model_dump(mode="json") for t in tenants],
                "count": len(tenants),
            }
        )

    async def post(self) -> web.Response:
        """Onboard a tenant."""
        payload, error = await self._body()
        if error is not None:
            return error
        try:
            create = TenantCreate(**payload)
        except ValidationError as exc:
            return self._validation_error(exc)

        try:
            tenant = await self._repository().create(create)
        except TenantAlreadyExists:
            # 409, emitted directly: BaseView.error() would degrade it to 400.
            return json_error(
                409,
                "tenant_exists",
                f"tenant {create.tenant_id!r} already exists",
            )
        logger.info("tenant onboarded: %s", tenant.tenant_id)
        return web.json_response(tenant.model_dump(mode="json"), status=201)


class TenantItemView(_TenantViewBase):
    """Read, amend and retire a single tenant."""

    _logger_name: str = "parrot_saas.TenantItemView"

    def _tenant_id(self) -> str:
        """Return the tenant slug from the path."""
        return self.request.match_info.get("tenant_id", "")

    async def get(self) -> web.Response:
        """Return one tenant."""
        tenant_id = self._tenant_id()
        tenant = await self._repository().get(tenant_id)
        if tenant is None:
            return json_error(404, "unknown_tenant", f"no such tenant: {tenant_id!r}")
        return web.json_response(tenant.model_dump(mode="json"))

    async def patch(self) -> web.Response:
        """Amend a tenant, then invalidate its cached runtime.

        The invalidation is the point of doing this here rather than in the
        repository: a live runtime holds agents built from the tenant's old
        settings, so a configuration change that did not evict it would appear
        to have no effect until the cache expired.
        """
        tenant_id = self._tenant_id()
        payload, error = await self._body()
        if error is not None:
            return error
        try:
            patch = TenantUpdate(**payload)
        except ValidationError as exc:
            return self._validation_error(exc)

        tenant = await self._repository().update(tenant_id, patch)
        if tenant is None:
            return json_error(404, "unknown_tenant", f"no such tenant: {tenant_id!r}")

        runtimes = self._runtimes()
        if runtimes is not None:
            await runtimes.invalidate(tenant_id)
        return web.json_response(tenant.model_dump(mode="json"))

    async def delete(self) -> web.Response:
        """Retire a tenant by suspending it.

        A soft delete: the tenant's coupons, replies and provisioned
        infrastructure reference this row, and removing it would orphan them
        and destroy the audit trail.
        """
        tenant_id = self._tenant_id()
        tenant = await self._repository().delete(tenant_id)
        if tenant is None:
            return json_error(404, "unknown_tenant", f"no such tenant: {tenant_id!r}")

        runtimes = self._runtimes()
        if runtimes is not None:
            await runtimes.invalidate(tenant_id)
        logger.info("tenant suspended: %s", tenant_id)
        return web.json_response(tenant.model_dump(mode="json"))


def setup_tenant_routes(
    app: web.Application, *, base: str = "/api/v1/saas/control/tenants"
) -> None:
    """Register the control-plane tenant routes.

    Args:
        app: The aiohttp application.
        base: Base path for the collection.
    """
    _app = app.get_app() if hasattr(app, "get_app") else app
    _app.router.add_view(base, TenantCollectionView)
    _app.router.add_view(f"{base}/{{tenant_id}}", TenantItemView)


__all__ = (
    "APP_TENANT_REPOSITORY",
    "APP_TENANT_RUNTIMES",
    "TenantCollectionView",
    "TenantItemView",
    "json_error",
    "setup_tenant_routes",
)
