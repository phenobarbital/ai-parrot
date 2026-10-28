"""FEAT-752 (TASK-4808): run the stream-trailer vitests from pytest (validation contract)."""

from ._vitest import run_vitest


def test_suggestion_stream_trailer_vitest() -> None:
    """done is yielded before EOF when a trailer frame follows; chips patch the finished bubble."""
    run_vitest(
        "src/lib/api/stream.test.ts",
        "src/lib/components/agents/AgentChat.test.ts",
    )
