"""Unit tests for ``StructuredChartConfig``'s new chart types (FEAT-527).

Verifies the 5 new ``ChartType`` members validate on the config and that the
new ``layout`` field round-trips through the model.
"""

from __future__ import annotations

import pytest

from parrot.models.outputs import StructuredChartConfig


@pytest.mark.parametrize("chart_type", ["gauge", "funnel", "waterfall", "heatmap", "treemap"])
def test_new_chart_types_validate(chart_type):
    cfg = StructuredChartConfig(type=chart_type, x="month", y=["revenue"])
    assert cfg.type == chart_type


@pytest.mark.parametrize("chart_type", ["donut", "radar"])
def test_previously_supported_types_still_validate(chart_type):
    cfg = StructuredChartConfig(type=chart_type, x="month", y=["revenue"])
    assert cfg.type == chart_type


def test_invalid_chart_type_rejected():
    with pytest.raises(ValueError):
        StructuredChartConfig(type="not-a-real-type", x="month", y=["revenue"])


@pytest.mark.parametrize("layout", ["full", "half"])
def test_layout_field_validates(layout):
    cfg = StructuredChartConfig(type="bar", x="month", y=["revenue"], layout=layout)
    assert cfg.layout == layout


def test_layout_defaults_to_none():
    cfg = StructuredChartConfig(type="bar", x="month", y=["revenue"])
    assert cfg.layout is None


def test_invalid_layout_rejected():
    with pytest.raises(ValueError):
        StructuredChartConfig(type="bar", x="month", y=["revenue"], layout="third")
