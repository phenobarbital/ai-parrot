"""FEAT-623 (TASK-3996): run the TS display-format parity suite from pytest."""

from ._vitest import run_vitest


def test_a2ui_format_parity() -> None:
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/a2ui-format.parity.test.ts",
        "src/lib/components/agents/canvas/a2ui/a2ui-format.test.ts",
    )
