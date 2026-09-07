"""The coupon API over HTTP, end to end against Postgres."""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.coupons.issuer import CouponIssuer
from parrot_saas.handlers.coupons import APP_COUPON_REPOSITORY
from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
OFFERS = "/api/v1/saas/coupon-offers"
COUPONS = "/api/v1/saas/coupons"
HDR = {TENANT_HEADER: "bar-pepe"}

POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"

OFFER = {
    "code": "RECOVER20",
    "name": "20% back",
    "discount_type": "percent",
    "discount_value": 20,
    "valid_days": 30,
}


class _PDP:
    """Minimal stand-in holding a real ``PolicyEvaluator``."""

    def __init__(self, evaluator) -> None:
        self._evaluator = evaluator


def _evaluator():
    """A PolicyEvaluator loaded from the repository's policy directory."""
    from navigator_auth.abac.policies.evaluator import PolicyEvaluator, PolicyLoader

    evaluator = PolicyEvaluator(cache_ttl_seconds=1)
    evaluator.load_policies(PolicyLoader.load_from_directory(POLICY_DIR))
    return evaluator


@pytest.fixture
async def client_factory(
    aiohttp_client, test_dsn: str, unique_schema: str, secret_store
):
    """Build a wired app whose requests carry a chosen set of user groups."""

    async def _build(*groups: str, with_pdp: bool = False):
        @web.middleware
        async def _fake_session(request, handler):
            request["session"] = {
                "session": {"username": "someone", "groups": list(groups)}
            }
            return await handler(request)

        app = web.Application()
        app.middlewares.append(_fake_session)
        setup_saas_api(
            app,
            dsn=test_dsn,
            schema=unique_schema,
            secret_store=secret_store,
            require_auth=False,
        )
        if with_pdp:
            app["abac"] = _PDP(_evaluator())
        http = await aiohttp_client(app)
        await http.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "Bar Pepe"})
        return http

    try:
        yield _build
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


@pytest.fixture
async def client(client_factory):
    """A wired app acting as a tenant admin, with no policy engine."""
    return await client_factory("tenant_admin")


async def _issue(client, **overrides) -> str:
    """Issue one coupon through the app's own issuer and return its code."""
    issuer = CouponIssuer(client.app[APP_COUPON_REPOSITORY])
    result = await issuer.issue("bar-pepe", offer_code="RECOVER20", **overrides)
    assert result.issued, result.reason
    return result.coupon_code


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------


async def test_create_and_list_offers(client) -> None:
    """An offer created over HTTP appears in the listing."""
    created = await client.post(OFFERS, json=OFFER, headers=HDR)

    assert created.status == 201
    body = await (await client.get(OFFERS, headers=HDR)).json()
    assert body["count"] == 1
    assert body["offers"][0]["code"] == "RECOVER20"


async def test_an_offer_code_is_normalised(client) -> None:
    """A rule naming ``RECOVER20`` and an offer stored as ``recover20`` would
    never meet, and the mismatch would look like an eligibility bug."""
    resp = await client.post(
        OFFERS, json={**OFFER, "code": " recover 20 "}, headers=HDR
    )

    assert (await resp.json())["code"] == "RECOVER20"


async def test_a_duplicate_code_is_409(client) -> None:
    """``BaseView.error()`` would degrade this to a 400."""
    await client.post(OFFERS, json=OFFER, headers=HDR)

    resp = await client.post(OFFERS, json=OFFER, headers=HDR)

    assert resp.status == 409
    assert (await resp.json())["error"] == "offer_exists"


async def test_patching_an_offer(client) -> None:
    """A partial amendment leaves the rest alone."""
    created = await (await client.post(OFFERS, json=OFFER, headers=HDR)).json()

    resp = await client.patch(
        f"{OFFERS}/{created['offer_id']}", json={"max_coupons": 50}, headers=HDR
    )

    body = await resp.json()
    assert body["max_coupons"] == 50
    assert body["code"] == "RECOVER20"
    assert body["discount_value"] == 20


async def test_the_code_cannot_be_patched(client) -> None:
    """Issued coupons and eligibility rules both point at it by code."""
    created = await (await client.post(OFFERS, json=OFFER, headers=HDR)).json()

    resp = await client.patch(
        f"{OFFERS}/{created['offer_id']}", json={"code": "OTHER"}, headers=HDR
    )

    assert resp.status == 400
    assert any("code" in d["field"] for d in (await resp.json())["details"])


async def test_deleting_an_offer_only_retires_it(client) -> None:
    """Coupons in guests' hands reference the row and must keep working."""
    created = await (await client.post(OFFERS, json=OFFER, headers=HDR)).json()
    code = await _issue(client)

    resp = await client.delete(f"{OFFERS}/{created['offer_id']}", headers=HDR)

    assert resp.status == 200
    assert (await resp.json())["active"] is False
    redeemed = await client.post(
        f"{COUPONS}/redeem", json={"code": code}, headers=HDR
    )
    assert redeemed.status == 200


async def test_an_invalid_offer_is_refused(client) -> None:
    """Bounds are checked before anything is stored."""
    resp = await client.post(
        OFFERS, json={**OFFER, "valid_days": 0}, headers=HDR
    )

    assert resp.status == 400
    assert (await resp.json())["error"] == "validation_error"


async def test_an_unknown_offer_is_404(client) -> None:
    """Including a malformed id, which must not surface a driver error."""
    assert (await client.get(f"{OFFERS}/nope", headers=HDR)).status == 404
    assert (await client.delete(f"{OFFERS}/nope", headers=HDR)).status == 404


# ---------------------------------------------------------------------------
# Coupons and redemption
# ---------------------------------------------------------------------------


async def test_listing_coupons(client) -> None:
    """Issued coupons show up with their offer and expiry."""
    await client.post(OFFERS, json=OFFER, headers=HDR)
    code = await _issue(client)

    body = await (await client.get(COUPONS, headers=HDR)).json()

    assert body["count"] == 1
    assert body["coupons"][0]["code"] == code
    assert body["coupons"][0]["expires_at"]


async def test_filtering_coupons_by_status(client) -> None:
    """A cashier's view is "what is still spendable"."""
    await client.post(OFFERS, json=OFFER, headers=HDR)
    code = await _issue(client)
    await client.post(f"{COUPONS}/redeem", json={"code": code}, headers=HDR)

    redeemed = await (
        await client.get(f"{COUPONS}?status=redeemed", headers=HDR)
    ).json()
    issued = await (
        await client.get(f"{COUPONS}?status=issued", headers=HDR)
    ).json()

    assert redeemed["count"] == 1
    assert issued["count"] == 0


async def test_an_invalid_status_filter_is_400(client) -> None:
    """An unknown value is refused rather than ignored."""
    resp = await client.get(f"{COUPONS}?status=banana", headers=HDR)

    assert resp.status == 400


async def test_redeeming_over_http(client) -> None:
    """The endpoint a till calls."""
    await client.post(OFFERS, json=OFFER, headers=HDR)
    code = await _issue(client)

    resp = await client.post(
        f"{COUPONS}/redeem", json={"code": code, "redeemed_by": "till-3"},
        headers=HDR,
    )

    body = await resp.json()
    assert resp.status == 200
    assert body["status"] == "redeemed"
    assert body["redeemed_by"] == "till-3"


async def test_a_second_redemption_is_409_with_its_reason(client) -> None:
    """409 rather than 404: the coupon exists, the request conflicts."""
    await client.post(OFFERS, json=OFFER, headers=HDR)
    code = await _issue(client)
    await client.post(f"{COUPONS}/redeem", json={"code": code}, headers=HDR)

    resp = await client.post(
        f"{COUPONS}/redeem", json={"code": code}, headers=HDR
    )

    assert resp.status == 409
    assert (await resp.json())["error"] == "already_redeemed"


async def test_an_unknown_code_is_404(client) -> None:
    """A typo at the counter is a different conversation from a used coupon."""
    resp = await client.post(
        f"{COUPONS}/redeem", json={"code": "NOPE-123456"}, headers=HDR
    )

    assert resp.status == 404
    assert (await resp.json())["error"] == "unknown_coupon"


async def test_redeeming_without_a_code_is_400(client) -> None:
    """The one required field."""
    resp = await client.post(f"{COUPONS}/redeem", json={}, headers=HDR)

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_code"


async def test_redeem_is_not_swallowed_by_the_collection_route(client) -> None:
    """Registration order matters; this asserts it."""
    resp = await client.post(f"{COUPONS}/redeem", json={}, headers=HDR)

    assert resp.status == 400  # reached the view, not a 404 or 405


# ---------------------------------------------------------------------------
# Isolation and authorization
# ---------------------------------------------------------------------------


async def test_offers_and_coupons_are_tenant_scoped(client) -> None:
    """Two tenants, no crossover."""
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
    await client.post(OFFERS, json=OFFER, headers=HDR)
    await _issue(client)

    theirs_offers = await (
        await client.get(OFFERS, headers={TENANT_HEADER: "hotel-x"})
    ).json()
    theirs_coupons = await (
        await client.get(COUPONS, headers={TENANT_HEADER: "hotel-x"})
    ).json()

    assert theirs_offers["count"] == 0
    assert theirs_coupons["count"] == 0


async def test_an_operator_may_redeem_but_not_configure(client_factory) -> None:
    """Exactly the counter staff's job: spend coupons, not decide who gets them."""
    admin = await client_factory("tenant_admin", with_pdp=True)
    await admin.post(OFFERS, json=OFFER, headers=HDR)
    code = await _issue(admin)

    operator = await client_factory("tenant_operator", with_pdp=True)
    listing = await operator.get(COUPONS, headers=HDR)
    redeem = await operator.post(
        f"{COUPONS}/redeem", json={"code": code}, headers=HDR
    )
    write = await operator.post(OFFERS, json={**OFFER, "code": "X"}, headers=HDR)

    assert listing.status == 200
    assert redeem.status == 200
    assert write.status == 403


async def test_a_stranger_may_not_redeem(client_factory) -> None:
    """Deny by default: no policy matched means no access."""
    nobody = await client_factory(with_pdp=True)

    resp = await nobody.post(
        f"{COUPONS}/redeem", json={"code": "ANY-123456"}, headers=HDR
    )

    assert resp.status == 403
