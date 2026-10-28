"""FEAT-752 (TASK-4804): run the chip wiring vitests from pytest (validation contract)."""

from ._vitest import run_vitest


def test_suggestion_chat_wiring_vitest() -> None:
    """Chips render under assistant bubbles only; clicks route to send (output_mode) or explain (turn_id + data)."""
    run_vitest(
        "src/lib/components/agents/ChatBubble.test.ts",
        "src/lib/components/agents/AgentChat.test.ts",
    )
