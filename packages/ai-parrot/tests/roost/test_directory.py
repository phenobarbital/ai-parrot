"""Tests for Roost capability-directory models and ranking."""

import sys

import pytest

from parrot.roost.directory import CapabilityMatch, InterAgentGrant, Locality, RoostAgentConfig, locality_of, rank
from parrot.roost.performatives import CarrierKind


def test_rank_orders_by_locality_then_cost_then_descending_score() -> None:
    """Nearest and cheapest matches rank first, with score breaking remaining ties."""
    matches = [
        CapabilityMatch(agent_name="remote", cap_id="x", locality=Locality.REMOTE, cost=0.1, score=1.0),
        CapabilityMatch(agent_name="local-low-score", cap_id="x", locality=Locality.IN_PROCESS, cost=1.0, score=0.5),
        CapabilityMatch(agent_name="local-expensive", cap_id="x", locality=Locality.IN_PROCESS, cost=2.0, score=10.0),
        CapabilityMatch(agent_name="local-high-score", cap_id="x", locality=Locality.IN_PROCESS, cost=1.0, score=0.9),
    ]

    assert [match.agent_name for match in rank(matches)] == [
        "local-high-score",
        "local-low-score",
        "local-expensive",
        "remote",
    ]


def test_rank_preserves_input_order_for_equal_keys() -> None:
    """Matches with identical ranking keys retain their input order."""
    matches = [
        CapabilityMatch(agent_name="first", cap_id="x", locality=Locality.SAME_HOST, cost=1.0, score=0.5),
        CapabilityMatch(agent_name="second", cap_id="x", locality=Locality.SAME_HOST, cost=1.0, score=0.5),
    ]

    assert [match.agent_name for match in rank(matches)] == ["first", "second"]


@pytest.mark.parametrize("kind", ["a2a", "squawk"])
def test_locality_of_remote_registry_kinds(kind: str) -> None:
    """External registry kinds are remote regardless of their Roost carrier."""
    config = RoostAgentConfig(carrier=CarrierKind.IN_PROCESS)

    assert locality_of(config, kind=kind, local_host_id="host-a") == Locality.REMOTE
    assert locality_of(None, kind=kind, local_host_id=None) == Locality.REMOTE


def test_locality_of_plain_local_entry_is_in_process() -> None:
    """A local registry entry without a Roost advertisement is in this process."""
    assert locality_of(None, kind="local", local_host_id="host-a") == Locality.IN_PROCESS


def test_locality_of_in_process_carrier() -> None:
    """An explicitly in-process Roost advertisement is in this process."""
    config = RoostAgentConfig(carrier=CarrierKind.IN_PROCESS, host_id="other-host")

    assert locality_of(config, kind="local", local_host_id="host-a") == Locality.IN_PROCESS


def test_locality_of_same_host_carrier() -> None:
    """A same-host carrier is local only when its host identifier matches."""
    config = RoostAgentConfig(carrier=CarrierKind.SAME_HOST, host_id="host-a")

    assert locality_of(config, kind="local", local_host_id="host-a") == Locality.SAME_HOST
    assert locality_of(config, kind="local", local_host_id="host-b") == Locality.SAME_NETWORK


@pytest.mark.parametrize("carrier", [CarrierKind.NETWORK, CarrierKind.MATRIX])
def test_locality_of_network_carriers(carrier: CarrierKind) -> None:
    """Network and Matrix carriers are classified on the same network tier."""
    config = RoostAgentConfig(carrier=carrier, host_id="host-a")

    assert locality_of(config, kind="local", local_host_id="host-a") == Locality.SAME_NETWORK


def test_model_defaults_are_isolated() -> None:
    """Mutable model defaults are not shared between advertisements or grants."""
    first_config = RoostAgentConfig()
    second_config = RoostAgentConfig()
    first_grant = InterAgentGrant()
    second_grant = InterAgentGrant()

    first_config.capabilities.append("hr.people.salary")
    first_grant.scopes.append("hr.*")

    assert second_config.capabilities == []
    assert second_grant.scopes == []


def test_directory_does_not_import_registry() -> None:
    """The dependency-light directory module must not introduce a registry import cycle."""
    assert "parrot.registry" not in sys.modules
