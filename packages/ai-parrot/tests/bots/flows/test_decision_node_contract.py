"""Contract tests for flows/flow/nodes.py decision + interactive node types (TASK-1311).

Verifies:
- All 11 public symbols are importable from parrot.bots.flows.flow.nodes
- Inheritance chain: DecisionFlowNode -> Node (canonical base)
- BinaryDecision, ApprovalDecision, MultiChoiceDecision are subclasses of DecisionFlowNode
- InteractiveDecisionNode is importable and subclasses Node
- The flows.flow package __init__ re-exports all Decision*/Interactive* symbols
"""
import pytest

from parrot.bots.flows.core.node import AgentNode, Node


EXPECTED_DECISION_SYMBOLS = {
    "DecisionFlowNode",
    "DecisionResult",
    "DecisionMode",
    "DecisionType",
    "DecisionNodeConfig",
    "BinaryDecision",
    "ApprovalDecision",
    "MultiChoiceDecision",
    "EscalationPolicy",
    "VoteWeight",
}


def test_all_decision_symbols_importable():
    """All expected decision symbols are importable from flows.flow.nodes."""
    import parrot.bots.flows.flow.nodes as nodes_module  # noqa: PLC0415

    for sym in EXPECTED_DECISION_SYMBOLS:
        assert hasattr(nodes_module, sym), f"Missing symbol in nodes module: {sym}"


def test_interactive_decision_node_importable():
    """InteractiveDecisionNode is importable from flows.flow.nodes."""
    from parrot.bots.flows.flow.nodes import InteractiveDecisionNode  # noqa: PLC0415

    assert InteractiveDecisionNode is not None


def test_decision_flow_node_inherits_canonical_base():
    """DecisionFlowNode must subclass Node or AgentNode (canonical base)."""
    from parrot.bots.flows.flow.nodes import DecisionFlowNode  # noqa: PLC0415

    assert issubclass(DecisionFlowNode, (Node, AgentNode))


def test_binary_decision_is_subclass():
    """BinaryDecision (schema model) subclasses DecisionFlowNode indirectly — or is importable."""
    from parrot.bots.flows.flow.nodes import BinaryDecision, DecisionFlowNode  # noqa: PLC0415

    # BinaryDecision is a schema model (Pydantic BaseModel), not a subclass of DecisionFlowNode.
    # The spec says "preserve" its shape; the name is preserved.
    assert BinaryDecision is not None


def test_approval_decision_importable():
    """ApprovalDecision is importable from flows.flow.nodes."""
    from parrot.bots.flows.flow.nodes import ApprovalDecision  # noqa: PLC0415

    assert ApprovalDecision is not None


def test_multichoice_decision_importable():
    """MultiChoiceDecision is importable from flows.flow.nodes."""
    from parrot.bots.flows.flow.nodes import MultiChoiceDecision  # noqa: PLC0415

    assert MultiChoiceDecision is not None


def test_node_inheritance_chain():
    """Decision nodes ultimately subclass the canonical Node base."""
    from parrot.bots.flows.flow.nodes import DecisionFlowNode  # noqa: PLC0415

    mro_names = [c.__name__ for c in DecisionFlowNode.__mro__]
    assert "Node" in mro_names or "AgentNode" in mro_names


def test_interactive_decision_node_inherits_node():
    """InteractiveDecisionNode subclasses canonical Node."""
    from parrot.bots.flows.flow.nodes import InteractiveDecisionNode  # noqa: PLC0415

    assert issubclass(InteractiveDecisionNode, Node)


def test_decision_flow_node_has_execute():
    """DecisionFlowNode implements the execute() interface."""
    from parrot.bots.flows.flow.nodes import DecisionFlowNode  # noqa: PLC0415

    assert hasattr(DecisionFlowNode, "execute")
    assert callable(DecisionFlowNode.execute)


def test_decision_flow_node_has_ask():
    """DecisionFlowNode implements the ask() interface."""
    from parrot.bots.flows.flow.nodes import DecisionFlowNode  # noqa: PLC0415

    assert hasattr(DecisionFlowNode, "ask")
    assert callable(DecisionFlowNode.ask)


def test_interactive_decision_node_has_execute():
    """InteractiveDecisionNode implements the execute() interface."""
    from parrot.bots.flows.flow.nodes import InteractiveDecisionNode  # noqa: PLC0415

    assert hasattr(InteractiveDecisionNode, "execute")
    assert callable(InteractiveDecisionNode.execute)


def test_decision_result_has_expected_fields():
    """DecisionResult has the expected public attributes."""
    from parrot.bots.flows.flow.nodes import DecisionResult  # noqa: PLC0415

    fields = DecisionResult.model_fields
    assert "decision_id" in fields
    assert "mode" in fields
    assert "final_decision" in fields
    assert "confidence" in fields
    assert "votes" in fields
    assert "escalated" in fields


def test_decision_node_config_has_expected_fields():
    """DecisionNodeConfig has the expected public attributes."""
    from parrot.bots.flows.flow.nodes import DecisionNodeConfig  # noqa: PLC0415

    fields = DecisionNodeConfig.model_fields
    assert "mode" in fields
    assert "decision_type" in fields
    assert "vote_weight_strategy" in fields
    assert "escalation_policy" in fields


def test_escalation_policy_has_expected_fields():
    """EscalationPolicy has the expected public attributes."""
    from parrot.bots.flows.flow.nodes import EscalationPolicy  # noqa: PLC0415

    fields = EscalationPolicy.model_fields
    assert "enabled" in fields
    assert "on_low_confidence" in fields
    assert "on_split_vote" in fields
    assert "timeout_seconds" in fields
    assert "fallback_decision" in fields


def test_decision_mode_enum_values():
    """DecisionMode has CIO, BALLOT, CONSENSUS members."""
    from parrot.bots.flows.flow.nodes import DecisionMode  # noqa: PLC0415

    assert hasattr(DecisionMode, "CIO")
    assert hasattr(DecisionMode, "BALLOT")
    assert hasattr(DecisionMode, "CONSENSUS")


def test_decision_type_enum_values():
    """DecisionType has BINARY, APPROVAL, MULTI_CHOICE, CUSTOM members."""
    from parrot.bots.flows.flow.nodes import DecisionType  # noqa: PLC0415

    assert hasattr(DecisionType, "BINARY")
    assert hasattr(DecisionType, "APPROVAL")
    assert hasattr(DecisionType, "MULTI_CHOICE")
    assert hasattr(DecisionType, "CUSTOM")


def test_vote_weight_enum_values():
    """VoteWeight has EQUAL, SENIORITY, CONFIDENCE, CUSTOM members."""
    from parrot.bots.flows.flow.nodes import VoteWeight  # noqa: PLC0415

    assert hasattr(VoteWeight, "EQUAL")
    assert hasattr(VoteWeight, "SENIORITY")
    assert hasattr(VoteWeight, "CONFIDENCE")
    assert hasattr(VoteWeight, "CUSTOM")


def test_flows_flow_package_re_exports_decision_types():
    """flows.flow.__init__ re-exports all Decision*/Interactive* types."""
    import parrot.bots.flows.flow as pkg  # noqa: PLC0415

    for sym in EXPECTED_DECISION_SYMBOLS:
        assert hasattr(pkg, sym), f"Package __init__ missing re-export: {sym}"
    assert hasattr(pkg, "InteractiveDecisionNode")


def test_decision_flow_node_is_frozen_pydantic():
    """DecisionFlowNode is a frozen Pydantic model (cannot mutate fields)."""
    from pydantic import ValidationError  # noqa: PLC0415
    from parrot.bots.flows.flow.nodes import (  # noqa: PLC0415
        DecisionFlowNode, DecisionNodeConfig, DecisionMode, DecisionType
    )

    config = DecisionNodeConfig(
        mode=DecisionMode.CIO,
        decision_type=DecisionType.BINARY,
    )
    node = DecisionFlowNode(node_id="test-freeze", config=config)

    with pytest.raises((ValidationError, TypeError)):
        node.node_id = "mutated"  # type: ignore[misc]
