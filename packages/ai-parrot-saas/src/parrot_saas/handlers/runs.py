"""HTTP surface for flow execution records.

Read-only. A run is started by ingest — a signed webhook or the simulate
endpoint — never by a request to this resource, because starting one spends
the tenant's own LLM budget and that decision belongs at the point a review
is admitted, not at a URL anyone with read access can hit.

Resuming a suspended run is deliberately absent too. ``AgentsFlow.resume()``
cannot rebuild a graph of custom node types today (it falls back to a generic
constructor that fails on any node with live dependencies), so an endpoint
here would be a promise the engine cannot keep. It arrives with the core
change that fixes that.

The tenant comes from the middleware, never from the path or the body: a run
id is a UUID and nothing about it is secret, so ``tenant_id`` in the ``WHERE``
clause is the only thing standing between a caller and another tenant's runs.
"""
from __future__ import annotations

from typing import Any, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView

from ..tenancy.middleware import current_tenant
from .authz import check_policy
from .tenants import json_error

#: Key under which ``setup_saas_api`` publishes the run repository.
APP_RUN_REPOSITORY = "saas_runs"

#: PBAC resource these routes are gated by, under the shared ``saas`` type.
PBAC_RESOURCE_NAME = "runs"

#: Upper bound on a page. Runs carry a per-node array, so an unbounded listing
#: is a large response as well as a large query.
MAX_LIMIT = 200

logger = logging.getLogger("parrot_saas.handlers.runs")


class _RunViewBase(BaseView):
    """Shared plumbing for the run routes."""

    def _tenant(self):
        """Return the tenant resolved by the middleware."""
        return current_tenant(self.request)

    def _repository(self) -> Optional[Any]:
        """Return the run repository published on the app."""
        return self.request.app.get(APP_RUN_REPOSITORY)

    async def _authorize(self) -> Optional[web.Response]:
        """Check the read policy."""
        return await check_policy(
            self.request,
            "saas:run:read",
            PBAC_RESOURCE_NAME,
            subject=self._tenant().tenant_id,
        )

    def _unavailable(self) -> web.Response:
        """Explain that no run repository is configured."""
        return json_error(
            503,
            "runs_unavailable",
            "no run repository is configured; call setup_saas_api(app)",
        )


class RunCollectionView(_RunViewBase):
    """List this tenant's runs."""

    _logger_name: str = "parrot_saas.RunCollectionView"

    async def get(self) -> web.Response:
        """Return the tenant's runs, newest first.

        Filters: ``status`` and ``review_id``. The second is the one an
        operator actually reaches for — "what happened to this review?" — and
        it is why the run row keeps ``review_id`` rather than only the reverse
        link.
        """
        denied = await self._authorize()
        if denied is not None:
            return denied
        runs = self._repository()
        if runs is None:
            return self._unavailable()

        query = self.request.rel_url.query
        try:
            limit = min(int(query.get("limit", 50)), MAX_LIMIT)
            offset = max(int(query.get("offset", 0)), 0)
        except ValueError:
            return json_error(
                400, "invalid_query", "'limit' and 'offset' must be integers"
            )

        tenant = self._tenant()
        records = await runs.list_runs(
            tenant.tenant_id,
            status=query.get("status") or None,
            review_id=query.get("review_id", ""),
            limit=limit,
            offset=offset,
        )
        return web.json_response(
            {
                "runs": [run.to_json() for run in records],
                "count": len(records),
                "limit": limit,
                "offset": offset,
            }
        )


class RunItemView(_RunViewBase):
    """Read one run."""

    _logger_name: str = "parrot_saas.RunItemView"

    async def get(self) -> web.Response:
        """Return one run, or 404.

        A run belonging to another tenant is a 404 rather than a 403: the
        repository query is tenant-scoped, so this handler genuinely cannot
        tell the two apart — and that is the right answer anyway, since a 403
        would confirm the id exists.
        """
        denied = await self._authorize()
        if denied is not None:
            return denied
        runs = self._repository()
        if runs is None:
            return self._unavailable()

        run_id = self.request.match_info.get("run_id", "")
        record = await runs.get(self._tenant().tenant_id, run_id)
        if record is None:
            return json_error(404, "unknown_run", f"no run {run_id!r}")
        return web.json_response(record.to_json())


def setup_run_routes(
    app: web.Application, *, base: str = "/api/v1/saas/runs"
) -> None:
    """Register the run routes.

    Args:
        app: The aiohttp application.
        base: Base path for the collection.
    """
    _app = app.get_app() if hasattr(app, "get_app") else app
    _app.router.add_view(base, RunCollectionView)
    _app.router.add_view(f"{base}/{{run_id}}", RunItemView)


__all__ = (
    "APP_RUN_REPOSITORY",
    "MAX_LIMIT",
    "RunCollectionView",
    "RunItemView",
    "setup_run_routes",
)
