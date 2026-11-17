"""FEAT-752 (TASK-4812): run the Agent Studio chip-settings vitests from pytest (validation contract)."""

from ._vitest import run_vitest


def test_studio_suggestion_fields_vitest() -> None:
    """Defaults, validation and the Capabilities-tab group for the five chip settings."""
    run_vitest(
        "src/lib/agents/fields.test.ts",
        "src/pages/agents/form/TabsCapabilities.test.ts",
    )
