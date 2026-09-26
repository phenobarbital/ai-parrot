"""FEAT-598 (TASK-3793): run the TS DSL + conditions golden suites from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_dsl_vitest() -> None:
    """dsl.ts and conditions.ts pass every shared contract fixture."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/linked/dsl.test.ts",
        "src/lib/components/agents/canvas/a2ui/linked/conditions.test.ts",
    )