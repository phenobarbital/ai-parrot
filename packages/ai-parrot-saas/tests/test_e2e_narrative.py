"""The whole circuit, over HTTP, exactly as a customer would drive it.

Every other module in this suite tests a piece. This one tests that the pieces
fit: a tenant is onboarded, configures itself, receives a one-star review, and
a coupon comes out the far end and is redeemed at a till. Nothing is called
directly — every step is an HTTP request against the app that ``setup_saas_api``
wires, which is what makes this the test that would notice a route registered
in the wrong order, a repository handed to the wrong constructor, or a policy
action nobody granted.

**No API key is involved.** With no provider credentials stored, the two LLM
nodes take their deterministic paths — which is exactly the property that keeps
the whole flow runnable in CI, and is worth having a test depend on.

The second half runs the same circuit for a second tenant and then asserts the
thing this entire feature exists for: neither can see anything of the other's.
"""
from __future__ import annotations

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
SECRETS = "/api/v1/saas/secrets"
OFFERS = "/api/v1/saas/coupon-offers"
RULES = "/api/v1/saas/rules"
SIMULATE = "/api/v1/saas/reviews/simulate"
RUNS = "/api/v1/saas/runs"
COUPONS = "/api/v1/saas/coupons"
REDEEM = "/api/v1/saas/coupons/redeem"

PEPE = {TENANT_HEADER: "bar-pepe"}
HOTEL = {TENANT_HEADER: "hotel-x"}


@pytest.fixture
async def api(aiohttp_client, test_dsn: str, unique_schema: str, secret_store):
    """The wired application, with an authenticated administrator session."""

    @web.middleware
    async def _admin_session(request, handler):
        request["session"] = {
            "session": {
                "username": "admin",
                "groups": ["platform_admin", "tenant_admin"],
            }
        }
        return await handler(request)

    app = web.Application()
    app.middlewares.append(_admin_session)
    from parrot_saas.handlers.setup import setup_saas_api

    setup_saas_api(
        app,
        dsn=test_dsn,
        schema=unique_schema,
        secret_store=secret_store,
        require_auth=False,
    )
    client = await aiohttp_client(app)
    try:
        yield client
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


async def _onboard(api, tenant_id: str, name: str) -> dict:
    """Take one tenant from nothing to ready-to-serve, over HTTP.

    The order is the one an operator follows and the one the README documents:
    create, store a credential, define what may be given away, define who
    qualifies.
    """
    headers = {TENANT_HEADER: tenant_id}

    created = await api.post(CONTROL, json={"tenant_id": tenant_id, "name": name})
    assert created.status == 201, await created.text()

    # A webhook secret rather than a provider key: a stored
    # ``anthropic:api_key`` would have the tenant's next runtime build a real
    # client, and the drafting node would make a real outbound call. The BYOK
    # path has its own tests; this one needs the *circuit*, offline.
    stored = await api.put(
        f"{SECRETS}/webhook:mock:hmac",
        json={"value": f"whsec-{tenant_id}"},
        headers=headers,
    )
    assert stored.status == 201
    assert (await stored.json())["fingerprint"]
    # The value never comes back out — asserted on the raw body, not on fields.
    assert f"whsec-{tenant_id}" not in await (
        await api.get(SECRETS, headers=headers)
    ).text()

    offer = await api.post(
        OFFERS,
        json={
            "code": "RECOVER20",
            "name": "20% off your next visit",
            "discount_type": "percent",
            "discount_value": 20,
            "valid_days": 30,
            "max_per_guest": 1,
        },
        headers=headers,
    )
    assert offer.status == 201, await offer.text()

    rule = await api.post(
        RULES,
        json={
            "name": "recover_detractor",
            "priority": 100,
            "conditions": {
                "ctx.rating": {"lte": 2},
                "ctx.reply_published": True,
                "ctx.consent_marketing": True,
            },
            "result": {"offer_code": "RECOVER20", "reason": "detractor_recovery"},
        },
        headers=headers,
    )
    assert rule.status == 201, await rule.text()
    return headers


async def _consent(api, tenant_id: str, email: str) -> None:
    """Record the marketing consent a guest gives the venue directly.

    Ingest deliberately creates guests *without* consent — a review platform
    never conveys it — so a tenant's own systems are what set it. Done through
    the repository because there is no HTTP surface for guest consent, which is
    itself worth knowing.
    """
    guests = api.app["saas_guests"]
    guest = await guests.find(tenant_id, email=email)
    await guests.set_consent(tenant_id, guest.guest_id, True)


async def _submit(api, headers: dict, external_id: str, email: str) -> dict:
    """Simulate one detractor review and return the ingest response."""
    resp = await api.post(
        SIMULATE,
        json={
            "external_id": external_id,
            "rating": 1,
            "text": "The food arrived cold and we waited forty minutes.",
            "author_email": email,
            "author_name": "A Guest",
        },
        headers=headers,
    )
    assert resp.status == 202, await resp.text()
    return await resp.json()


# ---------------------------------------------------------------------------
# The narrative
# ---------------------------------------------------------------------------


async def test_a_tenant_goes_from_signup_to_a_redeemed_coupon(api) -> None:
    """Onboard, configure, receive a bad review, answer it, give a coupon, redeem it."""
    headers = await _onboard(api, "bar-pepe", "Bar Pepe")

    # The guest's first review creates them with no consent on file, which is
    # the correct default and means no coupon yet.
    first = await _submit(api, headers, "demo-1", "guest@example.com")
    run = await (await api.get(f"{RUNS}/{first['run_id']}", headers=headers)).json()
    assert run["status"] == "completed"
    assert run["replied"] is True
    assert run["coupon_code"] == "", "a guest with no consent must not be couponed"
    assert run["outcome"] == "replied_no_contact"

    # They opt in, and their next review earns the offer.
    await _consent(api, "bar-pepe", "guest@example.com")
    second = await _submit(api, headers, "demo-2", "guest@example.com")

    run = await (await api.get(f"{RUNS}/{second['run_id']}", headers=headers)).json()
    assert run["status"] == "completed", run
    assert run["replied"] is True
    assert run["outcome"] in ("coupon_issued", "coupon_delivered"), run["outcome"]
    code = run["coupon_code"]
    assert code.startswith("RECOVER20-")

    listed = await (await api.get(COUPONS, headers=headers)).json()
    assert [c["code"] for c in listed["coupons"]] == [code]

    redeemed = await api.post(REDEEM, json={"code": code}, headers=headers)
    assert redeemed.status == 200
    assert (await redeemed.json())["status"] == "redeemed"

    # The till scans it twice — the second time is a discriminated refusal,
    # not a bare "no", because someone is standing there waiting.
    again = await api.post(REDEEM, json={"code": code}, headers=headers)
    assert again.status == 409
    assert (await again.json())["error"] == "already_redeemed"


async def test_a_replayed_review_produces_no_second_coupon(api) -> None:
    """The de-duplication guarantee, end to end rather than at the repository.

    A platform that redelivers must not cost the tenant a second reply and a
    second coupon — which is the whole reason ingest is idempotent on
    ``(tenant_id, source, external_id)``.
    """
    headers = await _onboard(api, "bar-pepe", "Bar Pepe")
    await _submit(api, headers, "demo-1", "guest@example.com")
    await _consent(api, "bar-pepe", "guest@example.com")
    await _submit(api, headers, "demo-2", "guest@example.com")

    replay = await api.post(
        SIMULATE,
        json={"external_id": "demo-2", "rating": 1, "text": "Same again."},
        headers=headers,
    )

    assert replay.status == 200
    assert (await replay.json())["status"] == "duplicate"
    coupons = await (await api.get(COUPONS, headers=headers)).json()
    assert coupons["count"] == 1


async def test_the_per_guest_cap_is_enforced_across_reviews(api) -> None:
    """``max_per_guest`` is 1, and a guest who complains twice gets one coupon."""
    headers = await _onboard(api, "bar-pepe", "Bar Pepe")
    await _submit(api, headers, "demo-1", "guest@example.com")
    await _consent(api, "bar-pepe", "guest@example.com")

    await _submit(api, headers, "demo-2", "guest@example.com")
    third = await _submit(api, headers, "demo-3", "guest@example.com")

    run = await (await api.get(f"{RUNS}/{third['run_id']}", headers=headers)).json()
    assert run["replied"] is True, "the second complaint is still answered"
    assert run["coupon_code"] == ""
    coupons = await (await api.get(COUPONS, headers=headers)).json()
    assert coupons["count"] == 1


# ---------------------------------------------------------------------------
# The same circuit, twice, with nothing shared
# ---------------------------------------------------------------------------


async def test_two_tenants_run_the_same_circuit_and_see_none_of_it(api) -> None:
    """The point of the whole feature, asserted on the wire.

    Both tenants use the same offer code and the same guest e-mail on purpose:
    if anything were keyed on the value rather than on ``(tenant_id, value)``,
    this is where it would surface.
    """
    codes: dict[str, str] = {}
    for tenant_id, name, headers in (
        ("bar-pepe", "Bar Pepe", PEPE),
        ("hotel-x", "Hotel X", HOTEL),
    ):
        await _onboard(api, tenant_id, name)
        await _submit(api, headers, "demo-1", "guest@example.com")
        await _consent(api, tenant_id, "guest@example.com")
        submitted = await _submit(api, headers, "demo-2", "guest@example.com")
        run = await (
            await api.get(f"{RUNS}/{submitted['run_id']}", headers=headers)
        ).json()
        assert run["coupon_code"], f"{tenant_id} earned no coupon: {run}"
        codes[tenant_id] = run["coupon_code"]

    assert codes["bar-pepe"] != codes["hotel-x"]

    # Each sees one of everything: its own.
    for headers, mine, theirs in (
        (PEPE, "bar-pepe", "hotel-x"),
        (HOTEL, "hotel-x", "bar-pepe"),
    ):
        for path, key in (
            (COUPONS, "coupons"),
            (RUNS, "runs"),
            ("/api/v1/saas/reviews", "reviews"),
            (OFFERS, "offers"),
            (RULES, "rules"),
            (SECRETS, "secrets"),
        ):
            body = await (await api.get(path, headers=headers)).json()
            assert theirs not in str(body), f"{path} leaked {theirs} to {mine}"
        assert (
            await (await api.get(COUPONS, headers=headers)).json()
        )["count"] == 1

    # And a coupon cannot be spent by the tenant that did not issue it. This is
    # the one that costs real money if it is wrong.
    stolen = await api.post(REDEEM, json={"code": codes["hotel-x"]}, headers=PEPE)
    assert stolen.status == 404
    assert (await stolen.json())["error"] == "unknown_coupon"

    # Still spendable by its owner, so the refusal above was about the tenant.
    assert (
        await api.post(REDEEM, json={"code": codes["hotel-x"]}, headers=HOTEL)
    ).status == 200


async def test_an_unknown_tenant_reaches_nothing(api) -> None:
    """The middleware fails closed, which is what makes the rest of this safe."""
    await _onboard(api, "bar-pepe", "Bar Pepe")

    assert (
        await api.get(COUPONS, headers={TENANT_HEADER: "nobody-here"})
    ).status == 404
    # And with no tenant at all.
    assert (await api.get(COUPONS)).status == 400
