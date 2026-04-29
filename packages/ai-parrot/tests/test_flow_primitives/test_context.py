"""Unit tests for parrot.bots.flows.core.context (TASK-917)."""
import pytest
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.result import NodeExecutionInfo


class TestFlowContextCanExecute:
    def test_no_deps_can_execute(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.can_execute("node-1", set()) is True

    def test_deps_not_met(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.can_execute("node-2", {"node-1"}) is False

    def test_deps_met(self):
        ctx = FlowContext(initial_task="test")
        ctx.completed_tasks.add("node-1")
        assert ctx.can_execute("node-2", {"node-1"}) is True

    def test_multiple_deps_all_met(self):
        ctx = FlowContext(initial_task="test")
        ctx.completed_tasks.update({"n1", "n2", "n3"})
        assert ctx.can_execute("n4", {"n1", "n2", "n3"}) is True

    def test_multiple_deps_partial_met(self):
        ctx = FlowContext(initial_task="test")
        ctx.completed_tasks.add("n1")
        assert ctx.can_execute("n4", {"n1", "n2"}) is False


class TestFlowContextMarkCompleted:
    def test_updates_tracking(self):
        ctx = FlowContext(initial_task="test")
        ctx.active_tasks.add("node-1")
        info = NodeExecutionInfo(node_id="node-1", node_name="agent-1")
        ctx.mark_completed("node-1", result="done", response=None, metadata=info)
        assert "node-1" in ctx.completed_tasks
        assert "node-1" in ctx.completion_order
        assert "node-1" not in ctx.active_tasks
        assert ctx.results["node-1"] == "done"
        assert ctx.node_metadata["node-1"] == info

    def test_mark_completed_no_result(self):
        ctx = FlowContext(initial_task="test")
        ctx.mark_completed("node-1")
        assert "node-1" in ctx.completed_tasks
        assert "node-1" not in ctx.results

    def test_completion_order_preserved(self):
        ctx = FlowContext(initial_task="test")
        ctx.mark_completed("n1", result="r1")
        ctx.mark_completed("n2", result="r2")
        ctx.mark_completed("n3", result="r3")
        assert ctx.completion_order == ["n1", "n2", "n3"]

    def test_response_stored(self):
        ctx = FlowContext(initial_task="test")
        ctx.mark_completed("node-1", response={"raw": "value"})
        assert ctx.responses["node-1"] == {"raw": "value"}

    def test_removes_from_active_tasks(self):
        ctx = FlowContext(initial_task="test")
        ctx.active_tasks.add("node-1")
        ctx.mark_completed("node-1")
        assert "node-1" not in ctx.active_tasks

    def test_none_result_not_stored(self):
        ctx = FlowContext(initial_task="test")
        ctx.mark_completed("node-1", result=None)
        assert "node-1" not in ctx.results

    def test_none_metadata_not_stored(self):
        ctx = FlowContext(initial_task="test")
        ctx.mark_completed("node-1", metadata=None)
        assert "node-1" not in ctx.node_metadata


class TestFlowContextGetInput:
    def test_no_deps_returns_initial_task(self):
        ctx = FlowContext(initial_task="research AI")
        result = ctx.get_input_for_node("node-1", set())
        assert result["task"] == "research AI"
        assert "dependencies" not in result

    def test_with_deps_includes_results(self):
        ctx = FlowContext(initial_task="research AI")
        ctx.results["dep-1"] = "findings"
        result = ctx.get_input_for_node("node-2", {"dep-1"})
        assert result["dependencies"]["dep-1"] == "findings"

    def test_dep_without_result_excluded(self):
        ctx = FlowContext(initial_task="task")
        # dep-1 is a dependency but has no result yet
        result = ctx.get_input_for_node("node-2", {"dep-1"})
        assert "dep-1" not in result.get("dependencies", {})

    def test_task_always_present_with_deps(self):
        ctx = FlowContext(initial_task="initial")
        ctx.results["dep-1"] = "r1"
        result = ctx.get_input_for_node("n2", {"dep-1"})
        assert result["task"] == "initial"


class TestFlowContextBackwardCompat:
    def test_agent_metadata_alias(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.agent_metadata is ctx.node_metadata

    def test_agent_metadata_reflects_node_metadata(self):
        ctx = FlowContext(initial_task="test")
        info = NodeExecutionInfo(node_id="n1", node_name="a1")
        ctx.node_metadata["n1"] = info
        assert ctx.agent_metadata["n1"] is info

    def test_get_input_for_agent_alias(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.get_input_for_agent("n", set()) == ctx.get_input_for_node("n", set())

    def test_get_input_for_agent_with_deps(self):
        ctx = FlowContext(initial_task="test")
        ctx.results["dep-1"] = "value"
        via_agent = ctx.get_input_for_agent("n2", {"dep-1"})
        via_node = ctx.get_input_for_node("n2", {"dep-1"})
        assert via_agent == via_node


class TestFlowContextMarkFailed:
    def test_stores_error(self):
        ctx = FlowContext(initial_task="test")
        exc = RuntimeError("boom")
        ctx.mark_failed("node-1", exc)
        assert ctx.errors["node-1"] is exc

    def test_removes_from_active_tasks(self):
        ctx = FlowContext(initial_task="test")
        ctx.active_tasks.add("node-1")
        ctx.mark_failed("node-1", ValueError("err"))
        assert "node-1" not in ctx.active_tasks

    def test_does_not_add_to_completed_tasks(self):
        ctx = FlowContext(initial_task="test")
        ctx.mark_failed("node-1", ValueError("err"))
        assert "node-1" not in ctx.completed_tasks

    def test_stores_metadata_when_provided(self):
        ctx = FlowContext(initial_task="test")
        info = NodeExecutionInfo(node_id="node-1", node_name="agent-1", status="failed")
        ctx.mark_failed("node-1", RuntimeError("err"), metadata=info)
        assert ctx.node_metadata["node-1"] is info

    def test_no_metadata_when_none(self):
        ctx = FlowContext(initial_task="test")
        ctx.mark_failed("node-1", RuntimeError("err"))
        assert "node-1" not in ctx.node_metadata


class TestFlowContextDefaults:
    def test_empty_results_on_init(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.results == {}

    def test_empty_responses_on_init(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.responses == {}

    def test_empty_node_metadata_on_init(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.node_metadata == {}

    def test_empty_completion_order_on_init(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.completion_order == []

    def test_empty_errors_on_init(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.errors == {}

    def test_empty_active_tasks_on_init(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.active_tasks == set()

    def test_empty_completed_tasks_on_init(self):
        ctx = FlowContext(initial_task="test")
        assert ctx.completed_tasks == set()
