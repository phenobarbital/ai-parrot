"""The provisioning control plane, over HTTP against Postgres.

The claim is what most of this is about. Two ``pulumi up`` processes on one
stack corrupt its state file, and this is an HTTP API someone can call twice
in a second, so "is it busy?" has to be a conditional write rather than a read
followed by a write. The concurrency test drives that directly.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.deployments import (
    APP_DEPLOYMENT_REPOSITORY,
)
from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.provisioning.models import DeploymentResult, DeploymentStatus

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
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


class _Deployer:
    """A deployer whose every operation is observable and controllable."""

    name = "fake"

    def __init__(self, *, gate: asyncio.Event | None = None, fail=False) -> None:
        self.calls: list[str] = []
        self.gate = gate
        self.fail = fail

    async def _run(self, tenant, operation, status):
        self.calls.append(operation)
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("the docker daemon is not running")
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation=operation,
            success=True,
            status=status,
            stack=f"tenant-{tenant.tenant_id}",
            outputs={"port": 18000},
            detail="ok",
        )

    async def plan(self, tenant):
        return await self._run(tenant, "plan", DeploymentStatus.PENDING)

    async def apply(self, tenant):
        return await self._run(tenant, "apply", DeploymentStatus.READY)

    async def destroy(self, tenant):
        return await self._run(tenant, "destroy", DeploymentStatus.DESTROYED)

    async def status(self, tenant):
        return await self._run(tenant, "status", DeploymentStatus.READY)


@pytest.fixture
async def client_factory(
    aiohttp_client, test_dsn: str, unique_schema: str, secret_store
):
    """Build a wired app with a controllable deployer."""

    async def _build(*groups: str, deployer=None, with_pdp: bool = False, mode="shared"):
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
            deployers={"shared": deployer} if deployer is not None else None,
        )
        if with_pdp:
            app["abac"] = _PDP(_evaluator())
        http = await aiohttp_client(app)
        await http.post(
            CONTROL,
            json={"tenant_id": "bar-pepe", "name": "Bar Pepe", "mode": mode},
        )
        return http

    try:
        yield _build
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


@pytest.fixture
async def client(client_factory):
    """A platform-admin client with a controllable deployer."""
    return await client_factory("platform_admin", deployer=_Deployer())


# ---------------------------------------------------------------------------
# The operations
# ---------------------------------------------------------------------------


async def test_apply_returns_202_and_records_ready(client) -> None:
    """Long operations answer with a job id, not a result."""
    resp = await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert resp.status == 202
    body = await resp.json()
    assert body["job_id"]
    assert body["operation"] == "apply"

    deployments = client.app[APP_DEPLOYMENT_REPOSITORY]
    record = await deployments.get("bar-pepe")
    assert record.status == DeploymentStatus.READY.value
    assert record.stack == "tenant-bar-pepe"
    assert record.outputs == {"port": 18000}
    assert record.job_id == ""  # cleared when the operation finished


async def test_a_plan_does_not_leave_the_tenant_looking_provisioned(
    client,
) -> None:
    """A plan changes nothing, so it must not record 'ready'."""
    resp = await client.post(f"{CONTROL}/bar-pepe/plan")

    assert resp.status == 202
    record = await client.app[APP_DEPLOYMENT_REPOSITORY].get("bar-pepe")
    assert record.status == DeploymentStatus.PENDING.value


async def test_a_failing_operation_records_the_reason(client_factory) -> None:
    """A background failure must not vanish into a worker log."""
    client = await client_factory("platform_admin", deployer=_Deployer(fail=True))

    resp = await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert resp.status == 202
    record = await client.app[APP_DEPLOYMENT_REPOSITORY].get("bar-pepe")
    assert record.status == DeploymentStatus.FAILED.value
    assert "docker daemon" in record.last_error


async def test_a_later_success_clears_the_previous_error(client_factory) -> None:
    """A stale message beside a healthy stack is worse than none."""
    deployer = _Deployer(fail=True)
    client = await client_factory("platform_admin", deployer=deployer)
    await client.post(f"{CONTROL}/bar-pepe/deploy")

    deployer.fail = False
    await client.post(f"{CONTROL}/bar-pepe/deploy")

    record = await client.app[APP_DEPLOYMENT_REPOSITORY].get("bar-pepe")
    assert record.status == DeploymentStatus.READY.value
    assert record.last_error == ""


async def test_destroy_records_destroyed(client) -> None:
    """And keeps the row, so the history survives a rebuild."""
    await client.post(f"{CONTROL}/bar-pepe/deploy")

    resp = await client.delete(f"{CONTROL}/bar-pepe/deployment")

    assert resp.status == 202
    record = await client.app[APP_DEPLOYMENT_REPOSITORY].get("bar-pepe")
    assert record.status == DeploymentStatus.DESTROYED.value
    assert record.stack == "tenant-bar-pepe"  # not erased by the destroy


async def test_status_reads_the_row_and_the_backend(client) -> None:
    """A row saying 'ready' about a stack someone removed by hand is a lie."""
    await client.post(f"{CONTROL}/bar-pepe/deploy")

    body = await (await client.get(f"{CONTROL}/bar-pepe/deployment")).json()

    assert body["status"] == DeploymentStatus.READY.value
    assert body["live"]["operation"] == "status"


async def test_an_unprovisioned_tenant_reports_pending(client) -> None:
    """No row yet is a state, not a 404."""
    body = await (await client.get(f"{CONTROL}/bar-pepe/deployment")).json()

    assert body["status"] == DeploymentStatus.PENDING.value


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


async def test_a_second_operation_while_one_is_in_flight_is_409(
    client_factory,
) -> None:
    """Two ``pulumi up`` runs on one stack corrupt its state file.

    409 and not 400: the request is perfectly valid, it just conflicts with
    the deployment's current state — which is exactly the distinction a
    retrying client needs.
    """
    gate = asyncio.Event()
    deployer = _Deployer(gate=gate)
    client = await client_factory("platform_admin", deployer=deployer)

    first = asyncio.create_task(client.post(f"{CONTROL}/bar-pepe/deploy"))
    await asyncio.sleep(0.05)  # let the first claim land
    second = await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert second.status == 409
    body = await second.json()
    assert body["error"] == "deployment_busy"
    assert body["current_status"] == DeploymentStatus.APPLYING.value

    gate.set()
    assert (await first).status == 202
    assert deployer.calls == ["apply"]


async def test_the_deployment_is_operable_again_after_it_finishes(client) -> None:
    """The claim must clear, or a tenant is stuck forever."""
    await client.post(f"{CONTROL}/bar-pepe/deploy")

    second = await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert second.status == 202


async def test_a_crashing_operation_still_clears_the_claim(
    client_factory,
) -> None:
    """Otherwise one bad deploy locks the tenant out of every later one."""
    client = await client_factory("platform_admin", deployer=_Deployer(fail=True))
    await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert (await client.post(f"{CONTROL}/bar-pepe/deploy")).status == 202


# ---------------------------------------------------------------------------
# Lifecycle and authorization
# ---------------------------------------------------------------------------


async def test_an_unknown_tenant_is_404(client) -> None:
    """The middleware does not run here, so the handler checks by hand."""
    assert (await client.post(f"{CONTROL}/nobody/deploy")).status == 404


async def test_a_suspended_tenant_cannot_be_provisioned(client) -> None:
    """Retiring a tenant has to actually stop work being done for them."""
    await client.delete(f"{CONTROL}/bar-pepe")

    resp = await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert resp.status == 403
    assert (await resp.json())["error"] == "tenant_suspended"


async def test_a_mode_with_no_deployer_names_what_is_configured(
    client_factory,
) -> None:
    """A wiring mistake should be readable from the response."""
    client = await client_factory(
        "platform_admin", deployer=_Deployer(), mode="dedicated"
    )

    resp = await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert resp.status == 503
    body = await resp.json()
    assert body["error"] == "not_configured"
    assert body["configured"] == ["shared"]


async def test_only_platform_staff_may_provision(client_factory) -> None:
    """A tenant admin manages their own configuration, not the platform's."""
    client = await client_factory(
        "tenant_admin", deployer=_Deployer(), with_pdp=True
    )

    assert (await client.post(f"{CONTROL}/bar-pepe/deploy")).status == 403


async def test_platform_staff_may(client_factory) -> None:
    """The mirror, so the test above cannot pass by denying everyone."""
    client = await client_factory(
        "platform_admin", deployer=_Deployer(), with_pdp=True
    )

    assert (await client.post(f"{CONTROL}/bar-pepe/deploy")).status == 202


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


async def test_the_dedicated_deployer_is_off_by_default(client_factory) -> None:
    """A shared-only deployment must not require Pulumi or a Docker daemon."""
    client = await client_factory("platform_admin")

    assert sorted(client.app["saas_deployers"]) == ["shared"]


async def test_the_dedicated_deployer_is_wired_when_enabled(
    client_factory, monkeypatch
) -> None:
    """And the flag is the only thing standing between the two modes."""
    monkeypatch.setattr(
        "parrot_saas.conf.SAAS_ENABLE_DEDICATED", True, raising=False
    )
    client = await client_factory("platform_admin", mode="dedicated")

    assert sorted(client.app["saas_deployers"]) == ["dedicated", "shared"]
    # And a dedicated tenant now reaches a deployer rather than a 503. It
    # fails, because this machine has no Pulumi CLI — with a message that says
    # exactly that, which is the point.
    resp = await client.post(f"{CONTROL}/bar-pepe/deploy")
    assert resp.status == 202
    record = await client.app[APP_DEPLOYMENT_REPOSITORY].get("bar-pepe")
    assert record.status == DeploymentStatus.FAILED.value
    assert "not on PATH" in record.last_error


async def test_the_default_shared_deployer_seeds_a_real_tenant(
    client_factory,
) -> None:
    """The wiring, not the deployer: the real one, through the real routes."""
    client = await client_factory("platform_admin")

    resp = await client.post(f"{CONTROL}/bar-pepe/deploy")

    assert resp.status == 202
    offers = await (
        await client.get(
            "/api/v1/saas/coupon-offers", headers={"X-Tenant-Id": "bar-pepe"}
        )
    ).json()
    rules = await (
        await client.get(
            "/api/v1/saas/rules", headers={"X-Tenant-Id": "bar-pepe"}
        )
    ).json()

    assert [offer["code"] for offer in offers["offers"]] == ["RECOVER20"]
    assert {rule["name"] for rule in rules["rules"]} == {
        "recover_detractor",
        "thank_loyal_promoter",
    }
