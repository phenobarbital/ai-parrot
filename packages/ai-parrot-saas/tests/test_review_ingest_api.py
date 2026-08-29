"""Review ingest over HTTP, end to end against Postgres.

Wired through ``setup_saas_api`` so the route registration, the exempt prefix
and the app keys are exercised alongside the handlers.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.reviews import APP_INGEST_SERVICE
from parrot_saas.handlers.runs import APP_RUN_REPOSITORY
from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.reviews.models import Review
from parrot_saas.reviews.webhook import SIGNATURE_HEADER, secret_key_for
from parrot_saas.tenancy.context import TenantContext
from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
REVIEWS = "/api/v1/saas/reviews"
HOOK = f"{REVIEWS}/webhook/webhook"
SECRET = "whsec_bar_pepe"
HDR = {TENANT_HEADER: "bar-pepe"}


def body(**overrides) -> bytes:
    """Serialise a review payload exactly as it will be signed."""
    payload = {"external_id": "g-1", "rating": 1, "text": "Cold food"}
    payload.update(overrides)
    return json.dumps(payload).encode()


def signed(raw: bytes, secret: str = SECRET) -> dict:
    """Headers carrying a valid signature for ``raw``."""
    return {
        SIGNATURE_HEADER: hmac.new(
            secret.encode(), raw, hashlib.sha256
        ).hexdigest()
    }


class _Launcher:
    """Records what the ingest service asked it to run."""

    def __init__(self) -> None:
        self.calls: list = []

    async def __call__(self, tenant, review, run_id):
        self.calls.append((tenant.tenant_id, review.review_id, run_id))
        return {"status": "ran", "run_id": run_id}


@pytest.fixture
def launcher() -> _Launcher:
    """A stand-in for the runner, which arrives with its own feature."""
    return _Launcher()


@pytest.fixture
async def client(
    aiohttp_client, test_dsn: str, unique_schema: str, secret_store, launcher
):
    """A wired app with one active tenant that has a webhook secret."""

    @web.middleware
    async def _admin_session(request, handler):
        """Stand in for the auth layer, which is not wired in tests."""
        request["session"] = {
            "session": {"username": "admin", "groups": ["tenant_admin"]}
        }
        return await handler(request)

    app = web.Application()
    app.middlewares.append(_admin_session)
    setup_saas_api(
        app,
        dsn=test_dsn,
        schema=unique_schema,
        secret_store=secret_store,
        run_launcher=launcher,
        require_auth=False,
    )
    http = await aiohttp_client(app)
    await http.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "Bar Pepe"})
    await secret_store.put("bar-pepe", secret_key_for("webhook"), SECRET)
    try:
        yield http
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


# ---------------------------------------------------------------------------
# The signed webhook
# ---------------------------------------------------------------------------


async def test_a_signed_delivery_is_accepted(client, launcher) -> None:
    """The happy path: verified, stored, queued."""
    raw = body()

    resp = await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))

    assert resp.status == 202
    payload = await resp.json()
    assert payload["status"] == "queued"
    assert payload["review_id"]
    assert payload["run_id"]
    assert launcher.calls[0][0] == "bar-pepe"
    assert launcher.calls[0][2] == payload["run_id"]


async def test_a_replay_is_a_duplicate_not_a_second_run(client, launcher) -> None:
    """The guarantee the whole de-duplication design exists for.

    Every webhook platform retries. A retry must not produce a second run, a
    second public reply and a second coupon — and it must not look like an
    error, or the platform will retry harder.
    """
    raw = body()

    first = await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))
    second = await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))

    assert first.status == 202
    assert second.status == 200
    assert (await second.json())["status"] == "duplicate"
    assert "run_id" not in await second.json()
    assert len(launcher.calls) == 1
    listing = await (await client.get(REVIEWS, headers=HDR)).json()
    assert listing["count"] == 1


async def test_an_unsigned_delivery_stores_nothing(client, launcher) -> None:
    """Rejected before the payload is even parsed."""
    raw = body()

    resp = await client.post(f"{HOOK}/bar-pepe", data=raw)

    assert resp.status == 401
    assert (await resp.json())["error"] == "invalid_signature"
    assert launcher.calls == []
    assert (await (await client.get(REVIEWS, headers=HDR)).json())["count"] == 0


async def test_a_tampered_body_is_rejected(client) -> None:
    """The signature covers the body, so an edit in flight has to show."""
    raw = body()
    headers = signed(raw)

    resp = await client.post(
        f"{HOOK}/bar-pepe", data=body(rating=5), headers=headers
    )

    assert resp.status == 401


async def test_a_body_signed_for_another_tenant_is_rejected(
    client, secret_store
) -> None:
    """The path names a tenant; the signature is what proves it.

    Without this the URL alone would be enough to post reviews as anyone.
    """
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
    await secret_store.put("hotel-x", secret_key_for("webhook"), "whsec_hotel_x")
    raw = body()

    resp = await client.post(
        f"{HOOK}/bar-pepe", data=raw, headers=signed(raw, "whsec_hotel_x")
    )

    assert resp.status == 401


async def test_a_tenant_without_a_secret_has_no_webhook(client) -> None:
    """Refused, rather than passed through for want of anything to compare."""
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
    raw = body()

    resp = await client.post(f"{HOOK}/hotel-x", data=raw, headers=signed(raw))

    assert resp.status == 403
    assert (await resp.json())["error"] == "webhook_not_configured"


async def test_an_unknown_tenant_is_404(client) -> None:
    """The lifecycle checks the middleware cannot make, made by hand."""
    raw = body()

    resp = await client.post(f"{HOOK}/nobody-here", data=raw, headers=signed(raw))

    assert resp.status == 404
    assert (await resp.json())["error"] == "unknown_tenant"


async def test_a_suspended_tenant_is_403(client) -> None:
    """Retiring a tenant must actually stop its ingest."""
    await client.delete(f"{CONTROL}/bar-pepe")
    raw = body()

    resp = await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))

    assert resp.status == 403
    assert (await resp.json())["error"] == "tenant_suspended"


async def test_an_unknown_source_names_what_is_configured(client) -> None:
    """A deployment mistake should be diagnosable from the response."""
    raw = body()

    resp = await client.post(
        f"{REVIEWS}/webhook/nosuch/bar-pepe", data=raw, headers=signed(raw)
    )

    assert resp.status == 404
    assert "webhook" in (await resp.json())["configured"]


async def test_an_oversized_body_is_refused(client, monkeypatch) -> None:
    """Bounded before the HMAC runs, not after."""
    from parrot_saas import conf

    monkeypatch.setattr(conf, "SAAS_WEBHOOK_MAX_BODY", 32)
    raw = body(text="x" * 200)

    resp = await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))

    assert resp.status == 413


async def test_a_signed_but_broken_body_is_400(client) -> None:
    """Authentic, but not JSON: that is the sender's bug, not an intrusion."""
    raw = b"{not json"

    resp = await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_json"


async def test_the_payload_cannot_choose_the_tenant(client) -> None:
    """``tenant_id`` in the body is inert; the verified path decides."""
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
    raw = body(tenant_id="hotel-x")

    await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))

    theirs = await (
        await client.get(REVIEWS, headers={TENANT_HEADER: "hotel-x"})
    ).json()
    assert theirs["count"] == 0


async def test_the_webhook_needs_no_tenant_header(client) -> None:
    """It is exempt from tenant resolution — that is why the path carries it."""
    raw = body()

    resp = await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))

    assert resp.status == 202


# ---------------------------------------------------------------------------
# Simulate
# ---------------------------------------------------------------------------


async def test_simulate_admits_a_review(client, launcher) -> None:
    """The demo entry point, and the one end-to-end tests drive."""
    resp = await client.post(
        f"{REVIEWS}/simulate",
        json={"external_id": "sim-1", "rating": 2, "text": "Slow service"},
        headers=HDR,
    )

    assert resp.status == 202
    assert (await resp.json())["status"] == "queued"
    assert len(launcher.calls) == 1


async def test_simulate_needs_a_tenant(client) -> None:
    """It goes through the middleware, unlike the webhook."""
    resp = await client.post(f"{REVIEWS}/simulate", json={"external_id": "sim-1"})

    assert resp.status == 400
    assert (await resp.json())["error"] == "tenant_required"


async def test_simulate_requires_an_external_id(client) -> None:
    """Without one there is no de-duplication key."""
    resp = await client.post(
        f"{REVIEWS}/simulate", json={"rating": 5}, headers=HDR
    )

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_review"


async def test_simulate_can_name_its_source(client) -> None:
    """The mock is the default, but the choice is the caller's."""
    resp = await client.post(
        f"{REVIEWS}/simulate",
        json={"source": "webhook", "external_id": "sim-2", "rating": 1},
        headers=HDR,
    )

    assert resp.status == 202
    assert (await resp.json())["source"] == "webhook"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def test_reading_is_scoped_to_the_asking_tenant(client, secret_store) -> None:
    """Two tenants, two ingests, no crossover."""
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
    await secret_store.put("hotel-x", secret_key_for("webhook"), "whsec_hotel_x")
    mine, theirs = body(external_id="mine"), body(external_id="theirs")
    await client.post(f"{HOOK}/bar-pepe", data=mine, headers=signed(mine))
    await client.post(
        f"{HOOK}/hotel-x", data=theirs, headers=signed(theirs, "whsec_hotel_x")
    )

    listing = await (await client.get(REVIEWS, headers=HDR)).json()

    assert [r["external_id"] for r in listing["reviews"]] == ["mine"]


async def test_reading_one_review_includes_its_drafts(client) -> None:
    """The drafting history is what explains the published text."""
    raw = body()
    created = await (
        await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))
    ).json()
    service = client.app[APP_INGEST_SERVICE]
    await service._reviews.record_reply(
        "bar-pepe", created["review_id"], text="We are sorry.", attempt=1
    )

    resp = await client.get(f"{REVIEWS}/{created['review_id']}", headers=HDR)

    body_json = await resp.json()
    assert body_json["review"]["external_id"] == "g-1"
    assert [r["text"] for r in body_json["replies"]] == ["We are sorry."]


async def test_an_unknown_review_is_404(client) -> None:
    """Including a malformed id, which must not surface a driver error."""
    resp = await client.get(f"{REVIEWS}/not-a-uuid", headers=HDR)

    assert resp.status == 404
    assert (await resp.json())["error"] == "unknown_review"


async def test_an_invalid_status_filter_is_400(client) -> None:
    """An unknown lifecycle value is refused rather than ignored."""
    resp = await client.get(f"{REVIEWS}?status=banana", headers=HDR)

    assert resp.status == 400


# ---------------------------------------------------------------------------
# Guest resolution and the launcher seam
# ---------------------------------------------------------------------------


async def test_contact_details_resolve_a_guest(client) -> None:
    """Sources that expose an address let the coupon path start earlier."""
    raw = body(email="marta@example.com", author="Marta R.")

    created = await (
        await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))
    ).json()

    resp = await client.get(f"{REVIEWS}/{created['review_id']}", headers=HDR)
    assert (await resp.json())["review"]["guest_id"]


async def test_an_anonymous_review_resolves_no_guest(client) -> None:
    """Public platforms rarely expose contact details; that is normal."""
    raw = body()

    created = await (
        await client.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))
    ).json()

    resp = await client.get(f"{REVIEWS}/{created['review_id']}", headers=HDR)
    assert (await resp.json())["review"]["guest_id"] == ""


async def test_the_default_wiring_actually_runs_the_flow(
    aiohttp_client, test_dsn, unique_schema, secret_store
) -> None:
    """``setup_saas_api`` wires a real runner, not the warning stub.

    This asserted the opposite until the runner existed: an admitted review
    and a log line saying nothing ran. What matters now is that the seam has
    a *working* default, because a deployment that has to remember to pass one
    is a deployment where reviews pile up unanswered.

    The run is expected to **fail** here, and that is the correct outcome
    rather than a weak assertion: the review arrived through the generic
    webhook adapter, which is inbound-only and refuses to publish replies. A
    tenant answering real reviews configures the platform's own adapter. What
    is being proved is that a run happened at all and was recorded.
    """
    app = web.Application()
    setup_saas_api(
        app,
        dsn=test_dsn,
        schema=unique_schema,
        secret_store=secret_store,
        require_auth=False,
    )
    http = await aiohttp_client(app)
    await http.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "Bar Pepe"})
    await secret_store.put("bar-pepe", secret_key_for("webhook"), SECRET)
    raw = body()

    try:
        resp = await http.post(f"{HOOK}/bar-pepe", data=raw, headers=signed(raw))
        assert resp.status == 202
        run_id = (await resp.json())["run_id"]

        runs = app[APP_RUN_REPOSITORY]
        record = await runs.get("bar-pepe", run_id)
        assert record is not None, "the ingest path started no run"
        assert record.failed_node == "publish_reply"
        assert "cannot publish replies" in record.error
        # And the run id the caller was handed is the one that was recorded.
        assert record.run_id == run_id
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


async def test_a_service_without_a_launcher_says_so(caplog) -> None:
    """The seam's own default is still loud, for anyone wiring by hand.

    ``setup_saas_api`` no longer leaves it in place, but a caller constructing
    the service directly gets it, and a silent no-op there would look like
    success while every review went unanswered.
    """
    from parrot_saas.reviews.ingest import null_run_launcher

    caplog.set_level(logging.WARNING)
    tenant = TenantContext(tenant_id="bar-pepe", name="Bar Pepe")

    result = await null_run_launcher(
        tenant, Review(review_id="r-1", tenant_id="bar-pepe"), "run-1"
    )

    assert result["status"] == "not_started"
    assert any(
        "no run launcher is configured" in r.getMessage() for r in caplog.records
    )
