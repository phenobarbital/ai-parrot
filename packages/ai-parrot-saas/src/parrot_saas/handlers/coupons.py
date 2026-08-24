"""HTTP surface for coupon offers and issued coupons.

Redemption is the endpoint a person uses under pressure — someone at a till
with a customer waiting — so its refusals are discriminated: ``expired``,
``already_redeemed`` and ``unknown_coupon`` lead to three different
conversations, and a bare "no" leads to none of them.

Deleting an offer is **deactivation**. Coupons already in guests' hands
reference the offer row and must stay redeemable; a real delete would either
break them or cascade away money the business already promised.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView
from pydantic import ValidationError

from ..coupons.models import CouponOfferCreate, CouponOfferUpdate, CouponStatus
from ..coupons.repository import OfferAlreadyExists, RedemptionError
from ..tenancy.middleware import current_tenant
from .authz import check_policy
from .tenants import json_error

#: Key under which ``setup_saas_api`` publishes the coupon repository.
APP_COUPON_REPOSITORY = "saas_coupons"

#: Key under which ``setup_saas_api`` publishes the issuer.
APP_COUPON_ISSUER = "saas_coupon_issuer"

#: PBAC resource these routes are gated by, under the shared ``saas`` type.
PBAC_RESOURCE_NAME = "coupons"

#: How a refusal maps onto a status code.
#:
#: ``already_redeemed`` and ``expired`` are 409, not 404: the coupon exists and
#: the caller's request conflicts with its state, which is exactly what a
#: cashier needs to be told apart from "no such code".
_REFUSAL_STATUS = {
    "unknown_coupon": 404,
    "already_redeemed": 409,
    "expired": 409,
    "void": 409,
}

logger = logging.getLogger("parrot_saas.handlers.coupons")


class _CouponViewBase(BaseView):
    """Shared plumbing for the coupon routes."""

    def _tenant(self):
        """Return the tenant resolved by the middleware."""
        return current_tenant(self.request)

    def _repository(self) -> Optional[Any]:
        """Return the coupon repository published on the app."""
        return self.request.app.get(APP_COUPON_REPOSITORY)

    async def _authorize(self, action: str) -> Optional[web.Response]:
        """Check the policy for one action."""
        return await check_policy(
            self.request,
            action,
            PBAC_RESOURCE_NAME,
            subject=self._tenant().tenant_id,
        )

    async def _body(self) -> tuple[Optional[dict], Optional[web.Response]]:
        """Parse the JSON body, distinguishing absent from malformed."""
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


class OfferCollectionView(_CouponViewBase):
    """List and create coupon offers."""

    _logger_name: str = "parrot_saas.OfferCollectionView"

    async def get(self) -> web.Response:
        """List this tenant's offers."""
        denied = await self._authorize("saas:coupon:read")
        if denied is not None:
            return denied
        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "coupons are not configured")

        args = self.get_arguments(self.request)
        active_only = str(args.get("active", "")).lower() in ("1", "true", "yes")
        offers = await repository.list_offers(
            self._tenant().tenant_id, active_only=active_only
        )
        return web.json_response(
            {
                "offers": [o.model_dump(mode="json") for o in offers],
                "count": len(offers),
            }
        )

    async def post(self) -> web.Response:
        """Create an offer."""
        denied = await self._authorize("saas:offer:write")
        if denied is not None:
            return denied
        payload, error = await self._body()
        if error is not None:
            return error
        try:
            create = CouponOfferCreate(**payload)
        except ValidationError as exc:
            return self._validation_error(exc)

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "coupons are not configured")
        tenant = self._tenant()
        try:
            offer = await repository.create_offer(tenant.tenant_id, create)
        except OfferAlreadyExists:
            # 409 emitted directly: BaseView.error() would degrade it to 400.
            return json_error(
                409,
                "offer_exists",
                f"an offer coded {create.code!r} already exists",
            )

        logger.info(
            "tenant %s created offer %s", tenant.tenant_id, offer.code
        )
        return web.json_response(offer.model_dump(mode="json"), status=201)


class OfferItemView(_CouponViewBase):
    """Amend or retire one offer."""

    _logger_name: str = "parrot_saas.OfferItemView"

    def _offer_id(self) -> str:
        """Return the offer id from the path."""
        return self.request.match_info.get("offer_id", "")

    async def get(self) -> web.Response:
        """Return one offer."""
        denied = await self._authorize("saas:coupon:read")
        if denied is not None:
            return denied
        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "coupons are not configured")

        offer = await repository.get_offer(
            self._tenant().tenant_id, self._offer_id()
        )
        if offer is None:
            return json_error(404, "unknown_offer", "no such offer")
        return web.json_response(offer.model_dump(mode="json"))

    async def patch(self) -> web.Response:
        """Apply a partial amendment."""
        denied = await self._authorize("saas:offer:write")
        if denied is not None:
            return denied
        payload, error = await self._body()
        if error is not None:
            return error
        try:
            patch = CouponOfferUpdate(**payload)
        except ValidationError as exc:
            return self._validation_error(exc)

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "coupons are not configured")

        offer = await repository.update_offer(
            self._tenant().tenant_id, self._offer_id(), patch
        )
        if offer is None:
            return json_error(404, "unknown_offer", "no such offer")
        return web.json_response(offer.model_dump(mode="json"))

    async def delete(self) -> web.Response:
        """Retire an offer.

        Deactivation, never a delete: coupons already issued point at this row
        and have to keep working. The response says so rather than pretending
        the offer is gone.
        """
        denied = await self._authorize("saas:offer:write")
        if denied is not None:
            return denied
        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "coupons are not configured")

        offer = await repository.deactivate_offer(
            self._tenant().tenant_id, self._offer_id()
        )
        if offer is None:
            return json_error(404, "unknown_offer", "no such offer")
        return web.json_response(offer.model_dump(mode="json"))


class CouponCollectionView(_CouponViewBase):
    """List issued coupons."""

    _logger_name: str = "parrot_saas.CouponCollectionView"

    async def get(self) -> web.Response:
        """List this tenant's coupons, newest first."""
        denied = await self._authorize("saas:coupon:read")
        if denied is not None:
            return denied
        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "coupons are not configured")

        args = self.get_arguments(self.request)
        status_raw = args.get("status")
        try:
            status = CouponStatus(status_raw).value if status_raw else None
        except ValueError:
            return json_error(
                400,
                "invalid_status",
                f"unknown status {status_raw!r}; expected one of "
                f"{[s.value for s in CouponStatus]}",
            )
        try:
            limit = min(max(int(args.get("limit", 50)), 1), 200)
            offset = max(int(args.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return json_error(
                400, "invalid_paging", "limit and offset must be integers"
            )

        coupons = await repository.list_coupons(
            self._tenant().tenant_id,
            status=status,
            guest_id=args.get("guest_id", ""),
            limit=limit,
            offset=offset,
        )
        return web.json_response(
            {
                "coupons": [c.model_dump(mode="json") for c in coupons],
                "count": len(coupons),
            }
        )


class CouponRedeemView(_CouponViewBase):
    """Spend a coupon at the point of sale."""

    _logger_name: str = "parrot_saas.CouponRedeemView"

    async def post(self) -> web.Response:
        """Redeem a coupon by code, exactly once."""
        denied = await self._authorize("saas:coupon:redeem")
        if denied is not None:
            return denied
        payload, error = await self._body()
        if error is not None:
            return error

        code = str(payload.get("code") or "").strip()
        if not code:
            return json_error(400, "invalid_code", "'code' is required")

        repository = self._repository()
        if repository is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "coupons are not configured")

        tenant = self._tenant()
        try:
            coupon = await repository.redeem(
                tenant.tenant_id,
                code,
                redeemed_by=str(payload.get("redeemed_by") or ""),
            )
        except RedemptionError as exc:
            # The reason is the payload here, not decoration: the person
            # holding the phone needs to know whether to argue, re-send or
            # honour it anyway.
            return json_error(
                _REFUSAL_STATUS.get(exc.reason, 409),
                exc.reason,
                str(exc),
            )

        logger.info(
            "tenant %s redeemed coupon %s", tenant.tenant_id, coupon.code
        )
        return web.json_response(coupon.model_dump(mode="json"))


def setup_coupon_routes(
    app: web.Application, *, base: str = "/api/v1/saas"
) -> None:
    """Register the coupon routes.

    ``redeem`` goes in before the coupon collection's dynamic siblings for the
    usual reason: aiohttp resolves resources in registration order.

    Args:
        app: The aiohttp application.
        base: Base path for the SaaS surface.
    """
    _app = app.get_app() if hasattr(app, "get_app") else app
    _app.router.add_view(f"{base}/coupon-offers", OfferCollectionView)
    _app.router.add_view(f"{base}/coupon-offers/{{offer_id}}", OfferItemView)
    _app.router.add_view(f"{base}/coupons/redeem", CouponRedeemView)
    _app.router.add_view(f"{base}/coupons", CouponCollectionView)


__all__ = (
    "APP_COUPON_ISSUER",
    "APP_COUPON_REPOSITORY",
    "CouponCollectionView",
    "CouponRedeemView",
    "OfferCollectionView",
    "OfferItemView",
    "setup_coupon_routes",
)
