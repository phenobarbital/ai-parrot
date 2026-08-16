"""Regression tests: nested Pydantic args must survive argument validation.

``AbstractTool.execute()`` validates the raw arguments an LLM sends against the
tool's ``args_schema``. That validation coerces JSON objects into the models the
tool declared — but the result used to be flattened again with
``model_dump()``, which serialises *recursively*. Any tool whose signature
declared a nested model therefore received plain dicts and blew up on attribute
access with ``'dict' object has no attribute '<field>'``.

These tests pin the contract: a tool receives the types its signature declares,
for both plain tools and toolkit-generated tools.
"""
from typing import Any

import pytest
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from parrot.tools.toolkit import AbstractToolkit
from pydantic import BaseModel, Field


class Metric(BaseModel):
    """A nested model an LLM would send as a JSON object."""

    name: str = Field(description="Metric name")
    formula: str = Field(description="Metric formula")
    description: str | None = None


class MetricsToolkit(AbstractToolkit):
    """Toolkit whose tool declares a list of nested models."""

    name = "metrics"
    description = "Toolkit used to pin nested-model argument handling"

    async def register_metrics(
        self,
        dataset: str,
        metrics: list[Metric] | None = None,
    ) -> str:
        """Register derived metrics for a dataset.

        Dereferences ``.name`` so the test fails loudly if the tool layer
        hands over dicts instead of ``Metric`` instances.
        """
        metrics = metrics or []
        return f"{dataset}:" + ",".join(f"{m.name}={m.formula}" for m in metrics)


class SingleMetricArgs(BaseModel):
    """Schema with a single (non-list) nested model."""

    metric: Metric


class SingleMetricTool(AbstractTool):
    """Plain AbstractTool with an explicit args_schema."""

    args_schema = SingleMetricArgs

    def __init__(self) -> None:
        super().__init__(name="single_metric", description="Echo one metric")

    async def _execute(self, **kwargs: Any) -> str:
        """Return the nested model's type name and its ``name`` field."""
        metric = kwargs["metric"]
        return f"{type(metric).__name__}:{metric.name}"


class ExtraArgs(BaseModel):
    """Schema that accepts unknown keys, mirroring lenient tool schemas."""

    model_config = {"extra": "allow"}

    known: str


class ExtraTool(AbstractTool):
    """Tool whose schema allows extra keys."""

    args_schema = ExtraArgs

    def __init__(self) -> None:
        super().__init__(name="extra_tool", description="Echo all kwargs")

    async def _execute(self, **kwargs: Any) -> dict:
        """Return every kwarg the tool layer forwarded."""
        return dict(kwargs)


@pytest.mark.asyncio
async def test_toolkit_tool_receives_nested_models_from_json():
    """A toolkit tool called with raw JSON gets model instances, not dicts."""
    toolkit = MetricsToolkit()
    tool = toolkit.get_tool("register_metrics")

    result = await tool.execute(
        dataset="clients",
        # Exactly the shape an LLM emits: a list of JSON objects.
        metrics=[
            {"name": "ebitda", "formula": "revenue - payroll - expenses"},
            {"name": "margin", "formula": "ebitda / revenue"},
        ],
    )

    assert not result.error, result.error
    assert result.result == (
        "clients:ebitda=revenue - payroll - expenses,margin=ebitda / revenue"
    )


@pytest.mark.asyncio
async def test_plain_tool_receives_nested_model_from_json():
    """A non-toolkit tool with an explicit args_schema behaves the same way."""
    result = await SingleMetricTool().execute(
        metric={"name": "ebitda", "formula": "revenue - expenses"},
    )

    assert not result.error, result.error
    assert result.result == "Metric:ebitda"


@pytest.mark.asyncio
async def test_already_typed_arguments_still_work():
    """Passing real model instances (programmatic callers) is unaffected."""
    toolkit = MetricsToolkit()
    tool = toolkit.get_tool("register_metrics")

    result = await tool.execute(
        dataset="clients",
        metrics=[Metric(name="ebitda", formula="revenue - expenses")],
    )

    assert not result.error, result.error
    assert result.result == "clients:ebitda=revenue - expenses"


@pytest.mark.asyncio
async def test_scalar_arguments_are_unchanged():
    """Plain scalars keep passing through untouched."""
    toolkit = MetricsToolkit()
    tool = toolkit.get_tool("register_metrics")

    result = await tool.execute(dataset="clients")

    assert not result.error, result.error
    assert result.result == "clients:"


@pytest.mark.asyncio
async def test_extra_fields_are_preserved():
    """Schemas declared with extra='allow' still forward unknown keys."""
    result = await ExtraTool().execute(known="a", surprise="b")

    assert not result.error, result.error
    assert result.result == {"known": "a", "surprise": "b"}


def test_shallow_dump_keeps_nested_models():
    """The helper itself: one level of dumping, nested models intact."""
    validated = SingleMetricArgs(metric={"name": "ebitda", "formula": "r - e"})

    dumped = AbstractTool._shallow_dump(validated)

    assert isinstance(dumped, dict)
    assert isinstance(dumped["metric"], Metric)
    # model_dump() is what used to destroy the type — contrast pinned here.
    assert isinstance(validated.model_dump()["metric"], dict)


def test_shallow_dump_on_empty_schema():
    """A schema with no declared fields dumps to an empty dict."""
    assert AbstractTool._shallow_dump(AbstractToolArgsSchema()) == {}
