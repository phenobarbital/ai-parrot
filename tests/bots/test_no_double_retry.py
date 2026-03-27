import inspect
import pytest
from parrot.bots.base import BaseBot


class TestNoDoubleRetry:
    def test_conversation_no_retry_loop(self):
        """conversation() should not contain a retry loop."""
        source = inspect.getsource(BaseBot.conversation)
        assert "for attempt in range" not in source
        assert "retries + 1" not in source

    def test_ask_no_retry_loop(self):
        """ask() should not contain a retry loop."""
        source = inspect.getsource(BaseBot.ask)
        assert "for attempt in range" not in source
        assert "retries + 1" not in source

    def test_conversation_no_retries_kwarg(self):
        """conversation() should not extract retries from kwargs."""
        source = inspect.getsource(BaseBot.conversation)
        assert "kwargs.get('retries'" not in source

    def test_ask_no_retries_kwarg(self):
        """ask() should not extract retries from kwargs."""
        source = inspect.getsource(BaseBot.ask)
        assert "kwargs.get('retries'" not in source

    def test_conversation_still_closes_llm(self):
        """conversation() still has finally block to close LLM."""
        source = inspect.getsource(BaseBot.conversation)
        assert "self._llm.close()" in source

    def test_conversation_preserves_cancelled_handling(self):
        """conversation() still handles CancelledError."""
        source = inspect.getsource(BaseBot.conversation)
        assert "CancelledError" in source

    def test_ask_preserves_cancelled_handling(self):
        """ask() still handles CancelledError."""
        source = inspect.getsource(BaseBot.ask)
        assert "CancelledError" in source
