"""FEAT-610 (TASK-3844): run the LinkedLane.refreshSource vitest suite from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_refresh_vitest() -> None:
    """refreshSource re-fetches one key; refreshAll unchanged."""
    run_vitest("src/lib/components/agents/canvas/a2ui/linked/index.test.ts")
