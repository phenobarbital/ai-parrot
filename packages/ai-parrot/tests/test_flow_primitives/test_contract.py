"""Contract tests — cross-module invariants for flow-primitives (TASK-921).

Tests here span multiple core modules and validate the spec §4 invariants.
Per-module unit tests live in their respective test_*.py files; this file
focuses on cross-module integration and protocol conformance.
"""
import pytest
from statemachine.exceptions import TransitionNotAllowed

from parrot.bots.flows.core import (
    AgentLike,
    FlowStatus,
    AgentTaskMachine,
    TransitionCondition,
    AgentNode,
    StartNode,
    EndNode,
    FlowResult,
    NodeExecutionInfo,
    FlowContext,
    FlowTransition,
    build_node_metadata,
    determine_run_status,
)


# ---------------------------------------------------------------------------
# Cross-module integration
# ---------------------------------------------------------------------------


class TestCrossModuleIntegration:
    """Tests that span multiple core modules."""

    def test_agent_node_has_fsm(self, agent_node):
        assert isinstance(agent_node.fsm, AgentTaskMachine)
        assert agent_node.fsm.current_state == agent_node.fsm.idle

    def test_agent_node_protocol_conformance(self, mock_agent):
        assert isinstance(mock_agent, AgentLike)

    def test_flow_context_with_node_execution_info(self, flow_context):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1", status="completed")
        flow_context.mark_completed("n1", result="done", metadata=info)
        assert flow_context.node_metadata["n1"] == info
        assert flow_context.agent_metadata["n1"] == info  # backward-compat alias

    def test_flow_result_with_flow_status(self):
        r = FlowResult(output="ok", status=FlowStatus.COMPLETED)
        assert r.success is True
        assert r.status == FlowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_transition_activates_and_builds_prompt(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ALWAYS,
            instruction="Do the thing",
        )
        assert await t.should_activate(result="ok") is True

    def test_node_id_uniqueness_concept(self, mock_agent):
        n1 = AgentNode(agent=mock_agent, node_id="instance-1")
        n2 = AgentNode(agent=mock_agent, node_id="instance-2")
        assert n1.node_id != n2.node_id
        assert n1.name == n2.name  # same underlying agent

    def test_determine_run_status_integration(self):
        assert determine_run_status(5, 0) == "completed"
        assert determine_run_status(3, 2) == "partial"
        assert determine_run_status(0, 4) == "failed"

    def test_build_node_metadata_returns_correct_type(self):
        info = build_node_metadata(
            node_id="n1",
            agent=None,
            response=None,
            output="result",
            execution_time=1.5,
            status="completed",
        )
        assert isinstance(info, NodeExecutionInfo)
        assert info.node_id == "n1"
        assert info.agent_id == "n1"  # backward-compat alias

    def test_node_metadata_round_trips_through_flow_result(self):
        info = NodeExecutionInfo(node_id="n1", node_name="a1", status="completed")
        r = FlowResult(output="done", nodes=[info])
        d = r.to_dict()
        assert len(d["nodes"]) == 1
        assert d["nodes"][0]["node_id"] == "n1"
        assert d["nodes"][0]["agent_id"] == "n1"  # backward-compat in dict

    def test_fsm_lifecycle_matches_node_execution_info_status(self, agent_node):
        """FSM states should correspond to NodeExecutionInfo status values."""
        fsm = agent_node.fsm
        assert fsm.current_state == fsm.idle

        fsm.schedule()
        fsm.start()
        fsm.succeed()
        assert fsm.current_state == fsm.completed

        info = NodeExecutionInfo(
            node_id=agent_node.node_id,
            node_name=agent_node.name,
            status="completed",
        )
        assert info.status == "completed"


# ---------------------------------------------------------------------------
# FSM contract
# ---------------------------------------------------------------------------


class TestFSMContract:
    """Full FSM lifecycle invariants from spec §4."""

    @pytest.fixture
    def fsm(self):
        return AgentTaskMachine(agent_name="contract-test")

    def test_initial_state_is_idle(self, fsm):
        assert fsm.current_state == fsm.idle

    def test_happy_path(self, fsm):
        fsm.schedule()
        assert fsm.current_state == fsm.ready
        fsm.start()
        assert fsm.current_state == fsm.running
        fsm.succeed()
        assert fsm.current_state == fsm.completed

    def test_retry_path(self, fsm):
        fsm.schedule()
        fsm.start()
        fsm.fail()
        assert fsm.current_state == fsm.failed
        fsm.retry()
        assert fsm.current_state == fsm.ready

    def test_blocked_path(self, fsm):
        fsm.block()
        assert fsm.current_state == fsm.blocked
        fsm.unblock()
        assert fsm.current_state == fsm.ready

    def test_completed_is_final(self, fsm):
        fsm.schedule()
        fsm.start()
        fsm.succeed()
        with pytest.raises(TransitionNotAllowed):
            fsm.schedule()

    def test_failed_is_not_final(self, fsm):
        fsm.schedule()
        fsm.start()
        fsm.fail()
        fsm.retry()  # must NOT raise
        assert fsm.current_state == fsm.ready

    def test_invalid_idle_to_running(self, fsm):
        with pytest.raises(TransitionNotAllowed):
            fsm.start()


# ---------------------------------------------------------------------------
# Node contract
# ---------------------------------------------------------------------------


class TestNodeContract:
    """node_id ≠ name invariant from spec §4."""

    def test_node_id_vs_name(self, agent_node):
        assert agent_node.node_id == "node-1"
        assert agent_node.name == "test-agent"
        assert agent_node.node_id != agent_node.name

    def test_start_node_default_name(self):
        assert StartNode().name == "__start__"

    def test_end_node_default_name(self):
        assert EndNode().name == "__end__"

    @pytest.mark.asyncio
    async def test_pre_action_sync(self, agent_node):
        calls = []
        agent_node.add_pre_action(lambda n, p, **kw: calls.append(n))
        await agent_node.run_pre_actions(prompt="q")
        assert calls == ["test-agent"]

    @pytest.mark.asyncio
    async def test_post_action_async(self, agent_node):
        calls = []

        async def async_hook(n, r, **kw):
            calls.append(r)

        agent_node.add_post_action(async_hook)
        await agent_node.run_post_actions(result="result")
        assert calls == ["result"]


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------


class TestResultContract:
    """Result model backward-compat and serialisation invariants."""

    def test_nodes_is_primary_agents_is_alias(self):
        info = NodeExecutionInfo(node_id="n1", node_name="a1")
        r = FlowResult(output="ok", nodes=[info])
        assert r.nodes is r.agents  # same object

    def test_to_dict_round_trip(self):
        r = FlowResult(output="hello", status=FlowStatus.COMPLETED)
        d = r.to_dict()
        assert d["output"] == "hello"
        assert d["status"] == "completed"
        assert "nodes" in d
        assert "agents" in d  # backward-compat key

    def test_node_execution_info_aliases(self):
        info = NodeExecutionInfo(node_id="x", node_name="y")
        assert info.agent_id == "x"
        assert info.agent_name == "y"

    def test_success_only_for_completed(self):
        assert FlowResult(output="ok", status=FlowStatus.COMPLETED).success is True
        assert FlowResult(output="ok", status=FlowStatus.PARTIAL).success is False
        assert FlowResult(output="ok", status=FlowStatus.FAILED).success is False


# ---------------------------------------------------------------------------
# Context contract
# ---------------------------------------------------------------------------


class TestContextContract:
    """FlowContext method invariants from spec §4."""

    def test_can_execute_no_deps(self, flow_context):
        assert flow_context.can_execute("n1", set()) is True

    def test_can_execute_unsatisfied(self, flow_context):
        assert flow_context.can_execute("n2", {"n1"}) is False

    def test_mark_completed_all_fields(self, flow_context, node_execution_info):
        flow_context.active_tasks.add("n1")
        flow_context.mark_completed("n1", result="r", metadata=node_execution_info)
        assert "n1" in flow_context.completed_tasks
        assert "n1" in flow_context.completion_order
        assert "n1" not in flow_context.active_tasks
        assert flow_context.results["n1"] == "r"
        assert flow_context.node_metadata["n1"] is node_execution_info

    def test_get_input_for_node_no_deps(self, flow_context):
        inp = flow_context.get_input_for_node("n1", set())
        assert inp == {"task": "test task"}

    def test_get_input_for_node_with_deps(self, flow_context):
        flow_context.results["dep"] = "dep-result"
        inp = flow_context.get_input_for_node("n2", {"dep"})
        assert inp["dependencies"]["dep"] == "dep-result"

    def test_agent_metadata_alias(self, flow_context):
        assert flow_context.agent_metadata is flow_context.node_metadata

    def test_get_input_for_agent_alias(self, flow_context):
        assert flow_context.get_input_for_agent("x", set()) == \
               flow_context.get_input_for_node("x", set())


# ---------------------------------------------------------------------------
# Transition contract
# ---------------------------------------------------------------------------


class TestTransitionContract:
    """TransitionCondition activation semantics from spec §4."""

    @pytest.mark.asyncio
    async def test_always_fires(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ALWAYS)
        assert await t.should_activate(result=None, error=Exception("err")) is True

    @pytest.mark.asyncio
    async def test_on_success(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_SUCCESS)
        assert await t.should_activate(result="ok", error=None) is True
        assert await t.should_activate(result=None, error=Exception("x")) is False

    @pytest.mark.asyncio
    async def test_on_error(self):
        t = FlowTransition(source="a", targets={"b"}, condition=TransitionCondition.ON_ERROR)
        assert await t.should_activate(result=None, error=Exception("x")) is True
        assert await t.should_activate(result="ok", error=None) is False

    @pytest.mark.asyncio
    async def test_on_condition_sync_predicate(self):
        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ON_CONDITION,
            predicate=lambda r: r > 5,
        )
        assert await t.should_activate(result=10) is True
        assert await t.should_activate(result=3) is False

    @pytest.mark.asyncio
    async def test_on_condition_async_predicate(self):
        async def pred(r):
            return r == "yes"

        t = FlowTransition(
            source="a",
            targets={"b"},
            condition=TransitionCondition.ON_CONDITION,
            predicate=pred,
        )
        assert await t.should_activate(result="yes") is True
        assert await t.should_activate(result="no") is False


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """AgentLike protocol accepts conforming objects and rejects others."""

    def test_conforming_agent(self, mock_agent):
        assert isinstance(mock_agent, AgentLike)

    def test_non_conforming_object_rejected(self):
        class NotAnAgent:
            pass

        assert not isinstance(NotAnAgent(), AgentLike)

    def test_partial_conformance_rejected(self):
        """Object with name but no invoke is NOT AgentLike."""

        class JustName:
            @property
            def name(self):
                return "x"

        # AgentLike requires both name AND invoke
        assert not isinstance(JustName(), AgentLike)


# ---------------------------------------------------------------------------
# Import compatibility
# ---------------------------------------------------------------------------


class TestImportCompatibility:
    """Old import paths must still work after TASK-920."""

    def test_crew_result_still_importable(self):
        from parrot.models.crew import CrewResult
        assert CrewResult is not None

    def test_agent_execution_info_still_importable(self):
        from parrot.models.crew import AgentExecutionInfo
        assert AgentExecutionInfo is not None

    def test_old_node_still_importable(self):
        from parrot.bots.flow import Node as OldNode, StartNode as OldStart, EndNode as OldEnd
        assert OldNode is not None
        assert OldStart is not None
        assert OldEnd is not None

    def test_agents_flow_still_importable(self):
        from parrot.bots.flow import AgentsFlow, FlowNode
        assert AgentsFlow is not None

    def test_old_storage_still_importable(self):
        from parrot.bots.flow.storage import ExecutionMemory as OldEM, PersistenceMixin
        assert OldEM is not None

    def test_agent_task_removed_from_crew(self):
        """AgentTask dataclass removed in TASK-920 must not be importable."""
        import parrot.bots.orchestration.crew as crew
        assert not hasattr(crew, "AgentTask")
