"""Integration tests: groundedness scoring wired through `ask()` / `ask_stream()`
(FEAT-398, TASK-2044).

Exercises the full seam: `enable_groundedness=True` bot kwarg ->
`GroundednessGuardrail` registered on the OUTPUT `GuardrailPipeline` ->
`_run_output_pipeline` (called from both `ask()` and `ask_stream()`) ->
`AIMessage.metadata["guardrails"]["groundedness"]`. Mirrors the
`_wire_fake_llm` / `_patched_bot` pattern already established by
`tests/unit/test_guardrails_input_migration.py` (TASK-2028) and
`tests/integration/test_guardrails_output.py` (TASK-2029) — no real LLM
call, no real vector store/DB.
"""
from unittest.mock import MagicMock, patch

import pytest

from parrot.bots.basic import BasicBot
from parrot.models import AIMessage, CompletionUsage
from parrot.models.basic import ToolCall


def _patched_bot(**kwargs) -> BasicBot:
    """Construct a BasicBot without loading the real pytector model."""
    with patch(
        "parrot.bots.guardrails.builtin.prompt_injection._get_shared_injection_detector"
    ) as mock_get_shared:
        mock_get_shared.return_value = MagicMock()
        return BasicBot(name="TestBot", injection_detection=False, **kwargs)


def _evidence_tool_calls() -> list[ToolCall]:
    return [
        ToolCall(
            id="1",
            name="sales_lookup",
            arguments={},
            result="Q3 revenue was $1,243,500 across 4,812 orders.",
        )
    ]


class _FakeAsyncClient:
    """Minimal async-context-manager LLM client stand-in with `ask_stream`."""

    def __init__(self, chunks, final_message):
        self._chunks = chunks
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def ask_stream(self, **kwargs):
        for chunk in self._chunks:
            yield chunk
        if self._final_message is not None:
            yield self._final_message


class TestAskEndToEnd:
    @pytest.mark.asyncio
    async def test_ask_end_to_end(self):
        """`ask()` returns an AIMessage carrying the groundedness report."""
        bot = _patched_bot(enable_groundedness=True)

        async def _fake_execute(client, method, **llm_kwargs):
            return AIMessage(
                input=llm_kwargs.get("prompt", ""),
                output="Q3 revenue was $1,243,500.",
                model="fake-model",
                provider="fake-provider",
                usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                session_id="s1",
                tool_calls=_evidence_tool_calls(),
            )

        bot.get_client = MagicMock(return_value=_FakeAsyncClient([], None))
        bot.execute_llm_call = _fake_execute

        result = await bot.ask(
            "What was the revenue?",
            use_conversation_history=False,
            use_vector_context=False,
            use_tools=False,
        )

        report = result.metadata.get("guardrails", {}).get("groundedness")
        assert report is not None
        assert report["score"] >= 0.0
        assert report["score"] == 1.0
        assert result.output == "Q3 revenue was $1,243,500."

    @pytest.mark.asyncio
    async def test_default_off(self):
        """Without `enable_groundedness`, no report and no scoring cost."""
        bot = _patched_bot(enable_groundedness=False)

        async def _fake_execute(client, method, **llm_kwargs):
            return AIMessage(
                input=llm_kwargs.get("prompt", ""),
                output="Q3 revenue was $1,243,500.",
                model="fake-model",
                provider="fake-provider",
                usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                session_id="s1",
                tool_calls=_evidence_tool_calls(),
            )

        bot.get_client = MagicMock(return_value=_FakeAsyncClient([], None))
        bot.execute_llm_call = _fake_execute

        result = await bot.ask(
            "What was the revenue?",
            use_conversation_history=False,
            use_vector_context=False,
            use_tools=False,
        )

        assert "groundedness" not in result.metadata.get("guardrails", {})
        # Scoring-only invariant: response text is unaffected either way.
        assert result.output == "Q3 revenue was $1,243,500."


class TestAskStreamEndToEnd:
    @pytest.mark.asyncio
    async def test_ask_stream_end_to_end(self):
        """`ask_stream()`'s final yielded AIMessage carries the report."""
        bot = _patched_bot(enable_groundedness=True)

        final_message = AIMessage(
            input="What was the revenue?",
            output="Q3 revenue was $1,243,500.",
            response="Q3 revenue was $1,243,500.",
            model="fake-model",
            provider="fake-provider",
            usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            session_id="s1",
            tool_calls=_evidence_tool_calls(),
        )
        bot._llm = _FakeAsyncClient(
            ["Q3 revenue ", "was $1,243,500."], final_message,
        )

        messages = []
        async for msg in bot.ask_stream(
            "What was the revenue?",
            use_conversation_history=False,
            use_vector_context=False,
        ):
            messages.append(msg)

        assert isinstance(messages[-1], AIMessage)
        final = messages[-1]
        report = final.metadata.get("guardrails", {}).get("groundedness")
        assert report is not None
        assert report["score"] == 1.0

    @pytest.mark.asyncio
    async def test_ask_stream_default_off_no_report(self):
        bot = _patched_bot(enable_groundedness=False)

        final_message = AIMessage(
            input="What was the revenue?",
            output="Q3 revenue was $1,243,500.",
            response="Q3 revenue was $1,243,500.",
            model="fake-model",
            provider="fake-provider",
            usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            session_id="s1",
            tool_calls=_evidence_tool_calls(),
        )
        bot._llm = _FakeAsyncClient(
            ["Q3 revenue ", "was $1,243,500."], final_message,
        )

        messages = []
        async for msg in bot.ask_stream(
            "What was the revenue?",
            use_conversation_history=False,
            use_vector_context=False,
        ):
            messages.append(msg)

        final = messages[-1]
        assert isinstance(final, AIMessage)
        assert "groundedness" not in final.metadata.get("guardrails", {})
