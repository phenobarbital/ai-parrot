"""FEAT-886 round 4 — ONE shared "finalize then persist" step for every entry point.

The text that is stored / published / hydrated is the text the caller receives, in ``ask``, ``invoke`` and
``conversation`` alike, with a real ``SecretsGuardrail``; a DataFrame output must not break ``ask()``;
PandasAgent goes through the same step and runs the deletion guard.
"""
from __future__ import annotations

import asyncio
import gc
from typing import Any

import pandas as pd
import pytest

from parrot.bots.base import BaseBot
from parrot.bots.data import PandasAgent
from parrot.memory import InMemoryConversation
from parrot.memory.hydration import HydrationSource, SessionDeletedError
from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage

from .test_turn_publish_after_save import SECRET, Client, RecordingPublisher, _SecretClient, _bot


async def _guarded_bot(client: Client) -> BaseBot:
    from parrot.bots.guardrails.base import GuardrailStage
    from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail

    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    bot._guardrail_pipelines[GuardrailStage.OUTPUT].add(SecretsGuardrail())
    bot.llm = client
    return bot


async def _stored(bot: BaseBot):
    history = await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")
    return history.turns[0]


def _assert_clean(bot: BaseBot, response: AIMessage, stored) -> None:
    event = bot.turn_publisher.events[0]
    for text in (
        str(response.output), str(response.response), response.to_text,
        stored.assistant_response, event.turn["assistant_response"], str(event.presentation.get("output")),
        str(event.presentation.get("response")),
    ):
        assert SECRET not in text, text
    assert "REDACTED" in stored.assistant_response and "REDACTED" in event.turn["assistant_response"]


@pytest.mark.parametrize("entry", ["ask", "invoke", "conversation"])
async def test_redaction_reaches_every_field_in_every_entry_point(entry: str):
    bot = await _guarded_bot(_SecretClient())
    if entry == "ask":
        response = await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False)
    elif entry == "invoke":
        response = await bot.invoke("hi", user_id="u", session_id="s")
    else:
        response = await bot.conversation("hi", user_id="u", session_id="s", use_vector_context=False)
    _assert_clean(bot, response, await _stored(bot))
    assert len(bot.turn_publisher.events) == 1


class _WrappedSecretClient(Client):
    """`output != response`: the formatter-style wrapped string embeds the raw secret."""

    def _msg(self, prompt: str) -> AIMessage:
        msg = super()._msg(prompt)
        msg.output = f"your key is API_KEY={SECRET}"
        msg.response = f"<div>your key is API_KEY={SECRET}</div>"
        return msg


@pytest.mark.parametrize("entry", ["ask", "conversation"])
async def test_output_different_from_response_is_redacted_everywhere(entry: str):
    bot = await _guarded_bot(_WrappedSecretClient())
    if entry == "ask":
        response = await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False)
    else:
        response = await bot.conversation("hi", user_id="u", session_id="s", use_vector_context=False)
    stored = await _stored(bot)
    assert SECRET not in response.to_text and SECRET not in stored.assistant_response
    assert SECRET not in bot.turn_publisher.events[0].turn["assistant_response"]


class _DataFrameClient(Client):
    def _msg(self, prompt: str) -> AIMessage:
        msg = super()._msg(prompt)
        msg.output = pd.DataFrame({"a": [1, 2]})
        return msg


async def test_a_dataframe_output_does_not_break_ask_and_is_persisted():
    """Regression: comparing `output` with `response` raised "truth value of a DataFrame is ambiguous"."""
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    bot.llm = _DataFrameClient()
    response = await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False)
    assert isinstance(response.output, pd.DataFrame)
    stored = await _stored(bot)
    assert stored.assistant_response  # the caller-visible text of a DataFrame answer
    assert len(bot.turn_publisher.events) == 1


async def test_a_dataframe_output_works_with_no_persistence_at_all():
    bot = await _bot()
    bot.conversation_memory = None
    bot.llm = _DataFrameClient()
    response = await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False,
                             use_conversation_history=False)
    assert isinstance(response.output, pd.DataFrame)


async def test_a_failing_unit_is_logged_once_and_never_left_unretrieved(caplog):
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    loop = asyncio.get_running_loop()
    seen: list = []
    loop.set_exception_handler(lambda _l, ctx: seen.append(ctx))

    async def boom(*a: Any, **kw: Any):
        raise RuntimeError("store down")

    bot.conversation_memory.add_turn = boom
    with pytest.raises(RuntimeError):
        await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False)
    gc.collect()
    await asyncio.sleep(0)
    assert [c for c in seen if "never retrieved" in str(c.get("message", ""))] == []
    assert any("persisting turn_id" in r.getMessage() for r in caplog.records)


async def test_a_failing_message_added_listener_does_not_fail_the_request():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))

    real_emit = bot.events.emit

    async def emit(event: Any) -> None:
        if type(event).__name__ == "MessageAddedEvent":
            raise RuntimeError("listener down")
        await real_emit(event)

    bot.events.emit = emit
    response = await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False)
    assert response.to_text
    assert len(bot.turn_publisher.events) == 1
    assert len((await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")).turns) == 1


# ── PandasAgent ───────────────────────────────────────────────────────────


class _Source(HydrationSource):
    deleted = False

    async def load_turns(self, *a: Any, **kw: Any):
        return None

    async def is_deleted(self, *a: Any, **kw: Any) -> bool:
        return self.deleted

    async def max_sequence(self, *a: Any, **kw: Any) -> int:
        return 0


class _PandasClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def close(self) -> None:
        return None

    async def ask(self, prompt: str, **kwargs: Any) -> AIMessage:
        return AIMessage(input=prompt, output="ok", response="ok", model="fake", provider="fake",
                         usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0))


def _pandas(use_source: bool = True) -> PandasAgent:
    agent = PandasAgent(name="pd-probe", llm="google:gemini-2.5-flash")
    agent._llm = _PandasClient()  # type: ignore[assignment]
    agent.conversation_memory = InMemoryConversation()
    agent.turn_publisher = RecordingPublisher(agent.conversation_memory, agent.memory_key_id)
    if use_source:
        agent.hydration_source = _Source()
    return agent


async def test_pandas_agent_persists_through_the_shared_step():
    agent = _pandas()
    await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert len(agent.turn_publisher.events) == 1
    history = await agent.conversation_memory.get_history("u", "s", chatbot_id=agent.memory_key_id)
    assert [t.assistant_response for t in history.turns] == ["ok"]


@pytest.mark.parametrize("history", [True, False])
async def test_pandas_agent_refuses_a_deleted_session(history: bool):
    agent = _pandas()
    agent.hydration_source.deleted = True
    with pytest.raises(SessionDeletedError):
        await agent.ask("hola", user_id="u", session_id="s", return_structured=False,
                        use_conversation_history=history)
    assert agent.turn_publisher.events == []


async def test_pandas_agent_save_failure_returns_the_answer_and_is_logged_at_error(caplog):
    agent = _pandas()

    async def boom(*a: Any, **kw: Any):
        raise RuntimeError("store down")

    agent.conversation_memory.add_turn = boom
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert response is not None  # the computed answer is not thrown away (behaviour before FEAT-886)
    assert any(r.levelname == "ERROR" and "persisting turn_id" in r.getMessage() for r in caplog.records)


class _PandasSecretClient(_PandasClient):
    async def ask(self, prompt: str, **kwargs: Any) -> AIMessage:
        text = f"your key is API_KEY={SECRET}"
        return AIMessage(input=prompt, output=text, response=text, model="fake", provider="fake",
                         usage=CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0))


async def test_pandas_agent_persisted_text_carries_an_output_verdict():
    """PandasAgent runs no output pipeline; the text it stores and publishes is still scanned."""
    from parrot.bots.guardrails.base import GuardrailStage
    from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail

    agent = _pandas()
    agent._llm = _PandasSecretClient()  # type: ignore[assignment]
    agent._guardrail_pipelines[GuardrailStage.OUTPUT].add(SecretsGuardrail())
    await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    history = await agent.conversation_memory.get_history("u", "s", chatbot_id=agent.memory_key_id)
    stored = history.turns[0].assistant_response
    published = agent.turn_publisher.events[0].turn["assistant_response"]
    for text in (stored, published):
        assert SECRET not in text, text
        assert "REDACTED" in text, text


def test_voice_saves_run_the_deletion_guard_first():
    """Every `save_conversation_turn` in bots/voice.py is immediately preceded by `_guard_session`."""
    import parrot.bots.voice as voice

    lines = [ln.strip() for ln in open(voice.__file__, encoding="utf-8").read().splitlines()]
    saves = [i for i, ln in enumerate(lines) if ln.startswith("await self.save_conversation_turn(")]
    assert len(saves) == 2
    for i in saves:
        assert lines[i - 1].startswith("await self._guard_session("), lines[i - 1]



@pytest.mark.parametrize("entry", ["invoke", "conversation"])
async def test_the_stored_text_is_the_answer_not_the_markdown_wrapper(entry: str):
    """`get_response` writes a "**Question** / **Answer**" block to `response.response` for the caller;
    the conversation (working memory, bus, next LLM call) keeps the answer itself."""
    bot = await _guarded_bot(_SecretClient())
    call = bot.invoke if entry == "invoke" else bot.conversation
    kwargs = {} if entry == "invoke" else {"use_vector_context": False}
    response = await call("what is the key?", user_id="u", session_id="s", **kwargs)
    stored, event = await _stored(bot), bot.turn_publisher.events[0]
    assert "**Question**" in response.response  # the caller still gets the rendered block
    for text in (stored.assistant_response, event.turn["assistant_response"]):
        assert "**Question**" not in text and "what is the key?" not in text, text
        assert SECRET not in text and "REDACTED" in text


@pytest.mark.parametrize(("entry", "expected_runs"), [("ask", 1), ("invoke", 2), ("conversation", 2)])
async def test_a_passing_response_scans_each_distinct_text_once(entry: str, expected_runs: int):
    """A PASS scans the answer once, and a distinct presentation wrapper (`get_response`'s markdown block) once more.

    `ask()` without a formatter has no wrapper, so it still runs the OUTPUT guardrails exactly once.
    """
    from parrot.bots.guardrails.base import GuardrailStage

    bot = await _guarded_bot(Client())  # no secret in the answer: the verdict is PASS
    pipeline = bot._guardrail_pipelines[GuardrailStage.OUTPUT]
    runs, real_run = [], pipeline.run

    async def counting_run(content, ctx):
        runs.append(content)
        return await real_run(content, ctx)

    pipeline.run = counting_run
    if entry == "ask":
        await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False)
    elif entry == "invoke":
        await bot.invoke("hi", user_id="u", session_id="s")
    else:
        await bot.conversation("hi", user_id="u", session_id="s", use_vector_context=False)
    assert len(runs) == expected_runs, runs
    assert "**Question**" not in runs[0], runs
    if expected_runs == 2:
        assert "**Question**" in runs[1], runs


def _passing_message(response: str) -> AIMessage:
    return AIMessage(
        input="hi",
        output="reply",
        response=response,
        model="stub",
        provider="stub",
        usage=CompletionUsage(prompt_tokens=0, completion_tokens=0),
    )


async def test_a_passing_output_still_scans_its_wrapper():
    """issue:a20713dc67a6 — the answer passes, but the wrapper `to_text` prefers carries a secret the answer lacks."""
    bot = await _guarded_bot(Client())
    response = await bot._run_output_pipeline(_passing_message(f"<div>reply API_KEY={SECRET}</div>"), method="ask")
    assert response.output == "reply"
    assert SECRET not in response.response and SECRET not in response.to_text, response.response
    assert "REDACTED" in response.response


@pytest.mark.parametrize("entry", ["invoke", "conversation"])
async def test_a_question_echoed_in_the_markdown_wrapper_is_redacted(entry: str):
    """`get_response` echoes the question in its "**Question**" block: the answer passes, the echo is still scanned."""
    bot = await _guarded_bot(Client())
    call = bot.invoke if entry == "invoke" else bot.conversation
    kwargs = {} if entry == "invoke" else {"use_vector_context": False}
    response = await call(f"my key is API_KEY={SECRET}", user_id="u", session_id="s", **kwargs)
    assert "**Question**" in response.response  # the caller still gets the rendered block
    assert SECRET not in response.response and SECRET not in response.to_text, response.response


async def test_a_blocked_wrapper_falls_back_to_the_passing_output():
    """A wrapper the OUTPUT guardrails block is replaced by the answer that passed; the response is not blocked."""
    from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailResult, GuardrailStage

    class BlockDiv(Guardrail):
        name = "block_div"
        stages = {GuardrailStage.OUTPUT}
        priority = 50
        on_error = "fail_closed"

        async def check(self, content: str, ctx: Any) -> GuardrailResult:
            if "<div>" in content:
                return GuardrailResult(action=GuardrailAction.BLOCK, reason="div")
            return GuardrailResult(action=GuardrailAction.PASS)

    bot = await _bot()
    bot._guardrail_pipelines[GuardrailStage.OUTPUT].add(BlockDiv())
    response = await bot._run_output_pipeline(_passing_message("<div>reply</div>"), method="ask")
    assert response.output == "reply"
    assert response.response == "reply"
    assert "error" not in response.metadata


class _ExplanationSecretClient(Client):
    """A structured (non-text) output that passes untouched, and a separate text answer carrying a secret."""

    def _msg(self, prompt: str) -> AIMessage:
        message = super()._msg(prompt)
        message.output = {"html": "<b>chart</b>"}
        message.response = f"your key is API_KEY={SECRET}"
        return message


async def test_text_the_pipeline_never_scanned_is_still_redacted_before_it_is_persisted():
    bot = await _guarded_bot(_ExplanationSecretClient())
    await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False)
    stored, event = await _stored(bot), bot.turn_publisher.events[0]
    for text in (stored.assistant_response, event.turn["assistant_response"]):
        assert SECRET not in text and "REDACTED" in text, text

