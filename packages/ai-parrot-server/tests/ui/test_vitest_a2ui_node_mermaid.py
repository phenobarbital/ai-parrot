"""FEAT-753 (TASK-4781): run the MermaidDiagram vitest suite(s) from pytest."""

from ._vitest import run_vitest


def test_a2ui_node_mermaid_vitest() -> None:
    """MermaidDiagram UI behaviour passes and the existing A2UI suites stay green."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/A2UINode.test.ts",
        "src/lib/components/agents/canvas/a2ui/a2ui-kind.test.ts",
    )
