"""FEAT-590 M1: protocol, adapter, trace sink."""
from __future__ import annotations

import json
import sys
from typing import Any, ClassVar, Dict

import pytest
from pydantic import BaseModel, ValidationError

from parrot.bots.flows.plan.delegate import JsonlTraceSink, ToolCallDelegate, ToolCallProposal, tool_specs
from parrot.bots.flows.plan.delegate.protocol import DelegateTrace
from parrot.tools.manager import ToolDefinition

from ._delegate_fakes import FakeDelegate, FakeTool, FakeToolManager


class _Args(BaseModel):
    query: str
    _context_fields: ClassVar[frozenset[str]] = frozenset({"_permission_context"})
    _permission_context: str = "hidden"


def test_tool_specs_uses_get_schema_and_strips_context() -> None:
    """Use the tool's authoritative schema and its delegate-specific description."""
    tool = FakeTool("search", _Args, delegate_description="Search indexed records")
    tool.get_schema = lambda: {
        "name": "search",
        "description": "search tool",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "$defs": {}},
    }

    specs = tool_specs(FakeToolManager([tool], {}), ["search"])

    assert specs == [
        {
            "name": "search",
            "description": "Search indexed records",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "$defs": {}},
        }
    ]
    assert "_permission_context" not in specs[0].parameters["properties"]


def test_tool_specs_supports_tooldefinition() -> None:
    """ToolDefinition supplies its already-authoritative input schema."""
    definition = ToolDefinition("weather", "Weather lookup", {"type": "object", "properties": {}}, lambda: None)

    specs = tool_specs(type("Manager", (), {"get_tool": lambda self, name: definition})(), ["weather"])

    assert specs[0].parameters is definition.input_schema
    assert specs[0].description == "Weather lookup"


def test_tool_specs_unknown_tool_raises() -> None:
    """The missing tool name is preserved in the error."""
    with pytest.raises(KeyError, match="missing"):
        tool_specs(FakeToolManager([], {}), ["missing"])


def test_proposal_confidence_bounds() -> None:
    """Confidence accepts None or values in the inclusive unit interval."""
    common: Dict[str, Any] = {"name": "search", "backend": "fake", "latency_ms": 1.0}
    assert ToolCallProposal(**common, confidence=None).confidence is None
    for confidence in (-0.1, 1.1):
        with pytest.raises(ValidationError):
            ToolCallProposal(**common, confidence=confidence)


def test_fake_delegate_satisfies_protocol() -> None:
    """The shared fake exposes the runtime protocol methods and attributes."""
    assert isinstance(FakeDelegate([]), ToolCallDelegate)


@pytest.mark.asyncio
async def test_jsonl_sink_appends_and_caps(tmp_path) -> None:
    """The sink appends one JSON document per record and caps nested strings."""
    trace = DelegateTrace(
        node_id="node",
        instruction="x" * 10,
        facts={"note": "y" * 10},
        tools=["search"],
        proposal=ToolCallProposal(name="search", arguments={"query": "z" * 10}, backend="fake", latency_ms=1),
        verdict="accepted",
    )
    sink = JsonlTraceSink(tmp_path / "traces.jsonl", max_field_chars=4)

    await sink.record(trace)
    await sink.record(trace)

    lines = (tmp_path / "traces.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["instruction"] == "xxxx…[truncated]"
    assert payload["facts"]["note"] == "yyyy…[truncated]"
    assert payload["proposal"]["arguments"]["query"] == "zzzz…[truncated]"


@pytest.mark.asyncio
async def test_jsonl_sink_never_raises(tmp_path) -> None:
    """An invalid append target is contained by the sink."""
    directory = tmp_path / "trace-directory"
    directory.mkdir()
    trace = DelegateTrace(
        node_id="node",
        instruction="choose",
        tools=["search"],
        proposal=ToolCallProposal(name=None, backend="fake", latency_ms=0),
        verdict="declined",
    )

    await JsonlTraceSink(directory).record(trace)


def test_package_import_is_lazy() -> None:
    """Importing the delegate package never imports the optional needle backend."""
    assert "needle" not in sys.modules
