"""Unit tests for parrot.bots.flows.core.result (TASK-915)."""
import pytest
from parrot.bots.flows.core.result import (
    FlowResult,
    NodeExecutionInfo,
    determine_run_status,
    build_node_metadata,
)
from parrot.bots.flows.core.types import FlowStatus


class TestNodeExecutionInfo:
    def test_backward_compat_aliases(self):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1")
        assert info.agent_id == "n1"
        assert info.agent_name == "agent-1"

    def test_to_dict(self):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1", status="completed")
        d = info.to_dict()
        assert d["node_id"] == "n1"
        assert d["status"] == "completed"

    def test_to_dict_includes_aliases(self):
        info = NodeExecutionInfo(node_id="n2", node_name="agent-2")
        d = info.to_dict()
        assert d["agent_id"] == "n2"
        assert d["agent_name"] == "agent-2"

    def test_default_status_pending(self):
        info = NodeExecutionInfo(node_id="n1", node_name="agent-1")
        assert info.status == "pending"

    def test_all_fields(self):
        info = NodeExecutionInfo(
            node_id="n3",
            node_name="agent-3",
            provider="openai",
            model="gpt-4",
            execution_time=1.5,
            tool_calls=[{"name": "search"}],
            status="completed",
            error=None,
            client="OpenAIClient",
            usage={"tokens": 100},
        )
        assert info.provider == "openai"
        assert info.model == "gpt-4"
        assert info.execution_time == 1.5
        assert info.tool_calls == [{"name": "search"}]
        assert info.client == "OpenAIClient"
        assert info.usage == {"tokens": 100}

    def test_error_field(self):
        info = NodeExecutionInfo(
            node_id="n4", node_name="agent-4", status="failed", error="Timeout"
        )
        assert info.error == "Timeout"
        d = info.to_dict()
        assert d["error"] == "Timeout"


class TestFlowResult:
    def test_nodes_is_primary(self):
        info = NodeExecutionInfo(node_id="n1", node_name="a1")
        r = FlowResult(output="done", nodes=[info])
        assert r.nodes == [info]
        assert r.agents == [info]  # backward-compat alias

    def test_content_alias(self):
        r = FlowResult(output="hello")
        assert r.content == "hello"

    def test_final_result_alias(self):
        r = FlowResult(output="world")
        assert r.final_result == "world"

    def test_success_property(self):
        r = FlowResult(output="ok", status=FlowStatus.COMPLETED)
        assert r.success is True
        r2 = FlowResult(output="fail", status=FlowStatus.FAILED)
        assert r2.success is False

    def test_success_partial_is_false(self):
        r = FlowResult(output="partial", status=FlowStatus.PARTIAL)
        assert r.success is False

    def test_to_dict_round_trip(self):
        r = FlowResult(output="test", status=FlowStatus.COMPLETED)
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["output"] == "test"
        assert d["status"] in ("completed", FlowStatus.COMPLETED)

    def test_to_dict_has_backward_compat_agents_key(self):
        info = NodeExecutionInfo(node_id="n1", node_name="a1")
        r = FlowResult(output="ok", nodes=[info])
        d = r.to_dict()
        assert "agents" in d
        assert "nodes" in d
        assert len(d["agents"]) == 1
        assert len(d["nodes"]) == 1

    def test_backward_compat_agent_results(self):
        r = FlowResult(output="ok")
        assert isinstance(r.node_results, dict)
        assert r.agent_results == r.node_results

    def test_completed_nodes(self):
        n1 = NodeExecutionInfo(node_id="n1", node_name="a1", status="completed")
        n2 = NodeExecutionInfo(node_id="n2", node_name="a2", status="failed")
        r = FlowResult(output="ok", nodes=[n1, n2])
        assert r.completed == ["n1"]
        assert r.failed == ["n2"]

    def test_getitem_output(self):
        r = FlowResult(output="hello")
        assert r["output"] == "hello"
        assert r["final_result"] == "hello"
        assert r["content"] == "hello"

    def test_getitem_status(self):
        r = FlowResult(output="ok", status=FlowStatus.COMPLETED)
        assert r["success"] is True

    def test_getitem_invalid_raises_key_error(self):
        r = FlowResult(output="ok")
        with pytest.raises(KeyError):
            _ = r["nonexistent"]

    def test_str_repr(self):
        r = FlowResult(output="hello")
        assert str(r) == "hello"
        assert "FlowResult" in repr(r)

    def test_summary_coerced_to_str(self):
        r = FlowResult(output="ok")
        r.summary = 42  # type: ignore[assignment]
        assert isinstance(r.summary, str)
        assert r.summary == "42"

    def test_default_status_is_completed(self):
        r = FlowResult(output="ok")
        assert r.status == FlowStatus.COMPLETED

    def test_total_execution_time_alias(self):
        r = FlowResult(output="ok", total_time=3.5)
        assert r.total_execution_time == 3.5


class TestDetermineRunStatus:
    def test_all_success(self):
        assert determine_run_status(3, 0) == "completed"

    def test_all_failed(self):
        assert determine_run_status(0, 3) == "failed"

    def test_partial(self):
        assert determine_run_status(2, 1) == "partial"

    def test_zero_zero_returns_completed(self):
        # No failures → completed
        assert determine_run_status(0, 0) == "completed"


class TestBuildNodeMetadata:
    def test_returns_node_execution_info(self):
        info = build_node_metadata(
            node_id="n1",
            agent=None,
            response=None,
            output="result",
            execution_time=0.5,
            status="completed",
        )
        assert isinstance(info, NodeExecutionInfo)
        assert info.node_id == "n1"
        assert info.status == "completed"
        assert info.execution_time == 0.5

    def test_normalises_success_status(self):
        info = build_node_metadata(
            node_id="n1",
            agent=None,
            response=None,
            output=None,
            execution_time=0.0,
            status="success",  # legacy status string
        )
        assert info.status == "completed"

    def test_normalises_error_status(self):
        info = build_node_metadata(
            node_id="n1",
            agent=None,
            response=None,
            output=None,
            execution_time=0.0,
            status="error",  # legacy status string
        )
        assert info.status == "failed"

    def test_agent_name_extracted(self):
        class FakeAgent:
            name = "my-agent"

        info = build_node_metadata(
            node_id="n1",
            agent=FakeAgent(),
            response=None,
            output=None,
            execution_time=0.0,
            status="completed",
        )
        assert info.node_name == "my-agent"

    def test_error_field_propagated(self):
        info = build_node_metadata(
            node_id="n1",
            agent=None,
            response=None,
            output=None,
            execution_time=0.0,
            status="failed",
            error="Something went wrong",
        )
        assert info.error == "Something went wrong"
