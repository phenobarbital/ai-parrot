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
        info = NodeExecutionInfo(node_id="n4", node_name="agent-4", status="failed", error="Timeout")
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


# ---------------------------------------------------------------------------
# FEAT-447 / TASK-2326 — shared envelope unwrapping + NodeExecutionInfo.client
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_response_with_usage():
    """AgentResponse whose AIMessage carries REAL usage + tool_calls.

    NOTE: a real ``CompletionUsage`` is mandatory -- ``build_node_metadata``
    calls ``usage_obj.model_dump()``, and a ``MagicMock`` would return another
    Mock, making every assertion vacuous.
    """
    from parrot.models.basic import CompletionUsage, ToolCall
    from parrot.models.responses import AgentResponse, AIMessage

    message = AIMessage(
        input="q",
        output="answer",
        model="gpt-4o",
        provider="openai",
        usage=CompletionUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        tool_calls=[ToolCall(id="tc-1", name="get_weather", arguments={"city": "Madrid"})],
    )
    return AgentResponse(
        agent_id="a1",
        agent_name="agent-one",
        question="q",
        response=message,
        output="answer",
    )


@pytest.fixture
def node_envelope(agent_response_with_usage):
    """The exact dict ``AgentNode.execute()`` returns (``core/node.py``)."""
    return {
        "response": agent_response_with_usage,
        "output": "answer",
        "execution_time": 0.42,
        "prompt": "q",
    }


class TestUnwrapResponse:
    """Unit tests for the shared ``_unwrap_response`` helper."""

    def test_unwrap_response_envelope(self, node_envelope, agent_response_with_usage):
        """An envelope resolves to its inner AgentResponse."""
        from parrot.bots.flows.core.result import _unwrap_response

        assert _unwrap_response(node_envelope) is agent_response_with_usage

    def test_unwrap_response_passthrough(self, agent_response_with_usage):
        """AgentResponse, AIMessage, str and None pass through unchanged."""
        from parrot.bots.flows.core.result import _unwrap_response

        message = agent_response_with_usage.response
        assert _unwrap_response(agent_response_with_usage) is agent_response_with_usage
        assert _unwrap_response(message) is message
        assert _unwrap_response("plain string") == "plain string"
        assert _unwrap_response(None) is None

        sentinel = object()
        assert _unwrap_response(sentinel) is sentinel

    def test_unwrap_response_nested_envelope(self, agent_response_with_usage):
        """An envelope wrapping an envelope resolves; recursion is bounded."""
        from parrot.bots.flows.core.result import (
            _MAX_UNWRAP_DEPTH,
            _unwrap_response,
        )

        inner = {"response": agent_response_with_usage, "output": "answer"}
        outer = {"response": inner, "output": "answer"}
        assert _unwrap_response(outer) is agent_response_with_usage

        # Self-referential envelope: bounded, returns without raising.
        cyclic: dict = {"output": "x"}
        cyclic["response"] = cyclic
        assert _unwrap_response(cyclic) is cyclic

        # A chain deeper than the cap stops at the cap instead of recursing.
        deep: object = agent_response_with_usage
        for _ in range(_MAX_UNWRAP_DEPTH + 3):
            deep = {"response": deep, "output": "answer"}
        result = _unwrap_response(deep)
        assert isinstance(result, dict)

    def test_unwrap_response_dict_without_response_key(self):
        """A dict with no ``"response"`` key is NOT an envelope."""
        from parrot.bots.flows.core.result import _unwrap_response

        plain = {"output": "answer", "execution_time": 0.1}
        assert _unwrap_response(plain) is plain
        assert _unwrap_response({}) == {}


class TestBuildNodeMetadataEnvelope:
    """``build_node_metadata`` fidelity for envelopes, crews, and ``client``."""

    def test_build_node_metadata_from_envelope(self, node_envelope):
        """Envelope input yields non-None usage and non-empty tool_calls."""
        info = build_node_metadata(
            node_id="n1",
            agent=None,
            response=node_envelope,
            output="answer",
            execution_time=1.25,
            status="completed",
        )
        assert info.usage is not None
        assert info.usage["prompt_tokens"] == 11
        assert info.usage["completion_tokens"] == 7
        assert info.tool_calls
        assert info.tool_calls[0]["name"] == "get_weather"
        assert info.model == "gpt-4o"
        assert info.provider == "openai"
        assert info.execution_time == 1.25
        assert info.status == "completed"

    def test_build_node_metadata_crew_shape_unchanged(self, agent_response_with_usage):
        """A bare AgentResponse yields the same metadata as its envelope."""
        crew_info = build_node_metadata(
            node_id="n1",
            agent=None,
            response=agent_response_with_usage,
            output="answer",
            execution_time=1.25,
            status="completed",
        )
        assert crew_info.model == "gpt-4o"
        assert crew_info.provider == "openai"
        assert crew_info.usage is not None
        assert crew_info.usage["total_tokens"] == 18
        assert crew_info.tool_calls[0]["name"] == "get_weather"
        # Crew (bare response) and flow (envelope) must agree field-for-field.
        flow_info = build_node_metadata(
            node_id="n1",
            agent=None,
            response={
                "response": agent_response_with_usage,
                "output": "answer",
                "execution_time": 0.42,
                "prompt": "q",
            },
            output="answer",
            execution_time=1.25,
            status="completed",
        )
        assert flow_info.to_dict() == crew_info.to_dict()

    def test_build_node_metadata_sets_client(self):
        """client is the concrete client class name, not None."""

        class OpenAIClient:
            model = "gpt-4o"

        class FakeAgent:
            name = "agent-one"
            llm = OpenAIClient()

        info = build_node_metadata(
            node_id="n1",
            agent=FakeAgent(),
            response=None,
            output=None,
            execution_time=0.0,
            status="completed",
        )
        assert info.client == "OpenAIClient"
        assert info.model == "gpt-4o"
        assert info.to_dict()["client"] == "OpenAIClient"

    def test_build_node_metadata_client_none_without_agent(self):
        """No agent (or an unconfigured string llm) leaves client as None."""
        assert (
            build_node_metadata(
                node_id="n1",
                agent=None,
                response=None,
                output=None,
                execution_time=0.0,
                status="completed",
            ).client
            is None
        )

        class UnconfiguredAgent:
            name = "agent-one"
            llm = "openai:gpt-4o"

        assert (
            build_node_metadata(
                node_id="n1",
                agent=UnconfiguredAgent(),
                response=None,
                output=None,
                execution_time=0.0,
                status="completed",
            ).client
            is None
        )


# ---------------------------------------------------------------------------
# FEAT-447 / TASK-2327 — envelope-aware FlowResult.node_results
# ---------------------------------------------------------------------------


class TestNodeResultsEnvelope:
    """``node_results`` must yield scalars for BOTH executors' shapes."""

    def test_node_results_unwraps_envelope(self, agent_response_with_usage):
        """A FlowResult whose responses hold AgentNode envelopes yields scalars."""
        result = FlowResult(
            output="x",
            responses={
                "n1": {
                    "response": agent_response_with_usage,
                    "output": "answer-1",
                    "execution_time": 0.1,
                    "prompt": "q",
                },
                "n2": {
                    "response": agent_response_with_usage,
                    "output": {"structured": True},
                    "execution_time": 0.2,
                    "prompt": "q2",
                },
            },
        )
        assert result.node_results == {"n1": "answer-1", "n2": {"structured": True}}
        # The alias inherits the fix.
        assert result.agent_results == {"n1": "answer-1", "n2": {"structured": True}}
        # No value is an envelope dict (spec AC8).
        assert not any(isinstance(v, dict) and "response" in v for v in result.node_results.values())
        # Read-only projection: `responses` is untouched.
        assert result.responses["n1"]["prompt"] == "q"

    def test_node_results_crew_shape_unchanged(self, agent_response_with_usage):
        """AgentResponse responses still unwrap via .output; None stays None."""
        result = FlowResult(
            output="x",
            responses={
                "a1": agent_response_with_usage,
                "a2": None,
                "a3": "plain",
                # A dict WITHOUT an "output" key is not an envelope.
                "a4": {"other": 1},
            },
        )
        assert result.node_results["a1"] == agent_response_with_usage.output
        assert result.node_results["a2"] is None
        assert result.node_results["a3"] == "plain"
        assert result.node_results["a4"] == {"other": 1}
        assert result.agent_results == result.node_results
