"""FEAT-610 TASK-3843 — pie/donut slices carry names (AC4)."""

from __future__ import annotations

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer  # noqa: E402

ROWS = [
    {"course": "Math", "graduates": 5},
    {"course": None, "graduates": 3},
]


def _props(chart_type: str) -> dict:
    return {"type": chart_type, "x": "course", "y": ["graduates"], "data": ROWS}


@pytest.mark.parametrize("chart_type", ["pie", "donut"])
def test_pie_slices_have_names(chart_type: str) -> None:
    option = EChartsRenderer()._build_option(_props(chart_type))
    assert option["series"][0]["data"] == [
        {"name": "Math", "value": 5},
        {"name": "Unassigned", "value": 3},
    ]
    if chart_type == "donut":
        assert option["series"][0]["radius"] == ["40%", "70%"]


def test_bar_series_unchanged() -> None:
    option = EChartsRenderer()._build_option(_props("bar"))
    assert option["series"][0]["data"] == [5, 3]
