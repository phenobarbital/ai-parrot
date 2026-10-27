"""Tests for MetricSuggestionProvider (FEAT-756 G7)."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from parrot.metrics.context import bind_metric_match, reset_metric_match
from parrot.metrics.models import MetricMatch
from parrot.metrics.suggestions import MetricSuggestionProvider

if TYPE_CHECKING:
    from parrot.bots.suggestions.protocol import SuggestionContext
    from parrot.metrics.models import MetricDefinition


async def test_no_match_returns_empty():
    """Test that no stashed match returns empty list."""
    provider = MetricSuggestionProvider()

    # Create a mock context
    ctx = AsyncMock()

    # No match bound, should return empty list
    result = await provider.suggest(ctx)
    assert result == []


async def test_metric_suggestion_provider_chips(worked_hours_def: "MetricDefinition"):
    """Test that provider generates chips for a metric with dimensions and comparison."""
    provider = MetricSuggestionProvider(max_chips=10)

    # Create a mock context
    ctx = AsyncMock()

    # Bind a metric match
    match = MetricMatch(metric=worked_hours_def, score=0.95, lane="alias")
    token = bind_metric_match(match)

    try:
        result = await provider.suggest(ctx)

        # Should have chips: compare + 2 dimensions + 2 shapes (Chart, DataTable)
        assert len(result) == 5

        # Check compare chip
        compare_chip = result[0]
        assert compare_chip.label == "vs previous period"
        assert compare_chip.prompt == "Compare Worked Hours vs previous period"
        assert compare_chip.kind.name == "FOLLOWUP"
        assert compare_chip.source.name == "PROVIDER"

        # Check dimension chips
        dim_chip_1 = result[1]
        assert dim_chip_1.label == "by cost center"
        assert dim_chip_1.prompt == "Show Worked Hours by cost center"
        assert dim_chip_1.kind.name == "FOLLOWUP"
        assert dim_chip_1.source.name == "PROVIDER"

        dim_chip_2 = result[2]
        assert dim_chip_2.label == "by pay code"
        assert dim_chip_2.prompt == "Show Worked Hours by pay code"
        assert dim_chip_2.kind.name == "FOLLOWUP"
        assert dim_chip_2.source.name == "PROVIDER"

        # Check presentation chips (excluding current shape which is KPICard)
        pres_chip_1 = result[3]
        assert pres_chip_1.label == "as Chart"
        assert pres_chip_1.prompt == "Show Worked Hours as a chart"
        assert pres_chip_1.kind.name == "PRESENTATION"
        assert pres_chip_1.source.name == "PROVIDER"

        pres_chip_2 = result[4]
        assert pres_chip_2.label == "as DataTable"
        assert pres_chip_2.prompt == "Show Worked Hours as a datatable"
        assert pres_chip_2.kind.name == "PRESENTATION"
        assert pres_chip_2.source.name == "PROVIDER"

    finally:
        reset_metric_match(token)


async def test_comparison_none_skips_compare_chip(worked_hours_def: "MetricDefinition"):
    """Test that comparison mode 'none' skips the compare chip."""
    provider = MetricSuggestionProvider(max_chips=10)

    # Create a mock context
    ctx = AsyncMock()

    # Create a copy of worked_hours_def with comparison mode 'none'
    metric_def = worked_hours_def.model_copy(deep=True)
    metric_def.comparison.mode = "none"

    # Bind a metric match
    match = MetricMatch(metric=metric_def, score=0.95, lane="alias")
    token = bind_metric_match(match)

    try:
        result = await provider.suggest(ctx)

        # Should have chips: 2 dimensions + 2 shapes (Chart, DataTable) but no compare chip
        assert len(result) == 4

        # First chip should be a dimension chip, not compare chip
        first_chip = result[0]
        assert first_chip.label == "by cost center"
        assert first_chip.prompt == "Show Worked Hours by cost center"
        assert first_chip.kind.name == "FOLLOWUP"

    finally:
        reset_metric_match(token)


async def test_max_chips_limit(worked_hours_def: "MetricDefinition"):
    """Test that provider respects max_chips limit."""
    provider = MetricSuggestionProvider(max_chips=3)

    # Create a mock context
    ctx = AsyncMock()

    # Bind a metric match
    match = MetricMatch(metric=worked_hours_def, score=0.95, lane="alias")
    token = bind_metric_match(match)

    try:
        result = await provider.suggest(ctx)

        # Should be limited to 3 chips despite having more available
        assert len(result) == 3

    finally:
        reset_metric_match(token)


async def test_label_truncation():
    """Test that labels are truncated to 40 characters."""
    provider = MetricSuggestionProvider()

    # Create a mock context
    ctx = AsyncMock()

    # Create a metric with a very long dimension name
    from parrot.metrics.models import (
        MetricDefinition,
        DimensionSpec,
        TimeSpec,
        PeriodBinding,
        KPICardShape,
        QuerySlugSource,
    )

    long_dimension_metric = MetricDefinition(
        id="test_metric",
        name="Test Metric With Very Long Name That Exceeds Limits",
        description="",
        dimensions=[
            DimensionSpec(
                name="very_long_dimension_name_that_will_cause_truncation",
                column="col1",
                label="Very Long Dimension Label That Will Definitely Exceed Forty Characters",
            )
        ],
        time=TimeSpec(
            grain="month",
            default_period="this_month",
            binding=PeriodBinding(start_placeholder="start", end_placeholder="end"),
        ),
        default_shape=KPICardShape(component="KPICard", value_column="value"),
        source=QuerySlugSource(kind="query_slug", slug="test_slug"),
        comparison={"mode": "previous_period"},
    )

    # Bind a metric match
    match = MetricMatch(metric=long_dimension_metric, score=0.95, lane="alias")
    token = bind_metric_match(match)

    try:
        result = await provider.suggest(ctx)

        # Find the dimension chip and check truncation
        dimension_chip = None
        for chip in result:
            if chip.label.startswith("by "):
                dimension_chip = chip
                break

        assert dimension_chip is not None
        assert len(dimension_chip.label) <= 40
        if len(dimension_chip.label) == 40:
            assert dimension_chip.label.endswith("...")

    finally:
        reset_metric_match(token)
