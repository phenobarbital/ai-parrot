import pytest

from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.google import GoogleGenAIClient
from parrot.models import AIMessage

@pytest.mark.asyncio
async def test_google_ask():
    # Mock the genai client
    with patch('parrot.clients.google.client.genai.Client') as mock_genai_cls:
        # Setup mock client instance
        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance
        
        # Setup mock response
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock()]
        
        # FIX: Ensure function_call is None to avoid Pydantic validation error
        mock_part = MagicMock(text="Hello, world!")
        mock_part.function_call = None
        mock_part.executable_code = None
        mock_part.code_execution_result = None
        mock_response.candidates[0].content.parts = [mock_part]
        
        # FIX: The client uses chat.send_message for ask() by default (multi-turn)
        mock_chat = MagicMock()
        mock_chat.send_message = AsyncMock(return_value=mock_response)
        
        # Mock chats.create to return our mock chat
        mock_client_instance.aio.chats.create = MagicMock(return_value=mock_chat)

        # Initialize our client
        client = GoogleGenAIClient(api_key="fake_key")
        client.client = mock_client_instance  # Inject mock client
        client.logger = MagicMock() # Mock logger to handle 'notice' calls

        # Test ask
        with patch('parrot.clients.google.client.AIMessageFactory') as mock_factory:
            # Mock the factory method
            mock_factory.from_gemini.return_value = AIMessage(content="Hello, world!")
            
            response = await client.ask(prompt="Hi")
            
            assert isinstance(response, AIMessage)
            assert "Hello, world!" in response.content

def mock_stream_chunk(text):
    chunk = MagicMock()
    chunk.text = text
    chunk.candidates = [MagicMock()] # Candidate for finish_reason check
    # Ensure no function call in chunk for basic test
    chunk_part = MagicMock()
    chunk_part.function_call = None
    chunk_part.executable_code = None
    chunk.candidates[0].content.parts = [chunk_part] 
    return chunk

@pytest.mark.asyncio
async def test_google_ask_stream():
    with patch('parrot.clients.google.client.genai.Client') as mock_genai_cls:
        mock_client_instance = MagicMock()
        mock_genai_cls.return_value = mock_client_instance
        
        # Setup mock stream iterator (async generator)
        async def async_iter():
            yield mock_stream_chunk("Hello")
            yield mock_stream_chunk(" world")
            
        # Setup mock stream object
        # The code iterates directly: async for chunk in await chat.send_message_stream(...)
        mock_stream = MagicMock()
        mock_stream.__aiter__.side_effect = async_iter
        
        # Setup mock chat
        mock_chat = MagicMock()
        # send_message_stream is awaited, so it must be AsyncMock returning the stream
        mock_chat.send_message_stream = AsyncMock(return_value=mock_stream)
        
        # chats.create returns mock_chat
        mock_client_instance.aio.chats.create = MagicMock(return_value=mock_chat)

        client = GoogleGenAIClient(api_key="fake_key")
        client.client = mock_client_instance
        
        chunks = []
        async for chunk in client.ask_stream("Hi"):
            chunks.append(chunk)
            
        assert "".join(chunks) == "Hello world"


@pytest.mark.asyncio
async def test_google_deep_research_ask_accepts_parameters():
    """Test that Google client accepts deep_research parameters without error."""
    mock_genai = MagicMock()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client
    
    # Mock the response
    # Mock interactions.create which is used in _deep_research_ask
    mock_interactions = MagicMock()
    mock_client.interactions = mock_interactions
    
    # Setup mock stream (synchronous iterator)
    mock_chunk = MagicMock()
    mock_chunk.event_type = "content.delta"
    mock_chunk.delta.type = "text"
    mock_chunk.delta.text = "Research result"
    mock_chunk.event_id = "evt_123"
    
    # interactions.create returns a synchronous stream
    mock_interactions.create.return_value = [mock_chunk]
    
    with patch('parrot.clients.google.client.genai', mock_genai):
        client = GoogleGenAIClient(api_key="fake_key")
        client.client = mock_client
        
        # Should not raise - falls back to standard ask
        response = await client.ask(
            "Research quantum computing",
            deep_research=True,
            background=True,
            file_search_store_names=["test-store"]
        )
        
        assert response is not None
        assert "Research result" in response.response


@pytest.mark.asyncio
async def test_google_deep_research_ask_stream_accepts_parameters():
    """Test that Google client ask_stream accepts deep_research parameters."""
    mock_genai = MagicMock()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client
    
    # Mock streaming response
    async def mock_text_stream():
        for chunk in ["Hello", " ", "world"]:
            yield chunk
    
    mock_stream = MagicMock()
    mock_stream.text_stream = mock_text_stream()
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)
    
    mock_chat = MagicMock()
    mock_chat.send_message_stream.return_value = mock_stream
    mock_client.aio.chats.create.return_value = mock_chat
    
    with patch('parrot.clients.google.client.genai', mock_genai):
        client = GoogleGenAIClient(api_key="fake_key")
        client.client = mock_client
        
        chunks = []
        async for chunk in client.ask_stream(
            "Research AI",
            deep_research=True,
            agent_config={"thinking_summaries": "auto"}
        ):
            chunks.append(chunk)
        
        assert len(chunks) > 0

def test_google_tool_result_coerces_non_string_keys():
    client = GoogleGenAIClient(api_key="fake_key")
    result = {
        1: "one",
        "nested": {2: "two"},
        "items": [{3: "three"}],
    }

    output = client._process_tool_result_for_api(result)

    assert output["result"]["1"] == "one"
    assert output["result"]["nested"]["2"] == "two"
    assert output["result"]["items"][0]["3"] == "three"
