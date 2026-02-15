"""Unit tests for DecisionFlowNode component."""
import pytest
from unittest.mock import AsyncMock, Mock, patch

from parrot.bots.orchestration.decision_node import (
    BinaryDecision,
    ApprovalDecision,
    DecisionFlowNode,
    DecisionMode,
    DecisionNodeConfig,
    DecisionResult,
    DecisionType,
    EscalationPolicy,
    VoteWeight,
)


# =============================================================================
# Mock Agents
# =============================================================================


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, name: str, response: Any):
        """Initialize mock agent.

        Args:
            name: Agent name.
            response: Response to return from ask().
        """
        self.name = name
        self._response = response
        self.is_configured = True

    async def ask(self, question: str = "", **kwargs):
        """Mock ask method.

        Args:
            question: The question.
            **kwargs: Additional arguments.

        Returns:
            The pre-configured response.
        """
        return self._response


# =============================================================================
# Test CIO Mode
# =============================================================================


@pytest.mark.asyncio
async def test_cio_mode_basic():
    """Test CIO mode with single agent making decision."""
    # Create mock agent that returns YES
    yes_decision = BinaryDecision(decision="YES", confidence=0.95, reasoning="Test reasoning")
    agent = MockAgent("checker", yes_decision)

    # Create decision node
    node = DecisionFlowNode(
        name="test_cio",
        agents={"checker": agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
        ),
    )

    # Execute
    result = await node.ask("Is this admin?", user_id="test")

    # Assertions
    assert isinstance(result, DecisionResult)
    assert result.mode == DecisionMode.CIO
    assert result.final_decision == "YES"
    assert result.confidence == 0.95
    assert not result.escalated
    assert "checker" in result.votes
    assert result.votes["checker"] == "YES"


@pytest.mark.asyncio
async def test_cio_mode_with_no_decision():
    """Test CIO mode when agent returns NO."""
    no_decision = BinaryDecision(decision="NO", confidence=0.88, reasoning="Not admin")
    agent = MockAgent("checker", no_decision)

    node = DecisionFlowNode(
        name="test_cio",
        agents={"checker": agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
        ),
    )

    result = await node.ask("Is this admin?")

    assert result.final_decision == "NO"
    assert result.confidence == 0.88


@pytest.mark.asyncio
async def test_cio_mode_low_confidence_escalation():
    """Test CIO mode escalation on low confidence."""
    low_conf_decision = BinaryDecision(decision="YES", confidence=0.5, reasoning="Uncertain")
    agent = MockAgent("checker", low_conf_decision)

    node = DecisionFlowNode(
        name="test_cio",
        agents={"checker": agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            escalation_policy=EscalationPolicy(
                enabled=True,
                on_low_confidence=0.7,
                fallback_decision="NO",
            ),
        ),
    )

    result = await node.ask("Is this admin?")

    # Should escalate and use fallback
    assert result.escalated
    assert result.final_decision == "NO"
    assert result.escalation_reason == "No HITL manager available"


@pytest.mark.asyncio
async def test_cio_mode_explicit_escalate():
    """Test CIO mode with explicit ESCALATE decision."""
    escalate_decision = ApprovalDecision(
        decision="ESCALATE",
        confidence=0.8,
        reasoning="Need human input",
        escalation_reason="Ambiguous case",
    )
    agent = MockAgent("checker", escalate_decision)

    node = DecisionFlowNode(
        name="test_cio",
        agents={"checker": agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.APPROVAL,
            decision_schema=ApprovalDecision,
            escalation_policy=EscalationPolicy(
                enabled=True,
                on_explicit_keyword=True,
                fallback_decision="REJECT",
            ),
        ),
    )

    result = await node.ask("Should we approve?")

    assert result.escalated
    assert result.final_decision == "REJECT"


# =============================================================================
# Test Ballot Mode
# =============================================================================


@pytest.mark.asyncio
async def test_ballot_mode_unanimous():
    """Test Ballot mode with unanimous vote."""
    # All agents vote YES
    agents = {
        f"agent{i}": MockAgent(
            f"agent{i}", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes")
        )
        for i in range(5)
    }

    node = DecisionFlowNode(
        name="test_ballot",
        agents=agents,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            vote_weight_strategy=VoteWeight.EQUAL,
        ),
    )

    result = await node.ask("Vote YES or NO")

    assert result.final_decision == "YES"
    assert result.consensus_level == "UNANIMOUS"
    assert len(result.votes) == 5
    assert result.vote_distribution["YES"] == 5


@pytest.mark.asyncio
async def test_ballot_mode_majority():
    """Test Ballot mode with majority vote."""
    # 3 YES, 2 NO
    agents = {
        "agent1": MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes")),
        "agent2": MockAgent("agent2", BinaryDecision(decision="YES", confidence=0.8, reasoning="Yes")),
        "agent3": MockAgent("agent3", BinaryDecision(decision="YES", confidence=0.85, reasoning="Yes")),
        "agent4": MockAgent("agent4", BinaryDecision(decision="NO", confidence=0.75, reasoning="No")),
        "agent5": MockAgent("agent5", BinaryDecision(decision="NO", confidence=0.7, reasoning="No")),
    }

    node = DecisionFlowNode(
        name="test_ballot",
        agents=agents,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
        ),
    )

    result = await node.ask("Vote YES or NO")

    assert result.final_decision == "YES"
    assert result.consensus_level == "MAJORITY"
    assert result.vote_distribution["YES"] == 3
    assert result.vote_distribution["NO"] == 2


@pytest.mark.asyncio
async def test_ballot_mode_custom_weights():
    """Test Ballot mode with custom vote weights."""
    # 2 NO (weight 1.0 each), 1 YES (weight 3.0) → YES wins due to weighting
    agents = {
        "risk": MockAgent("risk", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes")),
        "agent1": MockAgent("agent1", BinaryDecision(decision="NO", confidence=0.8, reasoning="No")),
        "agent2": MockAgent("agent2", BinaryDecision(decision="NO", confidence=0.8, reasoning="No")),
    }

    node = DecisionFlowNode(
        name="test_ballot",
        agents=agents,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            vote_weight_strategy=VoteWeight.CUSTOM,
            custom_weights={"risk": 3.0, "agent1": 1.0, "agent2": 1.0},
        ),
    )

    result = await node.ask("Vote YES or NO")

    # Risk agent's vote weighted 3x should make YES win
    assert result.final_decision == "YES"


@pytest.mark.asyncio
async def test_ballot_mode_split_vote_escalation():
    """Test Ballot mode escalation on split vote."""
    # 2 YES, 2 NO
    agents = {
        "agent1": MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes")),
        "agent2": MockAgent("agent2", BinaryDecision(decision="YES", confidence=0.8, reasoning="Yes")),
        "agent3": MockAgent("agent3", BinaryDecision(decision="NO", confidence=0.85, reasoning="No")),
        "agent4": MockAgent("agent4", BinaryDecision(decision="NO", confidence=0.75, reasoning="No")),
    }

    node = DecisionFlowNode(
        name="test_ballot",
        agents=agents,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            escalation_policy=EscalationPolicy(
                enabled=True,
                on_split_vote=True,
                fallback_decision="NO",
            ),
        ),
    )

    result = await node.ask("Vote YES or NO")

    # Should escalate due to split
    assert result.escalated
    assert result.consensus_level == "DEADLOCK"


@pytest.mark.asyncio
async def test_ballot_mode_quorum_not_met():
    """Test Ballot mode when quorum not met."""
    # Only 2 agents, but minimum_votes is 3
    agents = {
        "agent1": MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes")),
        "agent2": MockAgent("agent2", BinaryDecision(decision="YES", confidence=0.8, reasoning="Yes")),
    }

    node = DecisionFlowNode(
        name="test_ballot",
        agents=agents,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            minimum_votes=3,
        ),
    )

    with pytest.raises(RuntimeError, match="Quorum not met"):
        await node.ask("Vote YES or NO")


# =============================================================================
# Test Consensus Mode
# =============================================================================


@pytest.mark.asyncio
async def test_consensus_mode_basic():
    """Test Consensus mode with cross-pollination and coordinator synthesis."""
    # Analysts provide initial votes
    analysts = {
        "analyst1": MockAgent(
            "analyst1", BinaryDecision(decision="YES", confidence=0.8, reasoning="Looks good")
        ),
        "analyst2": MockAgent(
            "analyst2", BinaryDecision(decision="NO", confidence=0.75, reasoning="Risky")
        ),
        "coordinator": MockAgent(
            "coordinator", BinaryDecision(decision="YES", confidence=0.9, reasoning="Final decision")
        ),
    }

    node = DecisionFlowNode(
        name="test_consensus",
        agents=analysts,
        config=DecisionNodeConfig(
            mode=DecisionMode.CONSENSUS,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            coordinator_agent_name="coordinator",
            cross_pollination_rounds=1,
        ),
    )

    result = await node.ask("Should we proceed?")

    assert result.mode == DecisionMode.CONSENSUS
    assert result.final_decision == "YES"
    assert result.confidence == 0.9
    assert "coordinator" in result.metadata
    assert result.metadata["coordinator"] == "coordinator"


@pytest.mark.asyncio
async def test_consensus_mode_multi_round():
    """Test Consensus mode with multiple cross-pollination rounds."""
    analysts = {
        "analyst1": MockAgent(
            "analyst1", BinaryDecision(decision="YES", confidence=0.85, reasoning="Initial yes")
        ),
        "analyst2": MockAgent(
            "analyst2", BinaryDecision(decision="YES", confidence=0.9, reasoning="Revised yes")
        ),
        "coordinator": MockAgent(
            "coordinator", BinaryDecision(decision="YES", confidence=0.95, reasoning="Synthesized")
        ),
    }

    node = DecisionFlowNode(
        name="test_consensus",
        agents=analysts,
        config=DecisionNodeConfig(
            mode=DecisionMode.CONSENSUS,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            coordinator_agent_name="coordinator",
            cross_pollination_rounds=2,
        ),
    )

    result = await node.ask("Decision?")

    assert result.final_decision == "YES"
    # Agents should have been called multiple times (initial + 2 revisions)


# =============================================================================
# Test Configuration Validation
# =============================================================================


def test_cio_mode_validation_multiple_agents():
    """Test that CIO mode rejects multiple agents."""
    agents = {
        "agent1": MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes")),
        "agent2": MockAgent("agent2", BinaryDecision(decision="NO", confidence=0.8, reasoning="No")),
    }

    with pytest.raises(ValueError, match="CIO mode requires exactly 1 agent"):
        DecisionFlowNode(
            name="invalid",
            agents=agents,
            config=DecisionNodeConfig(mode=DecisionMode.CIO, decision_type=DecisionType.BINARY),
        )


def test_consensus_mode_validation_no_coordinator():
    """Test that CONSENSUS mode requires coordinator."""
    agents = {"agent1": MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))}

    with pytest.raises(ValueError, match="CONSENSUS mode requires coordinator_agent_name"):
        DecisionFlowNode(
            name="invalid",
            agents=agents,
            config=DecisionNodeConfig(mode=DecisionMode.CONSENSUS, decision_type=DecisionType.BINARY),
        )


def test_consensus_mode_validation_coordinator_not_in_agents():
    """Test that CONSENSUS mode coordinator must be in agents."""
    agents = {"agent1": MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))}

    with pytest.raises(ValueError, match="Coordinator .* not in agents"):
        DecisionFlowNode(
            name="invalid",
            agents=agents,
            config=DecisionNodeConfig(
                mode=DecisionMode.CONSENSUS,
                decision_type=DecisionType.BINARY,
                coordinator_agent_name="nonexistent",
            ),
        )


def test_custom_weights_validation():
    """Test that CUSTOM weight strategy requires custom_weights."""
    agents = {"agent1": MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))}

    with pytest.raises(ValueError, match="CUSTOM weight strategy requires custom_weights"):
        DecisionFlowNode(
            name="invalid",
            agents=agents,
            config=DecisionNodeConfig(
                mode=DecisionMode.BALLOT,
                decision_type=DecisionType.BINARY,
                vote_weight_strategy=VoteWeight.CUSTOM,
            ),
        )


# =============================================================================
# Test FSM Integration
# =============================================================================


def test_fsm_contract_properties():
    """Test that DecisionFlowNode satisfies FSM contract."""
    agent = MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))

    node = DecisionFlowNode(
        name="test_node",
        agents={"agent1": agent},
        config=DecisionNodeConfig(mode=DecisionMode.CIO, decision_type=DecisionType.BINARY),
    )

    # Check FSM contract
    assert hasattr(node, "name")
    assert hasattr(node, "ask")
    assert hasattr(node, "tool_manager")
    assert hasattr(node, "is_configured")

    assert node.name == "test_node"
    assert node.is_configured is True
    assert callable(node.ask)


@pytest.mark.asyncio
async def test_decision_result_in_predicate():
    """Test that DecisionResult can be used in transition predicates."""
    agent = MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))

    node = DecisionFlowNode(
        name="test_node",
        agents={"agent1": agent},
        config=DecisionNodeConfig(mode=DecisionMode.CIO, decision_type=DecisionType.BINARY),
    )

    result = await node.ask("Test question")

    # Test predicates (as would be used in AgentsFlow)
    def is_yes(r):
        return isinstance(r, DecisionResult) and r.final_decision == "YES"

    def is_no(r):
        return isinstance(r, DecisionResult) and r.final_decision == "NO"

    def is_high_confidence(r):
        return isinstance(r, DecisionResult) and r.confidence >= 0.8

    assert is_yes(result)
    assert not is_no(result)
    assert is_high_confidence(result)


# =============================================================================
# Test Vote Aggregation
# =============================================================================


def test_vote_aggregation_equal_weights():
    """Test vote aggregation with equal weights."""
    agent = MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))

    node = DecisionFlowNode(
        name="test",
        agents={"agent1": agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
            vote_weight_strategy=VoteWeight.EQUAL,
        ),
    )

    votes = {"agent1": "YES", "agent2": "YES", "agent3": "NO"}
    final, dist, consensus = node._aggregate_votes(votes)

    assert final == "YES"
    assert dist["YES"] == 2
    assert dist["NO"] == 1
    assert consensus == "MAJORITY"


def test_vote_aggregation_seniority_weights():
    """Test vote aggregation with seniority weights."""
    agents = {
        "senior": MockAgent("senior", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes")),
        "junior": MockAgent("junior", BinaryDecision(decision="NO", confidence=0.8, reasoning="No")),
    }

    node = DecisionFlowNode(
        name="test",
        agents=agents,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            vote_weight_strategy=VoteWeight.SENIORITY,
        ),
    )

    weights = node._get_vote_weights()

    # First agent (senior) should have weight 1.0, second (junior) weight 0.5
    assert weights["senior"] == 1.0
    assert weights["junior"] == 0.5


# =============================================================================
# Test Prompt Building
# =============================================================================


def test_build_decision_prompt():
    """Test decision prompt building."""
    agent = MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))

    node = DecisionFlowNode(
        name="test",
        agents={"agent1": agent},
        config=DecisionNodeConfig(mode=DecisionMode.CIO, decision_type=DecisionType.BINARY),
    )

    ctx = {"user_id": "123", "session_id": "abc"}
    prompt = node._build_decision_prompt("Is this admin?", ctx)

    assert "Is this admin?" in prompt
    assert "user_id" in prompt
    assert "session_id" in prompt


def test_build_revision_prompt():
    """Test revision prompt building for consensus mode."""
    agent = MockAgent("agent1", BinaryDecision(decision="YES", confidence=0.9, reasoning="Yes"))

    node = DecisionFlowNode(
        name="test",
        agents={"agent1": agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CONSENSUS,
            decision_type=DecisionType.BINARY,
            coordinator_agent_name="agent1",
            cross_pollination_rounds=2,
        ),
    )

    other_votes = {
        "agent2": {"decision": "NO", "confidence": 0.8, "reasoning": "Too risky"},
    }

    prompt = node._build_revision_prompt("Original question", other_votes, 1)

    assert "Original question" in prompt
    assert "agent2" in prompt
    assert "NO" in prompt
    assert "Round 1 of 2" in prompt
