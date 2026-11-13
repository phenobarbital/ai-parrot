"""FEAT-893 — `PandasAgent.ask` gives the answer it returns an OUTPUT guardrail verdict.

`PandasAgent.ask` is a full override that never reaches `BaseBot.ask`. Before FEAT-893 it never ran the OUTPUT
stage, so a secret in the answer reached the caller unredacted (issue:3e29dbe2f16a). These tests drive the real
`ask()` with a stub client and a real `SecretsGuardrail`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional

from parrot.bots.abstract import _OUTPUT_BLOCKED_TEXT
from parrot.bots.data import PandasAgent, PandasAgentResponse
from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail
from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage

from .test_finalize_persist_turn import _pandas, _PandasClient
from .test_turn_publish_after_save import SECRET

SECRET_TEXT = f"your key is API_KEY={SECRET}"


def _usage() -> CompletionUsage:
    return CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


class _TextSecretClient(_PandasClient):
    """Answers in plain text: the secret is in both ``output`` and ``response``."""

    async def ask(self, prompt: str, **kwargs: Any) -> AIMessage:
        return AIMessage(
            input=prompt, output=SECRET_TEXT, response=SECRET_TEXT, model="fake", provider="fake", usage=_usage()
        )


class _StructuredSecretClient(_PandasClient):
    """Answers with a structured `PandasAgentResponse` whose explanation carries the secret."""

    async def ask(self, prompt: str, **kwargs: Any) -> AIMessage:
        structured = PandasAgentResponse(explanation=SECRET_TEXT)
        return AIMessage(
            input=prompt,
            output=structured,
            structured_output=structured,
            model="fake",
            provider="fake",
            usage=_usage(),
        )


class _CountingGuardrail(Guardrail):
    """OUTPUT observer that records every text it is asked to judge."""

    name = "counting"
    stages = {GuardrailStage.OUTPUT}
    priority = 200

    def __init__(self) -> None:
        self.seen: List[str] = []

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        self.seen.append(content)
        return GuardrailResult(action=GuardrailAction.PASS)


class _BlockingGuardrail(Guardrail):
    """OUTPUT guardrail that blocks any answer mentioning an API key."""

    name = "blocking"
    stages = {GuardrailStage.OUTPUT}
    priority = 100

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        if "API_KEY" in content:
            return GuardrailResult(action=GuardrailAction.BLOCK, reason="api_key")
        return GuardrailResult(action=GuardrailAction.PASS)


def _agent(client: _PandasClient, *guardrails: Guardrail) -> PandasAgent:
    agent = _pandas()
    agent._llm = client  # type: ignore[assignment]
    for guardrail in guardrails:
        agent._guardrail_pipelines[GuardrailStage.OUTPUT].add(guardrail)
    return agent


def _answer_fields(response: AIMessage) -> List[str]:
    fields = [str(response.output), str(response.response), str(response.content), response.to_text]
    for candidate in (response.output, response.structured_output):
        if isinstance(candidate, PandasAgentResponse):
            fields.append(candidate.explanation)
    return fields


async def test_text_answer_is_redacted_for_the_caller():
    agent = _agent(_TextSecretClient(), SecretsGuardrail())
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    for text in _answer_fields(response):
        assert SECRET not in text, text
    assert "REDACTED" in response.response
    assert "REDACTED" in response.output


async def test_structured_answer_explanation_is_redacted():
    agent = _agent(_StructuredSecretClient(), SecretsGuardrail())
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert isinstance(response.output, PandasAgentResponse)
    for text in _answer_fields(response):
        assert SECRET not in text, text
    assert "REDACTED" in response.response
    assert "REDACTED" in response.output.explanation


async def test_answer_memory_and_persisted_turn_get_the_judged_text():
    agent = _agent(_StructuredSecretClient(), SecretsGuardrail())
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    remembered = await agent.answer_memory.get(response.turn_id)
    history = await agent.conversation_memory.get_history("u", "s", chatbot_id=agent.memory_key_id)
    stored = history.turns[0].assistant_response
    published = agent.turn_publisher.events[0].turn["assistant_response"]
    for text in (str(remembered["answer"]), stored, published):
        assert SECRET not in text, text
        assert "REDACTED" in text, text


async def test_persistence_does_not_rescan():
    counting = _CountingGuardrail()
    agent = _agent(_TextSecretClient(), counting)
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert response.response == SECRET_TEXT
    # output and response are the same text: one verdict, reused for the caller, answer_memory and persistence.
    assert counting.seen == [SECRET_TEXT]


async def test_structured_answer_is_judged_once_per_distinct_text():
    counting = _CountingGuardrail()
    agent = _agent(_StructuredSecretClient(), counting)
    await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    # The structured output is not text: only the explanation is judged, once, although it is also
    # response.response, the remembered answer and the persisted turn.
    assert counting.seen == [SECRET_TEXT]


async def test_block_replaces_every_answer_field():
    agent = _agent(_StructuredSecretClient(), _BlockingGuardrail())
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert response.response == _OUTPUT_BLOCKED_TEXT
    assert response.output.explanation == _OUTPUT_BLOCKED_TEXT
    assert response.metadata["error"] == "security_block"
    assert response.metadata["block_reason"] == "api_key"
    for text in _answer_fields(response):
        assert SECRET not in text, text


async def test_block_on_text_output_uses_the_pipeline_notice():
    agent = _agent(_TextSecretClient(), _BlockingGuardrail())
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert response.output == _OUTPUT_BLOCKED_TEXT
    assert response.response == _OUTPUT_BLOCKED_TEXT
    assert response.metadata["error"] == "security_block"
    history = await agent.conversation_memory.get_history("u", "s", chatbot_id=agent.memory_key_id)
    assert history.turns[0].assistant_response == _OUTPUT_BLOCKED_TEXT


async def test_early_return_path_is_guarded():
    """The interactive-artifact early return bypasses the formatter and must still be judged."""
    agent = _agent(_TextSecretClient(), SecretsGuardrail())
    envelope = SimpleNamespace(a2ui_envelope=None, artifact_id="art-1", enhanced=False)

    def _finalize(response: AIMessage, _envelope: Any) -> Optional[str]:
        explanation = response.response
        response.output = "<html><body>chart</body></html>"
        response.response = explanation
        return explanation

    agent._extract_last_interactive_result = lambda tool_calls: envelope  # type: ignore[method-assign]
    agent._finalize_interactive_response = _finalize  # type: ignore[method-assign]
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert response.output == "<html><body>chart</body></html>"
    assert SECRET not in response.response
    assert "REDACTED" in response.response
    assert SECRET not in response.to_text


async def test_no_guardrails_leaves_the_answer_untouched():
    agent = _agent(_TextSecretClient())
    response = await agent.ask("hola", user_id="u", session_id="s", return_structured=False)
    assert response.response == SECRET_TEXT
    assert response.output == SECRET_TEXT
    assert "guardrails" not in response.metadata
    assert "error" not in response.metadata
