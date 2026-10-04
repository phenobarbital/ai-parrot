"""FEAT-623 (TASK-3998): run the admin UI chart-adapter vitest suite from pytest."""

from ._vitest import run_vitest


def test_a2ui_chart_adapter_vitest() -> None:
    """toChartBlockData maps seriesAxes / yAxisLabels losslessly."""
    run_vitest("src/lib/components/agents/canvas/a2ui/a2ui-chart-adapter.test.ts")
