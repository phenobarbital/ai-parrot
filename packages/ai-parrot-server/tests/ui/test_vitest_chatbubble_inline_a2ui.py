"""FEAT-755 (TASK-4769): run the ChatBubble inline-A2UI vitest suite from pytest."""

from ._vitest import run_vitest


def test_chatbubble_inline_a2ui_vitest() -> None:
    """ChatBubble mounts A2UISurface for an inline A2UI message under features.a2ui."""
    run_vitest(
        "src/lib/components/agents/ChatBubble.test.ts",
    )
