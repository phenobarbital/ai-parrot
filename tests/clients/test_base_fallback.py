from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.clients.base import AbstractClient
from parrot.memory.abstract import ConversationHistory, ConversationTurn


class _ConcreteClient(AbstractClient):
    """Minimal concrete subclass for testing base class methods."""

    async def get_client(self):
        return None

    async def ask(self, *args, **kwargs):
        raise NotImplementedError

    async def ask_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def resume(self, *args, **kwargs):
        raise NotImplementedError

    async def invoke(self, *args, **kwargs):
        raise NotImplementedError


def _make_client(**attrs):
    """Create a minimal AbstractClient instance for testing."""
    client = _ConcreteClient.__new__(_ConcreteClient)
    client._fallback_model = None
    for key, value in attrs.items():
        setattr(client, key, value)
    return client


class TestIsCapacityError:
    def test_detects_429(self):
        client = _make_client()
        error = Exception("Error code: 429 - Rate limit exceeded")
        assert client._is_capacity_error(error) is True

    def test_detects_503(self):
        client = _make_client()
        error = Exception("503 Service Unavailable")
        assert client._is_capacity_error(error) is True

    def test_detects_overloaded(self):
        client = _make_client()
        error = Exception("The model is currently overloaded")
        assert client._is_capacity_error(error) is True

    def test_detects_rate_limit(self):
        client = _make_client()
        error = Exception("rate limit exceeded for this model")
        assert client._is_capacity_error(error) is True

    def test_detects_rate_limit_underscore(self):
        client = _make_client()
        error = Exception("rate_limit_exceeded")
        assert client._is_capacity_error(error) is True

    def test_detects_high_demand(self):
        client = _make_client()
        error = Exception("Model under high demand, please retry")
        assert client._is_capacity_error(error) is True

    def test_detects_too_many_requests(self):
        client = _make_client()
        error = Exception("Too many requests")
        assert client._is_capacity_error(error) is True

    def test_detects_service_unavailable(self):
        client = _make_client()
        error = Exception("Service unavailable right now")
        assert client._is_capacity_error(error) is True

    def test_ignores_auth_error(self):
        client = _make_client()
        error = Exception("401 Unauthorized - Invalid API key")
        assert client._is_capacity_error(error) is False

    def test_ignores_bad_request(self):
        client = _make_client()
        error = Exception("400 Bad Request - Invalid parameters")
        assert client._is_capacity_error(error) is False

    def test_ignores_not_found(self):
        client = _make_client()
        error = Exception("404 Not Found - Model does not exist")
        assert client._is_capacity_error(error) is False


class TestShouldUseFallback:
    def test_returns_true_when_conditions_met(self):
        client = _make_client(_fallback_model="fallback-model")
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("primary-model", error) is True

    def test_returns_false_when_no_fallback_model(self):
        client = _make_client(_fallback_model=None)
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("primary-model", error) is False

    def test_returns_false_when_same_model(self):
        client = _make_client(_fallback_model="same-model")
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("same-model", error) is False

    def test_returns_false_when_not_capacity_error(self):
        client = _make_client(_fallback_model="fallback-model")
        error = Exception("401 Unauthorized")
        assert client._should_use_fallback("primary-model", error) is False

    def test_returns_false_when_empty_string_fallback(self):
        client = _make_client(_fallback_model="")
        error = Exception("429 Rate limit exceeded")
        assert client._should_use_fallback("primary-model", error) is False


class TestPrepareConversationContext:
    """Code-review regression tests (FEAT-302): _prepare_conversation_context()
    previously built the current-turn message twice and, when a
    conversation history was present, replayed every historical turn
    twice too — with the current turn placed *before* the historical
    replay instead of after it. These tests pin down the corrected,
    non-duplicated, correctly-ordered behavior. This is shared
    AbstractClient infrastructure used by every provider (Anthropic,
    OpenAI, Google, Groq, Bedrock, ...), not Bedrock-specific.
    """

    def _client_with_memory(self, history: "ConversationHistory | None"):
        client = _make_client(logger=MagicMock())
        client.conversation_memory = MagicMock()
        client.conversation_memory.get_history = AsyncMock(return_value=history)
        client.conversation_memory.create_history = AsyncMock(return_value=history)
        return client

    @pytest.mark.asyncio
    async def test_no_history_single_current_message_no_duplication(self):
        """Without user_id/session_id, exactly one message is produced —
        not two identical ones."""
        client = self._client_with_memory(None)
        messages, history, system_prompt = await client._prepare_conversation_context(
            "Hello", None, None, None, None
        )
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert history is None

    @pytest.mark.asyncio
    async def test_with_history_no_duplication_and_correct_order(self):
        """With a conversation history, historical turns come first, the
        current turn comes last — each appearing exactly once."""
        history = ConversationHistory(
            session_id="s1",
            user_id="u1",
            turns=[
                ConversationTurn(
                    turn_id="t1", user_id="u1",
                    user_message="What's 2+2?", assistant_response="4",
                ),
            ],
        )
        client = self._client_with_memory(history)
        messages, returned_history, system_prompt = await client._prepare_conversation_context(
            "And 3+3?", None, "u1", "s1", None
        )

        # Exactly 3 messages: [history_user, history_assistant, current_user]
        # — not 5 (the old bug duplicated both the history turn and the
        # current message).
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"

        # The LAST message must be the *current* turn, not a repeat of history.
        current_text = messages[2]["content"]
        if isinstance(current_text, list):
            current_text = "".join(
                b.get("text", "") for b in current_text if isinstance(b, dict)
            )
        assert "3+3" in current_text
        assert returned_history is history

    @pytest.mark.asyncio
    async def test_system_prompt_generated_from_history_when_not_stateless(self):
        history = ConversationHistory(
            session_id="s1",
            user_id="u1",
            turns=[
                ConversationTurn(
                    turn_id="t1", user_id="u1",
                    user_message="hi", assistant_response="hello",
                ),
            ],
        )
        client = self._client_with_memory(history)
        _messages, _history, system_prompt = await client._prepare_conversation_context(
            "next question", None, "u1", "s1", None, stateless=False
        )
        assert system_prompt is not None
        assert "hi" in system_prompt and "hello" in system_prompt

    @pytest.mark.asyncio
    async def test_stateless_skips_system_prompt_generation(self):
        history = ConversationHistory(
            session_id="s1",
            user_id="u1",
            turns=[
                ConversationTurn(
                    turn_id="t1", user_id="u1",
                    user_message="hi", assistant_response="hello",
                ),
            ],
        )
        client = self._client_with_memory(history)
        messages, _history, system_prompt = await client._prepare_conversation_context(
            "next question", None, "u1", "s1", None, stateless=True
        )
        # History is still included in messages (stateless only skips the
        # system-prompt-from-history generation), current turn still last.
        assert len(messages) == 3
        assert system_prompt is None

    @pytest.mark.asyncio
    async def test_missing_file_logs_and_skips_instead_of_raising(self):
        client = self._client_with_memory(None)
        messages, _history, _system_prompt = await client._prepare_conversation_context(
            "Hello", ["/nonexistent/path/does-not-exist.txt"], None, None, None
        )
        # No exception raised; the missing file was skipped (no attachment
        # block appended, message content is text-only).
        assert len(messages) == 1
        client.logger.error.assert_called()
