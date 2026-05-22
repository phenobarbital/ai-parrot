"""Unit tests for HumanDecisionNode escalation_policy_id + severity kwargs.

TASK-1281 — FEAT-194 hitl-escalation-tier
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from parrot.human.models import (
    ConsensusMode,
    HumanInteraction,
    InteractionResult,
    InteractionStatus,
    InteractionType,
    Severity,
)
from parrot.human.node import HumanDecisionNode


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_result(interaction_id: str, value: str = "approved") -> InteractionResult:
    return InteractionResult(
        interaction_id=interaction_id,
        status=InteractionStatus.COMPLETED,
        consolidated_value=value,
    )


def _make_manager(interaction_id: str, value: str = "approved"):
    """Mock manager that returns a COMPLETED result."""
    mgr = AsyncMock()

    async def fake_request(interaction, channel="telegram"):
        return _make_result(interaction.interaction_id, value)

    mgr.request_human_input = fake_request
    return mgr


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestDecisionNodePolicyKwargs:

    @pytest.mark.asyncio
    async def test_built_interaction_carries_policy_id_and_severity(self):
        """Constructor kwargs escalation_policy_id + severity propagate to interaction."""
        built_interactions = []
        mgr = AsyncMock()

        async def capture_request(interaction, channel="telegram"):
            built_interactions.append(interaction)
            return _make_result(interaction.interaction_id)

        mgr.request_human_input = capture_request

        node = HumanDecisionNode(
            name="test_node",
            manager=mgr,
            escalation_policy_id="hr-policy",
            severity=Severity.HIGH,
        )

        await node.ask("Please review.")

        assert len(built_interactions) == 1
        built = built_interactions[0]
        assert built.policy_id == "hr-policy"
        assert built.severity == Severity.HIGH

    @pytest.mark.asyncio
    async def test_ctor_kwarg_wins_over_interaction_config_policy_id(self):
        """Constructor escalation_policy_id wins over interaction_config.policy_id."""
        built_interactions = []
        mgr = AsyncMock()

        async def capture_request(interaction, channel="telegram"):
            built_interactions.append(interaction)
            return _make_result(interaction.interaction_id)

        mgr.request_human_input = capture_request

        config = HumanInteraction(
            question="Base question?",
            policy_id="config-policy",
            severity=Severity.LOW,
        )
        node = HumanDecisionNode(
            name="test_node",
            manager=mgr,
            interaction_config=config,
            escalation_policy_id="override-policy",
            severity=Severity.HIGH,
        )

        await node.ask()

        built = built_interactions[0]
        assert built.policy_id == "override-policy"  # ctor wins
        assert built.severity == Severity.HIGH         # ctor wins

    @pytest.mark.asyncio
    async def test_interaction_config_policy_id_used_when_no_ctor_override(self):
        """When escalation_policy_id is None, interaction_config.policy_id is used."""
        built_interactions = []
        mgr = AsyncMock()

        async def capture_request(interaction, channel="telegram"):
            built_interactions.append(interaction)
            return _make_result(interaction.interaction_id)

        mgr.request_human_input = capture_request

        config = HumanInteraction(
            question="Review?",
            policy_id="config-policy",
            severity=Severity.CRITICAL,
        )
        node = HumanDecisionNode(
            name="test_node",
            manager=mgr,
            interaction_config=config,
            # No escalation_policy_id / severity — defaults to None / NORMAL
        )

        await node.ask()

        built = built_interactions[0]
        assert built.policy_id == "config-policy"   # from config
        assert built.severity == Severity.CRITICAL   # from config (ctor is NORMAL → config wins)

    @pytest.mark.asyncio
    async def test_no_new_kwargs_back_compat(self):
        """Existing nodes constructed without new kwargs continue to work."""
        built_interactions = []
        mgr = AsyncMock()

        async def capture_request(interaction, channel="telegram"):
            built_interactions.append(interaction)
            return _make_result(interaction.interaction_id)

        mgr.request_human_input = capture_request

        node = HumanDecisionNode(
            name="legacy_node",
            manager=mgr,
        )

        result = await node.ask("What should I do?")

        built = built_interactions[0]
        assert built.policy_id is None
        assert built.severity == Severity.NORMAL
        assert result == "approved"  # consolidated_value

    @pytest.mark.asyncio
    async def test_no_policy_on_bare_construction(self):
        """HumanDecisionNode() without new kwargs has None policy and NORMAL severity."""
        node = HumanDecisionNode(name="bare", manager=None)
        assert node.escalation_policy_id is None
        assert node.severity == Severity.NORMAL
