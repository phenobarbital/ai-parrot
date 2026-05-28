
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper
from aiogram.exceptions import TelegramBadRequest

class TestTelegramSendLogic:
    """Test suite for TelegramAgentWrapper's message sending logic."""

    @pytest.fixture
    def wrapper(self):
        """Create a mock wrapper instance."""
        wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
        wrapper.logger = MagicMock()
        return wrapper

    @pytest.mark.asyncio
    async def test_send_success(self, wrapper):
        """Standard successful send should not trigger retries."""
        mock_func = AsyncMock()
        text = "Hello world"
        
        await wrapper._try_send_message(mock_func, text, parse_mode="Markdown")
        
        # Expect positional args: (text, parse_mode)
        mock_func.assert_awaited_once_with(text, "Markdown")
        wrapper.logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_on_parsing_error(self, wrapper):
        """Should retry with escaped text on parsing error."""
        mock_func = AsyncMock()
        # First call fails with parsing error
        mock_func.side_effect = [
            TelegramBadRequest(method="sendMessage", message="Bad Request: can't parse entities"),
            None  # Second call succeeds
        ]
        
        text = "variable_name and another_one"
        await wrapper._try_send_message(mock_func, text, parse_mode="Markdown")
        
        assert mock_func.await_count == 2
        
        # First call with original text
        mock_func.assert_any_await(text, "Markdown")
        
        # Second call with escaped text
        # Expect underscores to be escaped
        expected_escaped = "variable\\_name and another\\_one"
        mock_func.assert_any_await(expected_escaped, "Markdown")
        
        # Should log info about retry, not warning
        wrapper.logger.info.assert_called()
        wrapper.logger.warning.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_on_persistent_error(self, wrapper):
        """Should fallback to plaintext if retry also fails."""
        mock_func = AsyncMock()
        # Both attempts fail with parsing error
        mock_func.side_effect = [
            TelegramBadRequest(method="sendMessage", message="Bad Request: can't parse entities"),
            TelegramBadRequest(method="sendMessage", message="Still can't parse"),
             None # Fallback succeeds
        ]
        
        text = "broken_text"
        await wrapper._try_send_message(mock_func, text, parse_mode="Markdown")
        
        assert mock_func.await_count == 3 # 1. original with markdown, 2. escaped with markdown, 3. original with None
        
        # Verify fallback call
        mock_func.assert_any_await(text, None)
        
        # Should simulate warning on fallback
        wrapper.logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_immediate_fallback_on_other_error(self, wrapper):
        """Should immediately fallback for non-parsing errors."""
        mock_func = AsyncMock()
        # Fails with generic error
        mock_func.side_effect = [
            Exception("Network error"), 
            None
        ]
        
        text = "text"
        await wrapper._try_send_message(mock_func, text, parse_mode="Markdown")
        
        # Should try once with markdown, then fallback
        assert mock_func.await_count == 2
        mock_func.assert_any_await(text, None)
        wrapper.logger.warning.assert_called()
