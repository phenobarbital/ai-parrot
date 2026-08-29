"""HTTP surface for review ingest and review reading.

Two entry points, authenticated in deliberately different ways.

**The webhook is authenticated by its signature, nothing else.** A review
platform registers a URL and POSTs to it; it sends no session and no tenant
header, so the tenant has to travel in the path and the route has to sit
outside the tenant-resolution middleware. That makes the split explicit: the
path says which tenant the request *claims* to be for, and the HMAC over the
body with that tenant's secret is what proves it. Claiming to be ``hotel-x``
without ``hotel-x``'s secret gets nowhere.

Because the middleware cannot run there, this handler repeats its checks by
hand — resolve the tenant, refuse an unknown or suspended one. That is not
redundant: skipping it would mean accepting reviews for a tenant that has been
retired.

**Everything else is ordinary.** Simulate and the read routes go through the
middleware, require a session, and ask the policy engine.
"""
from __future__ import annotations

import json
from typing import Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView

from .. import conf
from ..reviews.ingest import ReviewIngestService
from ..reviews.models import ReviewStatus
from ..reviews.webhook import secret_key_for
from ..tenancy.middleware import current_tenant
from .authz import check_policy
from .secrets import APP_SECRET_STORE_FACTORY
from .tenants import APP_TENANT_REPOSITORY, json_error

#: Key under which ``setup_saas_api`` publishes the review-source registry.
APP_REVIEW_SOURCES = "saas_review_sources"

#: Key under which ``setup_saas_api`` publishes the ingest service factory.
APP_INGEST_SERVICE = "saas_review_ingest"

#: Keys under which ``setup_saas_api`` publishes the two review-side
#: repositories. The handlers here reach them through the ingest service, but
#: the flow runner and the coupon delivery service need them directly, and a
#: shared instance is what keeps one connection pool per process rather than
#: one per consumer.
APP_REVIEW_REPOSITORY = "saas_reviews"
APP_GUEST_REPOSITORY = "saas_guests"

#: PBAC resource these routes are gated by, under the shared ``saas`` type.
PBAC_RESOURCE_NAME = "reviews"

logger = logging.getLogger("parrot_saas.handlers.reviews")


class _ReviewViewBase(BaseView):
    """Shared lookups for the review routes."""

    def _sources(self) -> dict:
        """Return the review-source registry published on the app."""
        return self.request.app.get(APP_REVIEW_SOURCES) or {}

    def _source(self, name: str):
        """Resolve one adapter by name.

        Returns:
            ``(source, None)``, or ``(None, response)`` carrying a 404 that
            names what is actually configured — an unknown source is a
            deployment mistake, and a bare 404 makes it hard to spot.
        """
        source = self._sources().get(name)
        if source is None:
            return None, json_error(
                404,
                "unknown_source",
                f"no review source named {name!r}",
                configured=sorted(self._sources()),
            )
        return source, None

    def _ingest(self) -> Optional[ReviewIngestService]:
        """Return the ingest service, when one is configured."""
        return self.request.app.get(APP_INGEST_SERVICE)

    def _repository(self):
        """Return the review repository the ingest service writes through."""
        service = self._ingest()
        return getattr(service, "_reviews", None) if service else None


class ReviewWebhookView(_ReviewViewBase):
    """Accept reviews pushed by a platform, authenticated by signature."""

    _logger_name: str = "parrot_saas.ReviewWebhookView"

    async def post(self) -> web.Response:
        """Verify, admit and queue a pushed review.

        Returns 202 with a ``run_id`` for a new review and 200 ``duplicate``
        for one already held. The duplicate answer is a success on purpose:
        every webhook platform retries, and a 4xx would make it retry harder.
        """
        source_name = self.request.match_info.get("source", "")
        tenant_id = self.request.match_info.get("tenant_id", "")

        source, error = self._source(source_name)
        if error is not None:
            return error

        # The raw bytes, read before anything parses them: the signature covers
        # what was sent, and a body that has been decoded and re-encoded will
        # not verify.
        body = await self.request.read()
        if len(body) > conf.SAAS_WEBHOOK_MAX_BODY:
            return json_error(
                413,
                "payload_too_large",
                f"a review payload may not exceed "
                f"{conf.SAAS_WEBHOOK_MAX_BODY} bytes",
            )

        tenant, error = await self._resolve_tenant(tenant_id)
        if error is not None:
            return error

        secret, error = await self._secret(tenant_id, source_name)
        if error is not None:
            return error

        if not source.verify_webhook(self.request.headers, body, secret):
            # No detail: which of "no signature", "wrong signature" or "wrong
            # secret" it was is exactly what an attacker would like to know.
            logger.warning(
                "rejected an unsigned or mis-signed %s webhook for tenant %s",
                source_name,
                tenant_id,
            )
            return json_error(
                401, "invalid_signature", "the request signature did not verify"
            )

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            return json_error(
                400, "invalid_json", f"request body is not valid JSON: {exc}"
            )

        return await self._admit(tenant, source, payload)

    async def _resolve_tenant(self, tenant_id: str):
        """Do by hand what the tenant middleware does elsewhere.

        This route is exempt from resolution because a platform cannot send a
        tenant header — which means the lifecycle checks have to happen here or
        not at all.
        """
        repository = self.request.app.get(APP_TENANT_REPOSITORY)
        if repository is None:  # pragma: no cover - misconfiguration
            return None, json_error(
                503, "not_configured", "the SaaS plane is not wired into this app"
            )
        tenant = await repository.get(tenant_id)
        if tenant is None:
            return None, json_error(
                404, "unknown_tenant", f"no such tenant: {tenant_id!r}"
            )
        context = tenant.to_context()
        if not context.is_active:
            return None, json_error(
                403,
                "tenant_suspended",
                f"tenant {tenant_id!r} is {context.status}",
            )
        return context, None

    async def _secret(self, tenant_id: str, source_name: str):
        """Read the tenant's signing secret for this source.

        A tenant that has not configured one has no webhook. Answering 403 —
        rather than letting an unsigned body through because there is nothing
        to compare it with — is the whole point.
        """
        factory = self.request.app.get(APP_SECRET_STORE_FACTORY)
        if factory is None:  # pragma: no cover - misconfiguration
            return None, json_error(
                503, "secret_store_unavailable", "no secret store is configured"
            )
        try:
            store = factory()
            secret = await store.get(tenant_id, secret_key_for(source_name))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            logger.error("could not read the webhook secret: %s", exc)
            return None, json_error(
                503,
                "secret_store_unavailable",
                "the webhook secret could not be read",
            )
        if not secret:
            return None, json_error(
                403,
                "webhook_not_configured",
                f"tenant {tenant_id!r} has no {secret_key_for(source_name)!r} "
                "secret; webhooks are refused until one is stored",
            )
        return secret, None

    async def _admit(self, tenant, source, payload) -> web.Response:
        """Hand a verified payload to the ingest service."""
        service = self._ingest()
        if service is None:  # pragma: no cover - misconfiguration
            return json_error(
                503, "not_configured", "review ingest is not configured"
            )
        try:
            result = await service.ingest_payload(tenant, source, payload)
        except ValueError as exc:
            return json_error(400, "invalid_review", str(exc))

        status = 202 if result.created else 200
        return web.json_response(result.to_json(), status=status)


class ReviewSimulateView(_ReviewViewBase):
    """Inject a review directly, for demos and end-to-end tests."""

    _logger_name: str = "parrot_saas.ReviewSimulateView"

    async def post(self) -> web.Response:
        """Admit a review supplied by an authenticated tenant admin.

        Restricted to administrators rather than operators: each simulated
        review starts a run, and a run spends the tenant's own LLM budget.
        """
        tenant = current_tenant(self.request)
        denied = await check_policy(
            self.request,
            "saas:review:simulate",
            PBAC_RESOURCE_NAME,
            subject=tenant.tenant_id,
        )
        if denied is not None:
            return denied

        raw = (await self.request.text()).strip()
        if not raw:
            return json_error(400, "invalid_json", "request body is required")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return json_error(
                400, "invalid_json", f"request body is not valid JSON: {exc}"
            )
        if not isinstance(payload, dict):
            return json_error(
                400, "invalid_json", "request body must be a JSON object"
            )

        source_name = str(payload.pop("source", "mock"))
        source, error = self._source(source_name)
        if error is not None:
            return error

        service = self._ingest()
        if service is None:  # pragma: no cover - misconfiguration
            return json_error(
                503, "not_configured", "review ingest is not configured"
            )
        try:
            result = await service.ingest_payload(tenant, source, payload)
        except ValueError as exc:
            return json_error(400, "invalid_review", str(exc))

        logger.info(
            "tenant %s simulated review %s", tenant.tenant_id, result.review.external_id
        )
        return web.json_response(
            result.to_json(), status=202 if result.created else 200
        )


class ReviewCollectionView(_ReviewViewBase):
    """List a tenant's reviews."""

    _logger_name: str = "parrot_saas.ReviewCollectionView"

    async def get(self) -> web.Response:
        """Return reviews for the resolved tenant, newest first."""
        tenant = current_tenant(self.request)
        denied = await check_policy(
            self.request,
            "saas:review:read",
            PBAC_RESOURCE_NAME,
            subject=tenant.tenant_id,
        )
        if denied is not None:
            return denied

        args = self.get_arguments(self.request)
        status_raw = args.get("status")
        try:
            status = ReviewStatus(status_raw) if status_raw else None
        except ValueError:
            return json_error(
                400,
                "invalid_status",
                f"unknown status {status_raw!r}; expected one of "
                f"{[s.value for s in ReviewStatus]}",
            )
        try:
            limit = min(max(int(args.get("limit", 50)), 1), 200)
            offset = max(int(args.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return json_error(
                400, "invalid_paging", "limit and offset must be integers"
            )

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(
                503, "not_configured", "review ingest is not configured"
            )
        reviews = await repository.list_reviews(
            tenant.tenant_id, status=status, limit=limit, offset=offset
        )
        return web.json_response(
            {
                "reviews": [r.model_dump(mode="json") for r in reviews],
                "count": len(reviews),
            }
        )


class ReviewItemView(_ReviewViewBase):
    """Read one review and the replies drafted for it."""

    _logger_name: str = "parrot_saas.ReviewItemView"

    async def get(self) -> web.Response:
        """Return one review with its drafting history."""
        tenant = current_tenant(self.request)
        denied = await check_policy(
            self.request,
            "saas:review:read",
            PBAC_RESOURCE_NAME,
            subject=tenant.tenant_id,
        )
        if denied is not None:
            return denied

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(
                503, "not_configured", "review ingest is not configured"
            )

        review_id = self.request.match_info.get("review_id", "")
        review = await repository.get(tenant.tenant_id, review_id)
        if review is None:
            return json_error(
                404, "unknown_review", f"no such review: {review_id!r}"
            )
        replies = await repository.list_replies(tenant.tenant_id, review_id)
        return web.json_response(
            {
                "review": review.model_dump(mode="json"),
                "replies": [r.model_dump(mode="json") for r in replies],
            }
        )


def setup_review_routes(
    app: web.Application, *, base: str = "/api/v1/saas/reviews"
) -> None:
    """Register the review ingest and read routes.

    The static paths go in before the ``{review_id}`` pattern: aiohttp resolves
    resources in registration order, so a dynamic route registered first would
    swallow them.

    Args:
        app: The aiohttp application.
        base: Base path for the collection.
    """
    _app = app.get_app() if hasattr(app, "get_app") else app
    _app.router.add_view(base, ReviewCollectionView)
    _app.router.add_view(f"{base}/simulate", ReviewSimulateView)
    _app.router.add_view(
        f"{base}/webhook/{{source}}/{{tenant_id}}", ReviewWebhookView
    )
    _app.router.add_view(f"{base}/{{review_id}}", ReviewItemView)


__all__ = (
    "APP_GUEST_REPOSITORY",
    "APP_INGEST_SERVICE",
    "APP_REVIEW_REPOSITORY",
    "APP_REVIEW_SOURCES",
    "ReviewCollectionView",
    "ReviewItemView",
    "ReviewSimulateView",
    "ReviewWebhookView",
    "setup_review_routes",
)
