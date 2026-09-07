"""Authorization on the review routes, against the real policy files.

Loaded through navigator-auth's own loader and evaluator, so these fail if the
shipped policy stops covering the actions the handlers ask about.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.reviews.webhook import SIGNATURE_HEADER, secret_key_for
from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
REVIEWS = "/api/v1/saas/reviews"
SECRET = "whsec_bar_pepe"
HDR = {TENANT_HEADER: "bar-pepe"}

#: Repository root, four levels up from this file.
POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"


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
def policies_exist() -> None:
    """Skip when the policy directory is not where it is expected."""
    if not POLICY_DIR.is_dir():
        pytest.skip(f"policy directory not found at {POLICY_DIR}")


@pytest.fixture
async def client_factory(
    aiohttp_client, test_dsn: str, unique_schema: str, secret_store
):
    """Build a wired app whose requests carry a chosen set of user groups."""

    async def _build(*groups: str, with_pdp: bool = True):
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
        await secret_store.put("bar-pepe", secret_key_for("webhook"), SECRET)
        return http

    try:
        yield _build
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


# ---------------------------------------------------------------------------
# Simulate is an administrator's call
# ---------------------------------------------------------------------------


async def test_an_admin_may_simulate(client_factory, policies_exist) -> None:
    """The shipped policy grants simulation to tenant admins."""
    client = await client_factory("tenant_admin")

    resp = await client.post(
        f"{REVIEWS}/simulate", json={"external_id": "sim-1"}, headers=HDR
    )

    assert resp.status == 202


@pytest.mark.parametrize("groups", [("tenant_operator",), ()])
async def test_an_operator_may_not_simulate(
    client_factory, policies_exist, groups
) -> None:
    """Each simulated review starts a run, and a run spends the tenant's
    own LLM budget — so it is not a day-to-day operator action."""
    client = await client_factory(*groups)

    resp = await client.post(
        f"{REVIEWS}/simulate", json={"external_id": "sim-1"}, headers=HDR
    )

    assert resp.status == 403
    assert (await resp.json())["error"] == "forbidden"


# ---------------------------------------------------------------------------
# Reading is a day-to-day action
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group", ["tenant_admin", "tenant_operator"])
async def test_reading_is_open_to_operators(
    client_factory, policies_exist, group
) -> None:
    """An operator has to be able to see the reviews they are handling."""
    client = await client_factory(group)

    listing = await client.get(REVIEWS, headers=HDR)
    item = await client.get(f"{REVIEWS}/00000000-0000-0000-0000-000000000000", headers=HDR)

    assert listing.status == 200
    assert item.status == 404  # authorized, simply not there


async def test_reading_is_refused_without_a_group(
    client_factory, policies_exist
) -> None:
    """Deny by default: no policy matched means no access."""
    client = await client_factory()

    assert (await client.get(REVIEWS, headers=HDR)).status == 403


# ---------------------------------------------------------------------------
# The webhook is authenticated by signature, not by policy
# ---------------------------------------------------------------------------


async def test_the_webhook_ignores_the_policy_engine(
    client_factory, policies_exist
) -> None:
    """A platform has no session and belongs to no group.

    If the webhook were gated by PBAC as well, every real delivery would be a
    403 — which is why its authentication is the signature and nothing else.
    """
    client = await client_factory()  # no groups at all
    raw = json.dumps({"external_id": "g-1", "rating": 1}).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()

    resp = await client.post(
        f"{REVIEWS}/webhook/webhook/bar-pepe",
        data=raw,
        headers={SIGNATURE_HEADER: signature},
    )

    assert resp.status == 202
