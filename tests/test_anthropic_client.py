import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.claude import AnthropicClient
from parrot.models import AIMessage

@pytest.mark.asyncio
async def test_anthropic_ask():
    # Mock the Anthropic client class
    with patch('parrot.clients.claude.AsyncAnthropic') as mock_anthropic_cls:
        # Client instance mock
        mock_client_instance = MagicMock()
        mock_anthropic_cls.return_value = mock_client_instance
        
        # Setup mock response
        mock_response = MagicMock()
        mock_response_dict = {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello, Claude!"}],
            "model": "claude-3-5-sonnet-20241022",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5}
        }
        mock_response.model_dump.return_value = mock_response_dict
        
        # Mock messages.create
        mock_client_instance.messages.create = AsyncMock(return_value=mock_response)

        # Initialize our client
        client = AnthropicClient(api_key="fake_key")
        client.client = mock_client_instance
        client.logger = MagicMock() # Mock logger

        # Patch AIMessageFactory
        with patch('parrot.clients.claude.AIMessageFactory') as mock_factory:
            mock_factory.from_claude.return_value = AIMessage(content="Hello, Claude!")

            # Test ask
            response = await client.ask(prompt="Hi")
            
            assert isinstance(response, AIMessage)
            assert "Hello, Claude!" in response.content

def mock_stream_chunk(text):
    chunk = MagicMock()
    chunk.text = text
    return text # The code uses async for text in stream.text_stream

@pytest.mark.asyncio
async def test_anthropic_ask_stream():
    with patch('parrot.clients.claude.AsyncAnthropic') as mock_anthropic_cls:
        mock_client_instance = MagicMock()
        mock_anthropic_cls.return_value = mock_client_instance
        
        # Setup async iterator for text_stream
        async def async_iter():
            yield "Hello"
            yield " Claude"
            
        # Setup mock stream object returned by context manager
        mock_stream = MagicMock()
        mock_stream.text_stream = async_iter()
        
        # Setup get_final_message
        mock_final_msg = MagicMock()
        mock_final_msg.stop_reason = "end_turn"
        mock_stream.get_final_message = AsyncMock(return_value=mock_final_msg)
        
        # Setup Async Context Manager
        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
        
        # Mock messages.stream
        mock_client_instance.messages.stream = MagicMock(return_value=mock_stream_ctx)

        client = AnthropicClient(api_key="fake_key")
        client.client = mock_client_instance
        client.logger = MagicMock() # Mock logger
        
        chunks = []
        async for chunk in client.ask_stream("Hi"):
            chunks.append(chunk)
            
        assert "".join(chunks) == "Hello Claude"
