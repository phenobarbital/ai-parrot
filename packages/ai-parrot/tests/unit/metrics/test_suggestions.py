"""Tests for MetricSuggestionProvider (FEAT-756 G7, FEAT-752 provider)."""

from __future__ import annotations

import pytest

from parrot.bots.suggestions.protocol import SuggestionContext
from parrot.metrics.context import bind_metric_match, reset_metric_match
from parrot.metrics.models import MetricDefinition, MetricMatch
from parrot.metrics.suggestions import MetricSuggestionProvider
from parrot.models.suggestions import Suggestion, SuggestionKind, SuggestionSource


@pytest.fixture
def provider() -> MetricSuggestionProvider:
    """Return a fresh provider instance."""
    return MetricSuggestionProvider(max_chips=5)


@pytest.fixture
def worked_hours_match(worked_hours_def: MetricDefinition) -> MetricMatch:
    """Return a MetricMatch for worked hours."""
    return MetricMatch(
        metric=worked_hours_def,
        score=0.95,
        lane="alias",
        tenant="test-tenant",
    )


@pytest.mark.asyncio
async def test_no_match_returns_empty(provider: MetricSuggestionProvider) -> None:
    """No stashed match → empty list."""
    token = bind_metric_match(None)
    try:
        suggestions = await provider.suggest(
            SuggestionContext(
                question="show me worked hours",
                response=None,
                output_mode=None,
                bot=None,
            )
        )
        assert suggestions == []
    finally:
        reset_metric_match(token)


@pytest.mark.asyncio
async def test_metric_suggestion_provider_chips(
    provider: MetricSuggestionProvider,
    worked_hours_match: MetricMatch,
) -> None:
    """Match with 2 dimensions + previous_period → compare chip, 2 dimension chips, shape chips, total ≤ max_chips."""
    token = bind_metric_match(worked_hours_match)
    try:
        suggestions = await provider.suggest(
            SuggestionContext(
                question="show me worked hours",
                response=None,
                output_mode=None,
                bot=None,
            )
        )

        # Should have: compare, 2 dimensions, 2 other shapes (KPICard is current)
        assert len(suggestions) == 5
        assert len(suggestions) <= provider.max_chips

        # Check compare chip
        compare = next((s for s in suggestions if s.label == "vs previous period"), None)
        assert compare is not None
        assert compare.kind == SuggestionKind.FOLLOWUP
        assert compare.source == SuggestionSource.PROVIDER
        assert "vs previous period" in compare.prompt

        # Check dimension chips
        dimension_labels = {s.label for s in suggestions if s.label.startswith("by ")}
        assert "by cost center" in dimension_labels
        assert "by pay code" in dimension_labels

        # Check shape chips (presentation)
        shape_labels = {s.label for s in suggestions if s.label.startswith("as ")}
        assert "as Chart" in shape_labels
        assert "as DataTable" in shape_labels

        # All chips should be valid Suggestion instances
        for chip in suggestions:
            assert isinstance(chip, Suggestion)
    finally:
        reset_metric_match(token)


@pytest.mark.asyncio
async def test_comparison_none_skips_compare_chip(
    provider: MetricSuggestionProvider,
    worked_hours_def: MetricDefinition,
) -> None:
    """comparison.mode == 'none' → no compare chip."""
    # Create a match with comparison mode "none"
    match = MetricMatch(
        metric=worked_hours_def,
        score=0.95,
        lane="alias",
        tenant="test-tenant",
    )
    # Override comparison mode
    match.metric.comparison.mode = "none"

    token = bind_metric_match(match)
    try:
        suggestions = await provider.suggest(
            SuggestionContext(
                question="show me worked hours",
                response=None,
                output_mode=None,
                bot=None,
            )
        )

        # Should have: 2 dimensions, 2 other shapes (no compare chip)
        assert len(suggestions) == 4
        assert len(suggestions) <= provider.max_chips

        # No compare chip
        assert not any(s.label == "vs previous period" for s in suggestions)

        # Should have dimension and shape chips
        dimension_labels = {s.label for s in suggestions if s.label.startswith("by ")}
        assert "by cost center" in dimension_labels
        assert "by pay code" in dimension_labels

        shape_labels = {s.label for s in suggestions if s.label.startswith("as ")}
        assert "as Chart" in shape_labels
        assert "as DataTable" in shape_labels
    finally:
        reset_metric_match(token)
