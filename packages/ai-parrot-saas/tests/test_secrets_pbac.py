"""Authorization on the secrets surface, against the real policy files.

Loads ``policies/`` through navigator-auth's own loader and evaluator, so these
tests fail if the shipped policy stops covering the actions the handlers ask
about — which is the failure mode a hand-written fake would hide.

``ResourceType`` is a closed enum with no member for secrets. The policies use
a custom string type instead (``saas:secrets``), which
``ResourcePolicy.covers_resource`` supports explicitly. That is the mechanism
under test here as much as the policy content.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
SECRETS = "/api/v1/saas/secrets"
ANTHROPIC = "anthropic:api_key"
HDR = {TENANT_HEADER: "bar-pepe"}

#: Repository root, four levels up from this file.
POLICY_DIR = Path(__file__).resolve().parents[3] / "policies"


class _PDP:
    """Minimal stand-in for navigator-auth's PDP.

    The handlers only ever read ``_evaluator`` off ``app['abac']``, so this
    carries a *real* ``PolicyEvaluator`` loaded from the real policy files —
    the policy logic is not stubbed, only the object that holds it.
    """

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


def _session(*groups: str) -> dict:
    """Build the session shape navigator-auth publishes on the request."""
    return {"session": {"username": "someone", "groups": list(groups)}}


@pytest.fixture
async def client_factory(
    aiohttp_client, test_dsn: str, unique_schema: str, secret_store
):
    """Build a wired app whose requests carry a chosen set of user groups."""
    created: list = []

    async def _build(*groups: str, with_pdp: bool = True, evaluator=None):
        @web.middleware
        async def _fake_session(request, handler):
            """Stand in for the auth layer, which is not wired in tests."""
            request["session"] = _session(*groups)
            return await handler(request)

        app = web.Application()
        # Registered before setup_saas_api so it runs outside tenant
        # resolution, mirroring the real order (auth, then tenant, then ABAC).
        app.middlewares.append(_fake_session)
        setup_saas_api(
            app,
            dsn=test_dsn,
            schema=unique_schema,
            secret_store=secret_store,
            require_auth=False,
        )
        if with_pdp:
            app["abac"] = _PDP(evaluator or _evaluator())
        http = await aiohttp_client(app)
        await http.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "Bar Pepe"})
        created.append(http)
        return http

    try:
        yield _build
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------


async def test_tenant_admin_may_write(client_factory, policies_exist) -> None:
    """The shipped policy grants secret management to tenant admins."""
    client = await client_factory("tenant_admin")

    resp = await client.put(
        f"{SECRETS}/{ANTHROPIC}", json={"value": "sk-ant-x"}, headers=HDR
    )

    assert resp.status == 201


@pytest.mark.parametrize("groups", [("tenant_operator",), ()])
async def test_non_admins_may_not_write(
    client_factory, policies_exist, groups
) -> None:
    """An operator runs the day to day; it must not change the credentials."""
    client = await client_factory(*groups)

    resp = await client.put(
        f"{SECRETS}/{ANTHROPIC}", json={"value": "sk-ant-x"}, headers=HDR
    )

    assert resp.status == 403
    assert (await resp.json())["error"] == "forbidden"


async def test_non_admins_may_not_list(client_factory, policies_exist) -> None:
    """Fingerprints are metadata, but they are still the tenant's own."""
    client = await client_factory("tenant_operator")

    resp = await client.get(SECRETS, headers=HDR)

    assert resp.status == 403


async def test_non_admins_may_not_delete_or_rotate(
    client_factory, policies_exist
) -> None:
    """The destructive verbs are covered too, not only the write."""
    client = await client_factory("tenant_operator")

    deleted = await client.delete(f"{SECRETS}/{ANTHROPIC}", headers=HDR)
    rotated = await client.post(f"{SECRETS}/rotate-dek", headers=HDR)

    assert deleted.status == 403
    assert rotated.status == 403


async def test_authorization_precedes_validation(
    client_factory, policies_exist
) -> None:
    """A denied caller must not learn anything from a validation message."""
    client = await client_factory("tenant_operator")

    resp = await client.put(
        f"{SECRETS}/NOT-A-VALID-KEY", json={"value": ""}, headers=HDR
    )

    assert resp.status == 403


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


async def test_without_a_policy_engine_it_warns_and_serves(
    client_factory, caplog
) -> None:
    """``setup_pbac`` returns nothing when its directory is missing.

    Allowing here matches the convention of the rest of the repository, and is
    defensible only because authorization is not the isolation boundary:
    without a PDP the degradation is "any authenticated user of this tenant"
    rather than "only its admin" — never another tenant, which the resolution
    middleware separates on its own. The warning is part of the contract.
    """
    caplog.set_level(logging.WARNING)
    client = await client_factory("tenant_operator", with_pdp=False)

    resp = await client.put(
        f"{SECRETS}/{ANTHROPIC}", json={"value": "sk-ant-x"}, headers=HDR
    )

    assert resp.status == 201
    assert any(
        "no PBAC policy engine configured" in r.getMessage() for r in caplog.records
    )


async def test_a_broken_evaluation_denies(client_factory, policies_exist) -> None:
    """An evaluator that raises must not become an open door."""

    class _Exploding:
        def check_access(self, **kwargs):
            raise RuntimeError("policy backend is down")

    client = await client_factory("tenant_admin", evaluator=_Exploding())

    resp = await client.get(SECRETS, headers=HDR)

    assert resp.status == 403
