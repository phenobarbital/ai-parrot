"""The runs API over HTTP, and the record the runner leaves behind.

Two concerns. The first is ordinary: a tenant can list and read its own runs.
The second is the one that matters — a run id is a UUID and nothing about it
is secret, so ``tenant_id`` in the ``WHERE`` clause is the only thing between
a caller and another tenant's runs. That is asserted directly, over the wire,
with a real id from the other tenant.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.runs import APP_RUN_REPOSITORY
from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.runs.models import RunStatus
from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
RUNS = "/api/v1/saas/runs"
HDR = {TENANT_HEADER: "bar-pepe"}
OTHER = {TENANT_HEADER: "hotel-x"}

POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"

RUN_A = "aaaaaaaa-0000-0000-0000-00000000000a"
RUN_B = "bbbbbbbb-0000-0000-0000-00000000000b"


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
        await http.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
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


async def _seed(client, tenant_id: str, run_id: str, **finish):
    """Write one finished run straight through the repository."""
    runs = client.app[APP_RUN_REPOSITORY]
    await runs.start(tenant_id, run_id)
    finish.setdefault("status", RunStatus.COMPLETED)
    return await runs.finish(tenant_id, run_id, **finish)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def test_a_run_is_listed_and_readable(client) -> None:
    """The ordinary case, over the wire."""
    await _seed(
        client,
        "bar-pepe",
        RUN_A,
        outcome="coupon_delivered",
        replied=True,
        coupon_code="RECOVER20-7KQF9M",
        usage={"triage": {"total_tokens": 120}},
        nodes=[{"node_id": "triage", "status": "completed", "duration_ms": 12}],
        duration_ms=345,
    )

    listing = await (await client.get(RUNS, headers=HDR)).json()
    assert listing["count"] == 1

    detail = await (await client.get(f"{RUNS}/{RUN_A}", headers=HDR)).json()
    assert detail["status"] == "completed"
    assert detail["outcome"] == "coupon_delivered"
    assert detail["replied"] is True
    assert detail["coupon_code"] == "RECOVER20-7KQF9M"
    assert detail["usage"]["triage"]["total_tokens"] == 120
    assert detail["nodes"][0]["node_id"] == "triage"
    assert detail["duration_ms"] == 345
    assert detail["finished_at"] is not None


async def test_runs_can_be_filtered_by_status(client) -> None:
    """An error dashboard asks for the failed ones."""
    await _seed(client, "bar-pepe", RUN_A, outcome="replied")
    await _seed(
        client,
        "bar-pepe",
        RUN_B,
        status=RunStatus.FAILED,
        failed_node="publish_reply",
        error="403 from the platform",
    )

    body = await (await client.get(f"{RUNS}?status=failed", headers=HDR)).json()

    assert body["count"] == 1
    assert body["runs"][0]["failed_node"] == "publish_reply"


async def test_an_unknown_run_is_404(client) -> None:
    """Including an id that is not even a UUID — a typo, not a 500."""
    assert (await client.get(f"{RUNS}/{RUN_B}", headers=HDR)).status == 404
    assert (await client.get(f"{RUNS}/not-a-uuid", headers=HDR)).status == 404


async def test_a_bad_limit_is_a_400_not_a_500(client) -> None:
    """Query parameters come from outside."""
    resp = await client.get(f"{RUNS}?limit=lots", headers=HDR)

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_query"


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


async def test_one_tenant_cannot_read_anothers_run(client) -> None:
    """The id is real and the caller is authenticated — only the tenant differs.

    A 404 rather than a 403 on purpose: the query is tenant-scoped, so the
    handler genuinely cannot tell "not yours" from "does not exist", and a 403
    would confirm the id is real.
    """
    await _seed(client, "hotel-x", RUN_B, outcome="replied")

    assert (await client.get(f"{RUNS}/{RUN_B}", headers=HDR)).status == 404
    assert (await client.get(f"{RUNS}/{RUN_B}", headers=OTHER)).status == 200

    mine = await (await client.get(RUNS, headers=HDR)).json()
    assert mine["count"] == 0


async def test_a_run_id_belonging_to_another_tenant_is_not_taken_over(
    client,
) -> None:
    """``start`` upserts on ``run_id``; the conflict branch keeps the guard.

    Without the tenant condition on ``ON CONFLICT DO UPDATE`` this call would
    quietly reassign the other tenant's run.
    """
    await _seed(client, "hotel-x", RUN_B, outcome="replied")
    runs = client.app[APP_RUN_REPOSITORY]

    taken = await runs.start("bar-pepe", RUN_B)

    assert taken is None
    still_theirs = await runs.get("hotel-x", RUN_B)
    assert still_theirs.outcome == "replied"


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_an_operator_may_read_runs(client_factory) -> None:
    """Answering "what happened to this review?" is the operator's job."""
    client = await client_factory("tenant_operator", with_pdp=True)
    await _seed(client, "bar-pepe", RUN_A, outcome="replied")

    assert (await client.get(f"{RUNS}/{RUN_A}", headers=HDR)).status == 200


async def test_a_stranger_may_not(client_factory) -> None:
    """No group, no runs."""
    client = await client_factory(with_pdp=True)

    assert (await client.get(RUNS, headers=HDR)).status == 403


# ---------------------------------------------------------------------------
# The whole path, once
# ---------------------------------------------------------------------------


async def test_a_simulated_review_runs_end_to_end_and_earns_a_coupon(
    client,
) -> None:
    """Ingest, flow, run row, coupon — the wiring, not the pieces.

    Each piece has its own tests; none of them would notice if
    ``setup_saas_api`` handed the runner the wrong repository, or if the
    review's own source never reached the publish node. This is deliberately
    the narrative from the plan: a one-star review from a guest who consented
    to marketing, a rule that recovers detractors, and a coupon at the end.

    No API key is involved: with no agents configured the two LLM nodes take
    their deterministic paths, which is exactly what keeps this runnable in
    CI.
    """
    from parrot_saas.reviews.models import ReviewStatus

    offers = "/api/v1/saas/coupon-offers"
    rules = "/api/v1/saas/rules"

    await client.post(
        offers,
        json={
            "code": "RECOVER20",
            "name": "20% off your next visit",
            "discount_type": "percent",
            "discount_value": 20,
            "valid_days": 30,
        },
        headers=HDR,
    )
    await client.post(
        rules,
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
        headers=HDR,
    )

    resp = await client.post(
        "/api/v1/saas/reviews/simulate",
        json={
            "external_id": "demo-1",
            "rating": 1,
            "text": "The food was cold and we waited forty minutes.",
            "author_email": "guest@example.com",
            "author_name": "A Guest",
        },
        headers=HDR,
    )
    assert resp.status == 202, await resp.text()
    body = await resp.json()

    # The guest arrived through ingest without consent, which is the correct
    # default — so grant it the way a tenant's own systems would, then run.
    guests = client.app["saas_guests"]
    guest = await guests.find("bar-pepe", email="guest@example.com")
    await guests.set_consent("bar-pepe", guest.guest_id, True)

    second = await client.post(
        "/api/v1/saas/reviews/simulate",
        json={
            "external_id": "demo-2",
            "rating": 1,
            "text": "Same again, sadly. Cold food and a long wait.",
            "author_email": "guest@example.com",
        },
        headers=HDR,
    )
    assert second.status == 202
    run_id = (await second.json())["run_id"]

    run = await (await client.get(f"{RUNS}/{run_id}", headers=HDR)).json()
    assert run["status"] == "completed", run
    assert run["replied"] is True
    assert run["outcome"] in ("coupon_issued", "coupon_delivered"), run["outcome"]
    assert run["coupon_code"].startswith("RECOVER20-")

    coupons = await (await client.get("/api/v1/saas/coupons", headers=HDR)).json()
    assert [c["code"] for c in coupons["coupons"]] == [run["coupon_code"]]

    # And the review it came from is marked answered.
    review = await (
        await client.get(
            f"/api/v1/saas/reviews/{(await second.json())['review_id']}",
            headers=HDR,
        )
    ).json()
    assert review["review"]["status"] == ReviewStatus.REPLIED.value
    assert body["status"] == "queued"
