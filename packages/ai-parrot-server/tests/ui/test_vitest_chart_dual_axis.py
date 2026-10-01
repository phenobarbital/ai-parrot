"""FEAT-623 (TASK-3999): run the AppChart dual-axis helper vitest suite from pytest."""

from ._vitest import run_vitest


def test_chart_dual_axis_vitest() -> None:
    """splitByAxis / axisDomain follow AppChart's domain rules."""
    run_vitest("src/lib/components/charts/dual-axis.test.ts")
