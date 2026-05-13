"""Unit tests for synthesize_results util — FEAT-163 TASK-1063.

Tests verify:
- synthesize_results is importable from synthesis.py and from storage package.
- Returns a non-empty string when a synthesis_client is available.
- Uses SYNTHESIS_PROMPT as the basis for the LLM call.
- Raises RuntimeError when ctx.synthesis_client is None.
- Sets result.summary with the returned string.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.flows.core.storage.synthesis import (
    SYNTHESIS_PROMPT,
    synthesize_results,
)
from parrot.bots.flows.core.storage import synthesize_results as sr_from_pkg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubResult:
    """Minimal FlowResult-like stub for testing."""

    def __init__(self) -> None:
        self.responses = {"agent_a": "found data", "agent_b": "analyzed it"}
        self.errors: dict = {}
        self.nodes: list = []
        self.status = "completed"
        self.summary: str = ""


class StubCtx:
    """Minimal FlowContext stub with a configurable synthesis_client."""

    def __init__(self, client: object) -> None:
        self.synthesis_client = client


# ---------------------------------------------------------------------------
# Import / API surface
# ---------------------------------------------------------------------------


class TestSynthesizeResultsImport:
    def test_importable_from_synthesis_module(self) -> None:
        assert callable(synthesize_results)

    def test_importable_from_storage_package(self) -> None:
        assert callable(sr_from_pkg)
        assert sr_from_pkg is synthesize_results


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSynthesizeResults:
    async def test_returns_string_with_client(self) -> None:
        response = MagicMock()
        response.content = "summary text"
        client = AsyncMock()
        client.ask = AsyncMock(return_value=response)
        ctx = StubCtx(client=client)

        out = await synthesize_results(ctx, StubResult())

        assert isinstance(out, str)
        assert out  # non-empty

    async def test_returns_client_content(self) -> None:
        response = MagicMock()
        response.content = "comprehensive summary"
        client = AsyncMock()
        client.ask = AsyncMock(return_value=response)
        ctx = StubCtx(client=client)

        out = await synthesize_results(ctx, StubResult())

        assert out == "comprehensive summary"

    async def test_uses_synthesis_prompt(self) -> None:
        response = MagicMock()
        response.content = "summary"
        client = AsyncMock()
        client.ask = AsyncMock(return_value=response)
        ctx = StubCtx(client=client)

        await synthesize_results(ctx, StubResult())

        client.ask.assert_called_once()
        call_kwargs = client.ask.call_args.kwargs
        prompt = call_kwargs.get("question") or call_kwargs.get("prompt", "")
        # Some token of SYNTHESIS_PROMPT must appear in the assembled prompt
        assert "research findings" in prompt.lower() or "specialist" in prompt.lower()

    async def test_sets_result_summary(self) -> None:
        response = MagicMock()
        response.content = "my summary"
        client = AsyncMock()
        client.ask = AsyncMock(return_value=response)
        ctx = StubCtx(client=client)
        result = StubResult()

        await synthesize_results(ctx, result)

        assert result.summary == "my summary"

    async def test_handles_response_without_content_attr(self) -> None:
        """If the LLM response has no .content, str() is used."""
        client = AsyncMock()
        client.ask = AsyncMock(return_value="raw string response")
        ctx = StubCtx(client=client)

        out = await synthesize_results(ctx, StubResult())

        assert isinstance(out, str)
        assert out  # non-empty


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


class TestSynthesizeResultsErrors:
    async def test_raises_without_client(self) -> None:
        ctx = StubCtx(client=None)
        with pytest.raises(RuntimeError, match="No synthesis client"):
            await synthesize_results(ctx, StubResult())

    async def test_raises_when_no_synthesis_client_attr(self) -> None:
        class NoClientCtx:
            pass

        with pytest.raises((RuntimeError, AttributeError)):
            await synthesize_results(NoClientCtx(), StubResult())  # type: ignore[arg-type]
