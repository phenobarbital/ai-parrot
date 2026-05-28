"""Unit tests for DecisionNode, InteractiveDecisionNode, SynthesisNode — FEAT-163 TASK-1066.

Tests verify:
- Each class is registered in NODE_REGISTRY under the correct key.
- Each class is a frozen Pydantic Node subclass.
- FSM is auto-created on construction.
- Frozen enforcement (field reassignment raises).
- SynthesisNode.execute() returns a string.
- DecisionNode.execute() returns a DecisionResult (mocked internal legacy).
- InteractiveDecisionNode.execute() is present and callable.
"""
import pytest
from pydantic import ValidationError
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.bots.flows.flow import (
    NODE_REGISTRY,
    DecisionNode,
    InteractiveDecisionNode,
    SynthesisNode,
)
from parrot.bots.flows.flow.nodes import (
    DecisionMode,
    DecisionNodeConfig,
    DecisionResult,
    DecisionType,
)
from parrot.bots.flows.core.fsm import AgentTaskMachine


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def decision_config() -> DecisionNodeConfig:
    """Minimal DecisionNodeConfig for testing (CIO mode, BINARY type)."""
    return DecisionNodeConfig(
        mode=DecisionMode.CIO,
        decision_type=DecisionType.BINARY,
    )


@pytest.fixture
def stub_ctx():
    """Minimal FlowContext stub."""

    class Ctx:
        initial_task: str = "test task"
        synthesis_client = None

    return Ctx()


@pytest.fixture
def stub_ctx_with_synthesis():
    """Minimal FlowContext stub with synthesis_client."""

    class Ctx:
        initial_task: str = "test task"

    ctx = Ctx()
    response = MagicMock()
    response.content = "synthesized summary"
    client = AsyncMock()
    client.ask = AsyncMock(return_value=response)
    ctx.synthesis_client = client  # type: ignore[attr-defined]
    return ctx


@pytest.fixture
def deps_stub() -> dict:
    return {"dep_a": "result from A", "dep_b": "result from B"}


# ---------------------------------------------------------------------------
# NODE_REGISTRY
# ---------------------------------------------------------------------------


class TestNodeRegistryForSubclasses:
    def test_decision_registered(self) -> None:
        assert NODE_REGISTRY["decision"] is DecisionNode

    def test_interactive_decision_registered(self) -> None:
        assert NODE_REGISTRY["interactive_decision"] is InteractiveDecisionNode

    def test_synthesis_registered(self) -> None:
        assert NODE_REGISTRY["synthesis"] is SynthesisNode


# ---------------------------------------------------------------------------
# DecisionNode
# ---------------------------------------------------------------------------


class TestDecisionNode:
    def test_is_pydantic_node_subclass(self) -> None:
        from pydantic import BaseModel
        from parrot.bots.flows.core.node import Node

        assert issubclass(DecisionNode, BaseModel)
        assert issubclass(DecisionNode, Node)

    def test_construction(self, decision_config: DecisionNodeConfig) -> None:
        node = DecisionNode(node_id="d1", decision_config=decision_config)
        assert node.node_id == "d1"
        assert node.name == "d1"

    def test_fsm_auto_created(self, decision_config: DecisionNodeConfig) -> None:
        node = DecisionNode(node_id="d1", decision_config=decision_config)
        assert node.fsm is not None
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_frozen_blocks_reassignment(self, decision_config: DecisionNodeConfig) -> None:
        node = DecisionNode(node_id="d1", decision_config=decision_config)
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            node.node_id = "d2"  # type: ignore[misc]

    def test_fsm_can_mutate(self, decision_config: DecisionNodeConfig) -> None:
        """Frozen model allows mutation of nested object (FSM) — B-lite contract.

        The FSM starts in idle state; schedule() moves it to ready.
        """
        node = DecisionNode(node_id="d1", decision_config=decision_config)
        node.fsm.schedule()  # idle → ready (should not raise)

    async def test_execute_returns_decision_result(
        self, decision_config: DecisionNodeConfig, stub_ctx: object, deps_stub: dict
    ) -> None:
        """Patch the legacy DecisionFlowNode.ask() to return a minimal DecisionResult."""
        fake_result = DecisionResult(
            mode=DecisionMode.CIO,
            final_decision="YES",
            confidence=0.9,
        )
        node = DecisionNode(node_id="d1", decision_config=decision_config)

        with patch(
            "parrot.bots.flows.flow.flow.DecisionFlowNode"
        ) as MockDecisionFlowNode:
            instance = AsyncMock()
            instance.ask = AsyncMock(return_value=fake_result)
            MockDecisionFlowNode.return_value = instance

            result = await node.execute(stub_ctx, deps_stub)

        assert isinstance(result, DecisionResult)
        assert result.final_decision == "YES"


# ---------------------------------------------------------------------------
# InteractiveDecisionNode
# ---------------------------------------------------------------------------


class TestInteractiveDecisionNode:
    def test_is_pydantic_node_subclass(self) -> None:
        from pydantic import BaseModel
        from parrot.bots.flows.core.node import Node

        assert issubclass(InteractiveDecisionNode, BaseModel)
        assert issubclass(InteractiveDecisionNode, Node)

    def test_registered(self) -> None:
        assert NODE_REGISTRY["interactive_decision"] is InteractiveDecisionNode

    def test_construction(self) -> None:
        node = InteractiveDecisionNode(
            node_id="i1",
            question="Approve?",
            options=["yes", "no"],
        )
        assert node.node_id == "i1"
        assert node.name == "i1"
        assert node.question == "Approve?"
        assert node.options == ["yes", "no"]

    def test_fsm_auto_created(self) -> None:
        node = InteractiveDecisionNode(
            node_id="i1",
            question="Q?",
            options=["a", "b"],
        )
        assert node.fsm is not None
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_has_execute_method(self) -> None:
        node = InteractiveDecisionNode(
            node_id="i1",
            question="Q?",
            options=["a", "b"],
        )
        assert callable(node.execute)


# ---------------------------------------------------------------------------
# SynthesisNode
# ---------------------------------------------------------------------------


class TestSynthesisNode:
    def test_is_pydantic_node_subclass(self) -> None:
        from pydantic import BaseModel
        from parrot.bots.flows.core.node import Node

        assert issubclass(SynthesisNode, BaseModel)
        assert issubclass(SynthesisNode, Node)

    def test_registered(self) -> None:
        assert NODE_REGISTRY["synthesis"] is SynthesisNode

    def test_construction(self) -> None:
        node = SynthesisNode(node_id="syn1")
        assert node.node_id == "syn1"
        assert node.name == "syn1"

    def test_fsm_auto_created(self) -> None:
        node = SynthesisNode(node_id="syn1")
        assert node.fsm is not None
        assert isinstance(node.fsm, AgentTaskMachine)

    def test_frozen_blocks_reassignment(self) -> None:
        node = SynthesisNode(node_id="syn1")
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            node.node_id = "syn2"  # type: ignore[misc]

    async def test_execute_returns_string(
        self, stub_ctx_with_synthesis: object, deps_stub: dict
    ) -> None:
        node = SynthesisNode(node_id="syn1")
        out = await node.execute(stub_ctx_with_synthesis, deps_stub)
        assert isinstance(out, str)
        assert out  # non-empty

    async def test_execute_raises_without_synthesis_client(
        self, stub_ctx: object, deps_stub: dict
    ) -> None:
        node = SynthesisNode(node_id="syn1")
        stub_ctx.synthesis_client = None  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="No synthesis client"):
            await node.execute(stub_ctx, deps_stub)
