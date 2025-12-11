import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.groq import GroqClient
from parrot.models import AIMessage

@pytest.mark.asyncio
async def test_groq_ask():
    # Mock the Groq client class
    with patch('parrot.clients.groq.AsyncGroq') as mock_groq_cls:
        # Client instance mock
        mock_client_instance = MagicMock()
        mock_groq_cls.return_value = mock_client_instance
        
        # Setup mock response parameters
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello, Groq!"
        mock_choice.message.role = "assistant"
        mock_choice.message.function_call = None
        mock_choice.message.tool_calls = None
        
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.id = "msg_123"
        mock_response.model = "llama3-8b"
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        
        # Mock chat.completions.create (AsyncGroq doesn't use 'parse' usually unless recent update, sticking to create)
        mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        # Initialize our client
        client = GroqClient(api_key="fake_key")
        client.client = mock_client_instance
        client.logger = MagicMock()

        # Patch AIMessageFactory
        with patch('parrot.clients.groq.AIMessageFactory') as mock_factory:
            mock_factory.from_groq.return_value = AIMessage(content="Hello, Groq!")

            # Test ask
            response = await client.ask(prompt="Hi")
            
            assert isinstance(response, AIMessage)
            assert "Hello, Groq!" in response.content

def mock_stream_chunk(text):
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta.content = text
    return chunk

@pytest.mark.asyncio
async def test_groq_ask_stream():
    with patch('parrot.clients.groq.AsyncGroq') as mock_groq_cls:
        mock_client_instance = MagicMock()
        mock_groq_cls.return_value = mock_client_instance
        
        # Setup async iterator
        async def async_iter():
            yield mock_stream_chunk("Hello")
            yield mock_stream_chunk(" Groq")
            
        # Setup mock stream object
        mock_stream = MagicMock()
        mock_stream.__aiter__.side_effect = async_iter
        
        # Mock chat.completions.create with stream=True
        mock_client_instance.chat.completions.create = AsyncMock(return_value=mock_stream)

        client = GroqClient(api_key="fake_key")
        client.client = mock_client_instance
        client.logger = MagicMock()
        
        chunks = []
        async for chunk in client.ask_stream("Hi"):
            chunks.append(chunk)
            
        assert "".join(chunks) == "Hello Groq"
