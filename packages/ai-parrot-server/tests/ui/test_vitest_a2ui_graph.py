"""FEAT-754 (TASK-4791): run the A2UIGraph vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_a2ui_graph_vitest() -> None:
    """A2UIGraph option/frame vitest passes."""
    run_vitest("src/lib/components/agents/canvas/a2ui/A2UIGraph.test.ts")
