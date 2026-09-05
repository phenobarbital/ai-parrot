"""Unit tests for ``PlanPlanner`` and ``resolve_planner_client`` (TASK-2183).

The canned client double is a real ``AbstractClient`` subclass (so
``isinstance`` checks in ``resolve_planner_client`` pass) with every
abstract method stubbed and ``ask()`` returning scripted responses — no
network, no real provider.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from parrot.bots.flows.plan import ExecutionPlan
from parrot.bots.flows.plan.validator import validate_plan
from parrot.clients.base import AbstractClient
from parrot.clients.anthropic import AnthropicClient
from parrot.tools.execution_plan.catalog import ToolCatalogEntry
from parrot.tools.execution_plan.planner import (
    PlanAuthoringError,
    PlanPlanner,
    resolve_planner_client,
)

_VALID_PLAN = {
    "name": "sweep",
    "objective": "test objective",
    "nodes": [
        {"id": "n1", "tool": "s3_filter_reports", "store_as": "k1"},
    ],
}


class _FakeClient(AbstractClient):
    """Minimal AbstractClient double: scripted ask() responses, no network."""

    def __init__(self, responses: List[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._responses = list(responses)
        self.calls: List[str] = []

    async def get_client(self) -> Any:
        return self

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        text = self._responses.pop(0)
        return SimpleNamespace(output=text)

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def _catalog() -> List[ToolCatalogEntry]:
    return [ToolCatalogEntry(name="s3_filter_reports", description="List reports", args_summary=[])]


class TestResolvePlannerClient:
    def test_provider_model_string(self) -> None:
        client = resolve_planner_client("google:gemini-2.5-flash")
        assert client.model == "gemini-2.5-flash"

    def test_instance_passthrough(self) -> None:
        instance = _FakeClient(["{}"])
        assert resolve_planner_client(instance) is instance

    def test_class_passthrough_instantiates(self) -> None:
        client = resolve_planner_client(AnthropicClient)
        assert isinstance(client, AnthropicClient)

    def test_dict_config(self) -> None:
        client = resolve_planner_client({"name": "openai", "model": "gpt-5", "temperature": 0.2})
        assert client.model == "gpt-5"
        assert client.temperature == 0.2

    def test_dict_config_provider_model_in_name(self) -> None:
        client = resolve_planner_client({"llm": "anthropic:claude-sonnet-5"})
        assert client.model == "claude-sonnet-5"

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="planner_llm must be one of"):
            resolve_planner_client(123)  # type: ignore[arg-type]

    def test_dict_missing_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="name.*llm.*provider"):
            resolve_planner_client({"model": "x"})

    def test_dict_unsupported_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            resolve_planner_client({"name": "not-a-real-provider"})


class TestPlanPlanner:
    async def test_author_valid_plan(self) -> None:
        client = _FakeClient([json.dumps(_VALID_PLAN)])
        planner = PlanPlanner(client, _catalog())

        plan = await planner.author("sweep reports")

        assert isinstance(plan, ExecutionPlan)
        assert plan.name == "sweep"
        assert len(client.calls) == 1

    async def test_author_invalid_json_raises_typed(self) -> None:
        client = _FakeClient(["not json at all {"])
        planner = PlanPlanner(client, _catalog())

        with pytest.raises(PlanAuthoringError, match="not valid JSON"):
            await planner.author("sweep reports")

    async def test_author_schema_invalid_raises_typed(self) -> None:
        # Valid JSON, but fails ExecutionPlan's own validators (no nodes).
        client = _FakeClient([json.dumps({"name": "x", "objective": "y", "nodes": []})])
        planner = PlanPlanner(client, _catalog())

        with pytest.raises(PlanAuthoringError, match="failed ExecutionPlan validation"):
            await planner.author("sweep reports")

    async def test_author_strips_markdown_fence(self) -> None:
        fenced = f"```json\n{json.dumps(_VALID_PLAN)}\n```"
        client = _FakeClient([fenced])
        planner = PlanPlanner(client, _catalog())

        plan = await planner.author("sweep reports")
        assert plan.name == "sweep"

    async def test_repair_embeds_report_and_returns_plan(self) -> None:
        bad_plan = {
            "name": "sweep",
            "objective": "test",
            "nodes": [{"id": "n1", "tool": "unknown_tool", "store_as": "k1"}],
        }
        report = validate_plan(ExecutionPlan.model_validate(bad_plan), tool_manager=None)

        client = _FakeClient([json.dumps(_VALID_PLAN)])
        planner = PlanPlanner(client, _catalog())

        plan = await planner.repair(bad_plan, report)

        assert isinstance(plan, ExecutionPlan)
        assert len(client.calls) == 1
        # The repair prompt must embed the report text verbatim.
        assert str(report) in client.calls[0]
        assert json.dumps(bad_plan) in client.calls[0]

    async def test_single_call_per_round(self) -> None:
        client = _FakeClient([json.dumps(_VALID_PLAN), json.dumps(_VALID_PLAN)])
        planner = PlanPlanner(client, _catalog())

        await planner.author("objective one")
        assert len(client.calls) == 1

        report = validate_plan(ExecutionPlan.model_validate(_VALID_PLAN), tool_manager=None)
        await planner.repair(_VALID_PLAN, report)
        assert len(client.calls) == 2

    async def test_no_default_model_anywhere(self) -> None:
        import parrot.tools.execution_plan.planner as planner_module

        source = planner_module.__file__
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        assert "anthropic:claude" not in text.lower()
        assert "gpt-" not in text.lower()
        assert "gemini" not in text.lower()
