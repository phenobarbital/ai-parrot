"""Shared opt-in fixtures for FEAT-581 process-boundary E2E scenarios."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

from parrot.e2e.models import TargetConfig
from parrot.e2e.supervisor import AdapterResolver, E2ESupervisor

_FEATURE_ID = "FEAT-581"
_OPT_IN_ENV = "PARROT_TEST_E2E"


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip suite scenarios unless their explicit deterministic opt-in is set.

    This hook runs before pytest constructs fixtures, so an omitted opt-in
    cannot create a supervisor or spawn a target process.

    Args:
        item: The test item pytest is about to set up.
    """
    if item.get_closest_marker("e2e") and os.environ.get(_OPT_IN_ENV) != "1":
        pytest.skip(f"set {_OPT_IN_ENV}=1 to run process-boundary E2E scenarios")


@pytest.fixture(scope="session")
def e2e_worktree() -> Path:
    """Return the checkout root that supervised targets must import from.

    Returns:
        The repository root containing this suite's source checkout.
    """
    return Path(__file__).resolve().parents[4]


@pytest.fixture
async def e2e_supervisor_factory(
    e2e_worktree: Path,
) -> AsyncIterator[Callable[[AdapterResolver | None], E2ESupervisor]]:
    """Create owner-scoped supervisors and stop every started target on teardown.

    Args:
        e2e_worktree: The checkout whose clean source target children import.

    Yields:
        A factory accepting an optional fixed target-adapter resolver.
    """
    owner_id = f"pytest-e2e-{uuid.uuid4().hex}"
    supervisors: list[E2ESupervisor] = []

    def _create(adapter_resolver: AdapterResolver | None = None) -> E2ESupervisor:
        supervisor = E2ESupervisor(
            worktree=e2e_worktree,
            owner_id=owner_id,
            feature_id=_FEATURE_ID,
            adapter_resolver=adapter_resolver,
        )
        supervisors.append(supervisor)
        return supervisor

    try:
        yield _create
    finally:
        for supervisor in supervisors:
            for run_id in list(supervisor._runs):
                state = await supervisor.stop(run_id)
                assert state.cleanup_complete, f"supervisor did not clean up owned run {run_id}"


@pytest.fixture
def mcp_toolkit_config() -> TargetConfig:
    """Return the fixed real working-memory HTTP target configuration.

    Returns:
        The supported deterministic MCP toolkit target configuration.
    """
    return TargetConfig(kind="mcp-toolkit", startup_timeout_s=30)


@pytest.fixture
def mcp_stdio_config() -> TargetConfig:
    """Return the fixed real working-memory stdio target configuration.

    Returns:
        The supported deterministic MCP stdio target configuration.
    """
    return TargetConfig(kind="mcp-stdio", startup_timeout_s=30)
