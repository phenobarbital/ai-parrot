from unittest.mock import AsyncMock, MagicMock

import json
import pytest
from parrot.clients.base import AbstractClient
from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.render import render_history


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


class TestBuildMessages:
    """Regression tests for ``AbstractClient._build_messages`` (FEAT-302, FEAT-524).

    FEAT-302 fixed a bug in the old ``_prepare_conversation_context()``: it built
    the current-turn message twice and, when a conversation history was present,
    replayed every historical turn twice too — with the current turn placed
    *before* the historical replay instead of after it. FEAT-524 removed that
    method (clients no longer load history at all), so these tests now pin the
    same non-duplication and ordering guarantees on its replacement,
    ``_build_messages(prompt, files, history)``. This is shared AbstractClient
    infrastructure used by every provider, not Bedrock-specific.
    """

    @staticmethod
    def _rendered(*pairs):
        """Render ``(user, assistant)`` pairs the way the bot would."""
        history = ConversationHistory(session_id="s1", user_id="u1", turns=[
            ConversationTurn(
                turn_id=f"t{i}", user_id="u1",
                user_message=user, assistant_response=assistant,
            )
            for i, (user, assistant) in enumerate(pairs)
        ])
        return render_history(history)

    def test_no_history_single_current_message_no_duplication(self):
        """Without history, exactly one message is produced — not two identical."""
        client = _make_client(logger=MagicMock())

        messages = client._build_messages("Hello", None, None)

        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_with_history_no_duplication_and_correct_order(self):
        """Historical turns come first, the current turn last, each exactly once."""
        client = _make_client(logger=MagicMock())

        messages = client._build_messages(
            "And 3+3?", None, self._rendered(("What's 2+2?", "4"))
        )

        # Exactly 3 messages: [history_user, history_assistant, current_user] —
        # not 5, which is what the pre-FEAT-302 duplication produced.
        assert [m["role"] for m in messages] == ["user", "assistant", "user"]

        current_text = messages[2]["content"]
        if isinstance(current_text, list):
            current_text = "".join(
                b.get("text", "") for b in current_text if isinstance(b, dict)
            )
        assert "3+3" in current_text
        # And the history text appears exactly once across the whole payload.
        assert json.dumps(messages).count("2+2") == 1

    def test_multi_turn_history_order_is_chronological(self):
        """Several turns keep their order, with the current turn appended last."""
        client = _make_client(logger=MagicMock())

        messages = client._build_messages(
            "third", None, self._rendered(("first", "a1"), ("second", "a2"))
        )

        texts = ["".join(b["text"] for b in m["content"]) for m in messages]
        assert texts == ["first", "a1", "second", "a2", "third"]

    def test_empty_history_behaves_like_none(self):
        """An empty rendered history is not an empty leading message."""
        client = _make_client(logger=MagicMock())

        assert client._build_messages("Hello", None, []) == client._build_messages(
            "Hello", None, None
        )

    def test_no_system_prompt_is_synthesized_from_history(self):
        """FEAT-524: history never becomes system-prompt prose any more.

        The removed helper used to return a synthesized
        "You have access to the following conversation history..." system
        prompt. ``_build_messages`` returns messages only — the caller's system
        prompt passes through untouched.
        """
        client = _make_client(logger=MagicMock())

        result = client._build_messages("next", None, self._rendered(("hi", "hello")))

        assert isinstance(result, list)
        assert all(set(m) == {"role", "content"} for m in result)

    def test_missing_file_logs_and_skips_instead_of_raising(self):
        """A nonexistent attachment is logged and skipped, never raised."""
        client = _make_client(logger=MagicMock())

        messages = client._build_messages(
            "Hello", ["/nonexistent/path/does-not-exist.txt"], None
        )

        # No exception; the missing file was skipped, leaving a text-only message.
        assert len(messages) == 1
        assert messages[0]["content"] == [{"type": "text", "text": "Hello"}]
        client.logger.error.assert_called()
