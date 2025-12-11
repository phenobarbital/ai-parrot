import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.gpt import OpenAIClient
from parrot.models import AIMessage

@pytest.mark.asyncio
async def test_openai_ask():
    # Mock the OpenAI client class
    with patch('parrot.clients.gpt.AsyncOpenAI') as mock_openai_cls:
        # Client instance mock
        mock_client_instance = MagicMock()
        mock_openai_cls.return_value = mock_client_instance
        
        # Setup mock response parameters
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello, GPT!"
        mock_choice.message.role = "assistant"
        mock_choice.message.function_call = None
        mock_choice.message.tool_calls = None
        
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.id = "chatcmpl-123"
        mock_response.model = "gpt-4o"
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        
        # Mock chat.completions.create and parse
        mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_client_instance.chat.completions.parse = AsyncMock(return_value=mock_response)

        # Initialize our client
        client = OpenAIClient(api_key="fake_key")
        client.client = mock_client_instance
        client.logger = MagicMock()

        # Patch AIMessageFactory
        with patch('parrot.clients.gpt.AIMessageFactory') as mock_factory:
            mock_factory.from_openai.return_value = AIMessage(content="Hello, GPT!")

            # Test ask
            response = await client.ask(prompt="Hi")
            
            assert isinstance(response, AIMessage)
            assert "Hello, GPT!" in response.content

def mock_stream_chunk(text):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = text
    return chunk

@pytest.mark.asyncio
async def test_openai_ask_stream():
    with patch('parrot.clients.gpt.AsyncOpenAI') as mock_openai_cls:
        mock_client_instance = MagicMock()
        mock_openai_cls.return_value = mock_client_instance
        
        # Setup async iterator
        async def async_iter():
            yield mock_stream_chunk("Hello")
            yield mock_stream_chunk(" GPT")
            
        # Setup mock stream object
        mock_stream = MagicMock()
        mock_stream.__aiter__.side_effect = async_iter
        
        # Mock chat.completions.create with stream=True
        mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_stream)

        client = OpenAIClient(api_key="fake_key")
        client.client = mock_client_instance
        client.logger = MagicMock()
        
        chunks = []
        async for chunk in client.ask_stream("Hi"):
            chunks.append(chunk)
            
        assert "".join(chunks) == "Hello GPT"
