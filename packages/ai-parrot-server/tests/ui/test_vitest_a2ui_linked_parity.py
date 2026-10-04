"""FEAT-611 (TASK-3838): run the Epson Python↔TS parity vitest from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_parity_vitest() -> None:
    """parity.test.ts reproduces the shared epson_dashboard_params.json fixture."""
    run_vitest("src/lib/components/agents/canvas/a2ui/linked/parity.test.ts")
