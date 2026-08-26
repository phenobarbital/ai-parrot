"""Tests for swarm config models — FEAT-463 TASK-2478."""
import pytest
from pydantic import ValidationError

from parrot.integrations.matrix.crew.config import (
    ChannelConfig,
    MatrixCrewAgentEntry,
    MatrixCrewConfig,
)

BASE = dict(
    homeserver_url="http://hs",
    server_name="parrot.local",
    as_token="a",
    hs_token="h",
    bot_mxid="@parrot:parrot.local",
    general_room_id="!gen:parrot.local",
)
AGENTS = {
    "analyst": MatrixCrewAgentEntry(
        chatbot_id="analyst",
        display_name="Analyst",
        mxid_localpart="parrot-analyst",
    )
}


def test_defaults_backward_compat():
    cfg = MatrixCrewConfig(**BASE, agents=AGENTS)
    assert cfg.channels == []
    assert cfg.tunnels.ttl_minutes == 120
    assert cfg.space.enabled is False
    assert cfg.human_namespace_patterns[0].startswith("^@signal_")


def test_channel_unknown_agent():
    with pytest.raises(ValidationError, match="unknown agents"):
        MatrixCrewConfig(
            **BASE,
            agents=AGENTS,
            channels=[ChannelConfig(name="general", agents=["ghost"])],
        )


def test_swarm_requires_collaborative():
    with pytest.raises(ValidationError, match="collaborative"):
        MatrixCrewConfig(
            **BASE,
            agents=AGENTS,
            channels=[
                ChannelConfig(name="g", agents=["analyst"], answer_policy="swarm")
            ],
        )


def test_router_policy_rejected():
    with pytest.raises(ValidationError):
        ChannelConfig(name="g", answer_policy="router")


def test_duplicate_channel_names():
    with pytest.raises(ValidationError, match="duplicate"):
        MatrixCrewConfig(**BASE, channels=[ChannelConfig(name="a"), ChannelConfig(name="a")])


def test_examples_still_load():
    for f in (
        "examples/matrix_crew/matrix_crew.yaml",
        "examples/matrix_crew/collaborative_crew.yaml",
    ):
        assert MatrixCrewConfig.from_yaml(f)  # env vars substituted to "" is fine
