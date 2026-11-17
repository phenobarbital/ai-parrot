"""FEAT-752 (TASK-4803): run the SuggestionChips vitest from pytest (validation contract)."""

from ._vitest import run_vitest


def test_suggestion_chips_vitest() -> None:
    """Chip row renders, reports clicks, and renders nothing when empty."""
    run_vitest("src/lib/components/agents/SuggestionChips.test.ts")
