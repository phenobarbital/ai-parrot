"""FEAT-611 (TASK-3836): run the admin-canvas linked-surface vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_a2ui_canvas_linked_vitest() -> None:
    """Linked roots open the a2ui canvas with persistedSurfaceId; existing canvas decision table stays green."""
    run_vitest(
        "src/lib/components/agents/canvas/infographic-tab-builder.test.ts",
        "src/lib/components/agents/AgentChat.a2ui-canvas.test.ts",
        "src/lib/components/agents/canvas/InfographicCanvas.a2ui.test.ts",
        "src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts",
    )
