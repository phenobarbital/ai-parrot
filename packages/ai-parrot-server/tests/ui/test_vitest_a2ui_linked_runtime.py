"""FEAT-598 (TASK-3794): run the linked fetch / scheduler / ref vitest suites from pytest."""

from ._vitest import run_vitest


def test_a2ui_linked_runtime_vitest() -> None:
    """fetch.ts, scheduler.ts and ref.ts suites pass."""
    run_vitest(
        "src/lib/components/agents/canvas/a2ui/linked/fetch.test.ts",
        "src/lib/components/agents/canvas/a2ui/linked/scheduler.test.ts",
        "src/lib/components/agents/canvas/a2ui/linked/ref.test.ts",
    )
