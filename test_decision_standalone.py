"""Standalone test of DecisionFlowNode without full workflow integration.

This demonstrates that the DecisionFlowNode component works correctly
for all three modes without requiring full workflow integration.
"""
import asyncio

from parrot.bots.orchestration.decision_node import (
    BinaryDecision,
    DecisionFlowNode,
    DecisionMode,
    DecisionNodeConfig,
    DecisionType,
    VoteWeight,
)


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, name: str, decision: str, confidence: float = 0.9):
        self.name = name
        self.is_configured = True
        self.tool_manager = None
        self._decision = decision
        self._confidence = confidence

    async def ask(self, question: str = "", **kwargs):
        """Return mock decision."""
        if "structured_output" in kwargs:
            schema = kwargs["structured_output"]
            return schema(
                decision=self._decision,
                confidence=self._confidence,
                reasoning=f"{self.name} says {self._decision}"
            )
        return f"{self._decision}"


async def main():
    """Run all DecisionFlowNode tests."""
    print("\n" + "=" * 80)
    print("DecisionFlowNode Standalone Tests")
    print("=" * 80)

    # Test 1: CIO Mode - YES decision
    print("\n" + "-" * 80)
    print("TEST 1: CIO Mode - Admin Approval (YES)")
    print("-" * 80)

    admin_agent = MockAgent("AdminChecker", "YES", 0.95)
    admin_gate = DecisionFlowNode(
        name="admin_gate",
        agents={"checker": admin_agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
        ),
    )

    result1 = await admin_gate.ask("Is this user an admin?")
    print(f"✓ Decision: {result1.final_decision}")
    print(f"✓ Confidence: {result1.confidence}")
    print(f"✓ Mode: {result1.mode}")
    assert result1.final_decision == "YES"
    assert result1.confidence == 0.95

    # Test 2: CIO Mode - NO decision
    print("\n" + "-" * 80)
    print("TEST 2: CIO Mode - Regular User (NO)")
    print("-" * 80)

    regular_agent = MockAgent("RegularChecker", "NO", 0.88)
    regular_gate = DecisionFlowNode(
        name="regular_gate",
        agents={"checker": regular_agent},
        config=DecisionNodeConfig(
            mode=DecisionMode.CIO,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
        ),
    )

    result2 = await regular_gate.ask("Is this user an admin?")
    print(f"✓ Decision: {result2.final_decision}")
    print(f"✓ Confidence: {result2.confidence}")
    assert result2.final_decision == "NO"
    assert result2.confidence == 0.88

    # Test 3: Ballot Mode - Majority YES
    print("\n" + "-" * 80)
    print("TEST 3: Ballot Mode - Majority Vote (3 YES, 2 NO)")
    print("-" * 80)

    committee = {
        "agent1": MockAgent("Agent1", "YES", 0.9),
        "agent2": MockAgent("Agent2", "YES", 0.85),
        "agent3": MockAgent("Agent3", "YES", 0.92),
        "agent4": MockAgent("Agent4", "NO", 0.75),
        "agent5": MockAgent("Agent5", "NO", 0.70),
    }

    ballot_node = DecisionFlowNode(
        name="committee_vote",
        agents=committee,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            vote_weight_strategy=VoteWeight.EQUAL,
        ),
    )

    result3 = await ballot_node.ask("Should we approve?")
    print(f"✓ Decision: {result3.final_decision}")
    print(f"✓ Consensus: {result3.consensus_level}")
    print(f"✓ Vote Distribution: {result3.vote_distribution}")
    print(f"✓ Votes: {result3.votes}")
    assert result3.final_decision == "YES"
    assert result3.consensus_level == "MAJORITY"
    assert result3.vote_distribution["YES"] == 3
    assert result3.vote_distribution["NO"] == 2

    # Test 4: Ballot Mode with Custom Weights
    print("\n" + "-" * 80)
    print("TEST 4: Ballot Mode - Custom Weights (YES wins despite being minority)")
    print("-" * 80)

    weighted_committee = {
        "risk_lead": MockAgent("RiskLead", "YES", 0.95),
        "analyst1": MockAgent("Analyst1", "NO", 0.80),
        "analyst2": MockAgent("Analyst2", "NO", 0.85),
    }

    weighted_ballot = DecisionFlowNode(
        name="weighted_vote",
        agents=weighted_committee,
        config=DecisionNodeConfig(
            mode=DecisionMode.BALLOT,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            vote_weight_strategy=VoteWeight.CUSTOM,
            custom_weights={"risk_lead": 3.0, "analyst1": 1.0, "analyst2": 1.0},
        ),
    )

    result4 = await weighted_ballot.ask("High risk decision?")
    print(f"✓ Decision: {result4.final_decision} (weighted)")
    print(f"✓ Vote Distribution: {result4.vote_distribution}")
    assert result4.final_decision == "YES"  # YES wins with 3.0 weight vs 2.0 combined

    # Test 5: Consensus Mode
    print("\n" + "-" * 80)
    print("TEST 5: Consensus Mode - Deliberative Decision")
    print("-" * 80)

    consensus_agents = {
        "analyst1": MockAgent("Analyst1", "YES", 0.85),
        "analyst2": MockAgent("Analyst2", "NO", 0.80),
        "coordinator": MockAgent("Coordinator", "YES", 0.95),
    }

    consensus_node = DecisionFlowNode(
        name="consensus_decision",
        agents=consensus_agents,
        config=DecisionNodeConfig(
            mode=DecisionMode.CONSENSUS,
            decision_type=DecisionType.BINARY,
            decision_schema=BinaryDecision,
            coordinator_agent_name="coordinator",
            cross_pollination_rounds=1,
        ),
    )

    result5 = await consensus_node.ask("Strategic decision?")
    print(f"✓ Decision: {result5.final_decision}")
    print(f"✓ Confidence: {result5.confidence}")
    print(f"✓ Coordinator: {result5.metadata.get('coordinator')}")
    assert result5.final_decision == "YES"
    assert result5.confidence == 0.95
    assert result5.metadata["coordinator"] == "coordinator"

    # Test 6: Use in predicates (as would be used in AgentsFlow)
    print("\n" + "-" * 80)
    print("TEST 6: Decision Results in Predicates (for routing)")
    print("-" * 80)

    def route_to_admin_path(decision_result):
        """Predicate for admin routing."""
        from parrot.bots.orchestration.decision_node import DecisionResult
        return isinstance(decision_result, DecisionResult) and decision_result.final_decision == "YES"

    def route_to_simple_path(decision_result):
        """Predicate for simple routing."""
        from parrot.bots.orchestration.decision_node import DecisionResult
        return isinstance(decision_result, DecisionResult) and decision_result.final_decision == "NO"

    # Test with result1 (YES)
    assert route_to_admin_path(result1) is True
    assert route_to_simple_path(result1) is False
    print("✓ YES decision routes to admin path")

    # Test with result2 (NO)
    assert route_to_admin_path(result2) is False
    assert route_to_simple_path(result2) is True
    print("✓ NO decision routes to simple path")

    print("\n" + "=" * 80)
    print("✓✓✓ ALL TESTS PASSED! ✓✓✓")
    print("=" * 80)
    print("\nDecisionFlowNode component verified:")
    print("  ✓ CIO Mode (single decision maker)")
    print("  ✓ Ballot Mode (multi-agent voting)")
    print("  ✓ Custom vote weighting")
    print("  ✓ Consensus Mode (coordinator synthesis)")
    print("  ✓ Result objects work in predicates for routing")
    print("\nThe DecisionFlowNode is ready for production use!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
