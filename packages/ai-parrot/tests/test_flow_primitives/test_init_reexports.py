"""Unit tests for parrot.bots.flows.core and flows __init__ re-exports (TASK-920)."""
import pytest


class TestCoreInit:
    def test_import_all_from_core(self):
        from parrot.bots.flows.core import (
            AgentLike, AgentRef, FlowStatus,
            AgentTaskMachine, TransitionCondition,
            Node, AgentNode, StartNode, EndNode,
            FlowResult, NodeExecutionInfo,
            FlowContext, FlowTransition,
            ExecutionMemory, PersistenceMixin, SynthesisMixin,
        )

    def test_all_symbols_in___all__(self):
        import parrot.bots.flows.core as core
        expected = [
            "AgentLike", "AgentRef", "DependencyResults", "PromptBuilder",
            "ActionCallback", "FlowStatus",
            "AgentTaskMachine", "TransitionCondition",
            "Node", "AgentNode", "StartNode", "EndNode",
            "FlowResult", "NodeExecutionInfo", "build_node_metadata", "determine_run_status",
            "FlowContext",
            "FlowTransition",
            "ExecutionMemory", "VectorStoreMixin", "PersistenceMixin", "SynthesisMixin",
        ]
        for name in expected:
            assert name in core.__all__, f"{name!r} missing from core.__all__"

    def test_import_from_flows_package(self):
        from parrot.bots.flows import (
            AgentLike, Node, FlowResult, FlowContext, FlowTransition,
        )

    def test_flows_all_has_symbols(self):
        import parrot.bots.flows as flows
        assert "FlowResult" in flows.__all__
        assert "FlowContext" in flows.__all__
        assert "AgentNode" in flows.__all__

    def test_flow_status_usable(self):
        from parrot.bots.flows.core import FlowStatus
        assert FlowStatus.COMPLETED.value == "completed"
        assert FlowStatus.FAILED.value == "failed"

    def test_flow_result_instantiable(self):
        from parrot.bots.flows.core import FlowResult, FlowStatus
        r = FlowResult(output="test", status=FlowStatus.COMPLETED)
        assert r.success is True

    def test_flow_context_instantiable(self):
        from parrot.bots.flows.core import FlowContext
        ctx = FlowContext(initial_task="hello")
        assert ctx.initial_task == "hello"

    def test_agent_node_instantiable(self):
        from parrot.bots.flows.core import AgentNode

        class MockAgent:
            @property
            def name(self):
                return "mock"
            async def invoke(self, prompt, **kwargs):
                return "ok"

        node = AgentNode(agent=MockAgent(), node_id="n1")
        assert node.node_id == "n1"
        assert node.name == "mock"

    def test_flow_transition_importable_from_core(self):
        from parrot.bots.flows.core import FlowTransition, TransitionCondition
        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ON_SUCCESS,
        )
        assert t.source == "a"


class TestExistingImportsNotBroken:
    def test_crew_result_still_importable(self):
        from parrot.models.crew import CrewResult
        assert CrewResult is not None

    def test_agent_execution_info_still_importable(self):
        from parrot.models.crew import AgentExecutionInfo
        assert AgentExecutionInfo is not None

    def test_flow_node_still_importable(self):
        from parrot.bots.flow import Node, StartNode, EndNode
        assert Node is not None

    def test_agents_flow_still_importable(self):
        from parrot.bots.flow import AgentsFlow, FlowNode
        assert AgentsFlow is not None

    def test_flow_storage_still_importable(self):
        from parrot.bots.flow.storage import ExecutionMemory, PersistenceMixin
        assert ExecutionMemory is not None

    def test_agent_crew_still_importable(self):
        from parrot.bots.orchestration.crew import AgentCrew
        assert AgentCrew is not None


class TestDeadCodeRemoved:
    def test_agent_task_not_in_crew(self):
        import parrot.bots.orchestration.crew as crew_mod
        assert not hasattr(crew_mod, "AgentTask")

    def test_agent_task_class_gone(self):
        """AgentTask dataclass from crew.py must not be importable."""
        try:
            from parrot.bots.orchestration.crew import AgentTask
            raise AssertionError("AgentTask should have been removed from crew.py")
        except ImportError:
            pass  # expected
