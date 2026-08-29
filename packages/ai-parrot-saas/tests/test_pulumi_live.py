"""A real ``pulumi up`` against a real Docker daemon.

Skipped unless three things hold: ``SAAS_PULUMI_E2E=1`` is set, the ``pulumi``
CLI is on PATH, and ``docker info`` answers. All three are checked rather than
assumed — a "live" test that silently ran against nothing would be worse than
no test, because it would go green.

This is the only place the three executor workarounds are proved *together*
against the real thing. Everything else about the deployer is covered by
``test_pulumi_deployer.py``, which needs neither.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from parrot_saas.provisioning.models import DeploymentStatus
from parrot_saas.provisioning.pulumi_deployer import (
    DSN_SECRET_TEMPLATE,
    PulumiDeployer,
    stack_name,
)
from parrot_saas.tenancy.context import TenantContext


def _docker_is_up() -> bool:
    """Whether a Docker daemon actually answers."""
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("SAAS_PULUMI_E2E") != "1",
        reason="set SAAS_PULUMI_E2E=1 to run the live provisioning test",
    ),
    pytest.mark.skipif(
        shutil.which("pulumi") is None, reason="the pulumi CLI is not installed"
    ),
    pytest.mark.skipif(
        not _docker_is_up(), reason="no Docker daemon is answering"
    ),
]


class _Store:
    """In-memory secret store, so no vault key is needed to run this."""

    def __init__(self) -> None:
        self.values: dict = {}

    async def put(self, tenant_id, key, value):
        self.values[(tenant_id, key)] = value

    async def delete(self, tenant_id, key):
        return self.values.pop((tenant_id, key), None) is not None


@pytest.fixture
def tenant() -> TenantContext:
    """A tenant slug unlikely to collide with anything on the machine."""
    return TenantContext(
        tenant_id="pulumi-e2e", name="Pulumi E2E", mode="dedicated"
    )


@pytest.fixture
def deployer(tmp_path, tenant):
    """A deployer on a throwaway state directory, torn down afterwards."""
    store = _Store()
    instance = PulumiDeployer(
        secret_store=store,
        state_dir=tmp_path / "state",
        # A port well outside the default range, so a developer's own stacks
        # are not disturbed.
        port_allocator=lambda _tenant: 18777,
    )
    instance.store = store  # type: ignore[attr-defined]
    try:
        yield instance
    finally:
        import asyncio

        asyncio.run(instance.destroy(tenant))


async def test_a_dedicated_stack_comes_up_and_goes_down(deployer, tenant) -> None:
    """Plan, apply, status, destroy — against real containers.

    The three workarounds are all load-bearing here: without the written stack
    config the program has no tenant id, without ``PULUMI_BACKEND_URL`` the
    CLI reaches for Pulumi Cloud, and with ``use_docker`` left on there is no
    Docker socket inside the container to build anything with.
    """
    planned = await deployer.plan(tenant)
    assert planned.success, planned.detail
    assert planned.status == DeploymentStatus.PENDING.value

    applied = await deployer.apply(tenant)
    assert applied.success, applied.detail
    assert applied.status == DeploymentStatus.READY.value
    assert applied.outputs["host_port"] == 18777

    # The DSN reached the store and not the outputs.
    ref = DSN_SECRET_TEMPLATE.format(stack=stack_name(tenant.tenant_id))
    assert applied.secret_refs == [ref]
    assert "dsn" not in applied.outputs
    assert deployer.store.values[(tenant.tenant_id, ref)].startswith("postgres://")

    live = await deployer.status(tenant)
    assert live.status == DeploymentStatus.READY.value
    assert live.outputs["worker_container"].endswith("-worker")

    torn = await deployer.destroy(tenant)
    assert torn.success, torn.detail
    assert torn.status == DeploymentStatus.DESTROYED.value
    assert deployer.store.values == {}
