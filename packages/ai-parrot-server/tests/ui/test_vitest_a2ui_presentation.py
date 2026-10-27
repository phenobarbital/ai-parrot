"""FEAT-755 (TASK-4768): run the A2UI presentation-marker vitest suite from pytest."""

from ._vitest import run_vitest


def test_a2ui_presentation_vitest() -> None:
    """getPresentation / isInlinePresentation and inferSurfaceKind marker precedence."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/a2ui-presentation.test.ts",
        "src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts",
    )
