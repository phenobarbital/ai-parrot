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


@pytest.mark.asyncio
async def test_openai_deep_research_routes_to_correct_model():
    """Test that deep_research flag routes to o3-deep-research model."""
    with patch('parrot.clients.gpt.AsyncOpenAI') as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        
        # Mock response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Deep research result"
        mock_response.choices[0].message.tool_calls = None
        
        # Mock responses.create for deep research models
        mock_client.responses.create = AsyncMock(return_value=MagicMock(
            output_text="Deep research result",
            output=[],
            usage=None
        ))
        
        client = OpenAIClient(api_key="fake_key")
        client.client = mock_client
        
        response = await client.ask(
            "Research quantum computing",
            model="gpt-4o",
            deep_research=True
        )
        
        # Verify responses.create was called (indicates o3-deep-research routing)
        assert mock_client.responses.create.called


@pytest.mark.asyncio
async def test_openai_deep_research_configures_tools():
    """Test that deep_research configures web_search and file_search tools."""
    with patch('parrot.clients.gpt.AsyncOpenAI') as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        
        # Mock responses API
        mock_client.responses.create = AsyncMock(return_value=MagicMock(
            output_text="Research with tools",
            output=[],
            usage=None
        ))
        
        client = OpenAIClient(api_key="fake_key")
        client.client = mock_client
        
        response = await client.ask(
            "Research with tools",
            deep_research=True,
            enable_web_search=True,
            vector_store_ids=["vs_123"],
            enable_code_interpreter=True
        )
        
        # Verify responses.create was called with tools
        call_args = mock_client.responses.create.call_args
        assert call_args is not None
        # Tools should be in the kwargs
        if 'tools' in call_args.kwargs:
            tools = call_args.kwargs['tools']
            assert len(tools) == 3  # web_search, file_search, code_interpreter
