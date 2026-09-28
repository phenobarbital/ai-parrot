"""FEAT-598 (TASK-3795): run the linked-surface lane vitest (plus the untouched baked suites) from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_surface_vitest() -> None:
    """Linked lane behaviour passes and the existing baked A2UI suites stay green (AC11)."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/A2UISurface.linked.test.ts",
        "src/lib/components/agents/canvas/a2ui/A2UISurface.test.ts",
        "src/lib/components/agents/canvas/a2ui/A2UINode.test.ts",
    )
