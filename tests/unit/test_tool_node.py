"""
Unit tests for the deterministic ToolNode and its template resolver.

Verifies that:
- resolve_templates substitutes {input} and {nodes.<name>.output}
  placeholders, preserves native types on full-match, walks nested
  structures, leaves literal braces alone, and raises a clear error for
  unresolvable node references.
- ToolNode duck-types the crew node contract (name, agent, is_configured,
  auto-created FSM) and its execute() returns the AgentNode-compatible
  result dict.
- A failed ToolResult raises ToolNodeExecutionError.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.bots.flows.crew import (
    TemplateResolutionError,
    ToolNode,
    ToolNodeExecutionError,
    resolve_templates,
)
from parrot.bots.flows.crew.tool_node import extract_tool_output
from parrot.tools.abstract import ToolResult


class RecordingTool:
    """Minimal ToolLike double that records calls."""

    def __init__(
        self,
        name: str = "recording_tool",
        result: Any = "tool-output",
        *,
        fail: bool = False,
    ) -> None:
        self.name = name
        self._result = result
        self._fail = fail
        self.calls: list = []

    async def execute(self, *args: Any, **kwargs: Any) -> ToolResult:
        self.calls.append((args, kwargs))
        if self._fail:
            return ToolResult(
                success=False, status="error", result=None, error="boom"
            )
        return ToolResult(success=True, status="success", result=self._result)


def make_ctx(**overrides: Any) -> SimpleNamespace:
    """Build a minimal FlowContext-shaped object for execute() tests."""
    defaults = dict(
        initial_task="the-initial-task",
        results={},
        completion_order=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestResolveTemplates:
    """Tests for the deterministic template resolver."""

    def test_input_placeholder(self):
        assert resolve_templates("{input}", input_text="AAPL", results={}) == "AAPL"

    def test_embedded_placeholder_stringifies(self):
        out = resolve_templates(
            "symbol={input}!", input_text="AAPL", results={}
        )
        assert out == "symbol=AAPL!"

    def test_node_output_placeholder(self):
        out = resolve_templates(
            "{nodes.researcher.output}",
            input_text="",
            results={"researcher": "found-it"},
        )
        assert out == "found-it"

    def test_full_match_preserves_native_type(self):
        payload = {"price": 42, "rows": [1, 2]}
        out = resolve_templates(
            "{nodes.fetch.output}", input_text="", results={"fetch": payload}
        )
        assert out is payload

    def test_embedded_node_output_stringifies(self):
        out = resolve_templates(
            "data: {nodes.fetch.output}",
            input_text="",
            results={"fetch": {"k": 1}},
        )
        assert out == "data: {'k': 1}"

    def test_nested_structures_walked(self):
        value = {
            "q": "sym={input}",
            "n": 3,
            "inner": {"ref": "{nodes.a.output}"},
            "items": ["{input}", 7],
        }
        out = resolve_templates(value, input_text="X", results={"a": "A-OUT"})
        assert out == {
            "q": "sym=X",
            "n": 3,
            "inner": {"ref": "A-OUT"},
            "items": ["X", 7],
        }

    def test_literal_braces_untouched(self):
        literal = '{"json": 1, "other": {"nested": true}}'
        assert resolve_templates(literal, input_text="", results={}) == literal

    def test_missing_node_raises_with_available_keys(self):
        with pytest.raises(TemplateResolutionError) as excinfo:
            resolve_templates(
                "{nodes.missing.output}", input_text="", results={"a": 1}
            )
        assert "missing" in str(excinfo.value)
        assert "'a'" in str(excinfo.value)

    def test_non_string_leaves_pass_through(self):
        assert resolve_templates(42, input_text="x", results={}) == 42
        assert resolve_templates(None, input_text="x", results={}) is None


class TestExtractToolOutput:
    """Tests for ToolResult payload stringification."""

    def test_string_passthrough(self):
        tr = ToolResult(success=True, status="success", result="plain")
        assert extract_tool_output(tr) == "plain"

    def test_dict_payload_serialised(self):
        tr = ToolResult(success=True, status="success", result={"a": 1})
        out = extract_tool_output(tr)
        assert isinstance(out, str)
        assert '"a"' in out or "'a'" in out


class TestToolNodeContract:
    """Duck-typing invariants required by the crew engine."""

    def test_identity_and_configuration(self):
        node = ToolNode(tool=RecordingTool(), node_id="fetch")
        assert node.name == "fetch"
        assert node.agent is node
        assert node.is_configured is True
        assert node.fsm is not None
        assert node.dependencies == set()
        assert node.successors == set()

    def test_default_description(self):
        node = ToolNode(tool=RecordingTool("weather"), node_id="fetch")
        assert node.description is None

    @pytest.mark.asyncio
    async def test_configure_is_noop(self):
        node = ToolNode(tool=RecordingTool(), node_id="fetch")
        assert await node.configure() is None


class TestToolNodeExecute:
    """Tests for flow-mode execute() and call_tool()."""

    @pytest.mark.asyncio
    async def test_execute_returns_agentnode_shaped_dict(self):
        tool = RecordingTool(result={"price": 42})
        node = ToolNode(tool=tool, node_id="fetch", kwargs={"q": "{input}"})
        result = await node.execute(make_ctx(), {})
        assert sorted(result.keys()) == [
            "execution_time", "output", "prompt", "response",
        ]
        assert isinstance(result["response"], ToolResult)
        assert isinstance(result["output"], str)
        assert "42" in result["output"]
        assert result["prompt"].startswith("tool:recording_tool(")
        assert tool.calls == [((), {"q": "the-initial-task"})]

    @pytest.mark.asyncio
    async def test_derive_input_uses_last_completed_dependency(self):
        tool = RecordingTool()
        node = ToolNode(
            tool=tool,
            node_id="fetch",
            kwargs={"q": "{input}"},
            dependencies={"a", "b"},
        )
        ctx = make_ctx(
            results={"a": "a-out", "b": "b-out", "c": "c-out"},
            completion_order=["a", "c", "b"],
        )
        await node.execute(ctx, ctx.results)
        assert tool.calls[0][1]["q"] == "b-out"

    @pytest.mark.asyncio
    async def test_positional_args_passed_through(self):
        tool = RecordingTool()
        node = ToolNode(tool=tool, node_id="fetch", args=["{input}", 5])
        await node.execute(make_ctx(initial_task="AAPL"), {})
        assert tool.calls[0][0] == ("AAPL", 5)

    @pytest.mark.asyncio
    async def test_failed_tool_result_raises(self):
        node = ToolNode(tool=RecordingTool(fail=True), node_id="fetch")
        with pytest.raises(ToolNodeExecutionError) as excinfo:
            await node.execute(make_ctx(), {})
        assert "fetch" in str(excinfo.value)
        assert "boom" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_call_tool_resolves_node_references(self):
        tool = RecordingTool()
        node = ToolNode(
            tool=tool, node_id="fetch", kwargs={"sym": "{nodes.a.output}"}
        )
        result = await node.call_tool(
            input_text="ignored", results={"a": "A-VALUE"}
        )
        assert isinstance(result, ToolResult)
        assert tool.calls[0][1]["sym"] == "A-VALUE"

    @pytest.mark.asyncio
    async def test_call_tool_missing_reference_raises(self):
        node = ToolNode(
            tool=RecordingTool(),
            node_id="fetch",
            kwargs={"sym": "{nodes.absent.output}"},
        )
        with pytest.raises(TemplateResolutionError):
            await node.call_tool(input_text="", results={})

    @pytest.mark.asyncio
    async def test_pre_and_post_actions_fire_in_execute(self):
        events: list = []
        node = ToolNode(tool=RecordingTool(), node_id="fetch")
        node.add_pre_action(lambda name, prompt, **ctx: events.append(("pre", name)))
        node.add_post_action(lambda name, result, **ctx: events.append(("post", name)))
        await node.execute(make_ctx(), {})
        assert events == [("pre", "fetch"), ("post", "fetch")]
