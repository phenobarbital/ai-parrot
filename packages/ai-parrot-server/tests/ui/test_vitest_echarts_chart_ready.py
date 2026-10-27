"""FEAT-754 (TASK-4790): run the ECharts onChartReady vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_echarts_chart_ready_vitest() -> None:
    """ECharts onChartReady lifecycle vitest passes."""
    run_vitest("src/lib/components/visualizations/ECharts.test.ts")
