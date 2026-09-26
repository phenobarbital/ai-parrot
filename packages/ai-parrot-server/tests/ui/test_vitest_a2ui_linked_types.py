"""FEAT-598 (TASK-3792): run the linked-types vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_a2ui_linked_types_vitest() -> None:
    """getDataSources vitest passes."""
    run_vitest("src/lib/components/agents/canvas/a2ui/linked/types.test.ts")
