import pytest

from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.google import GoogleGenAIClient
from parrot.models import AIMessage

@pytest.mark.asyncio
async def test_google_ask():
    # Mock the genai client
    with patch('parrot.clients.google.genai.Client') as mock_genai_cls:
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
        with patch('parrot.clients.google.AIMessageFactory') as mock_factory:
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
    with patch('parrot.clients.google.genai.Client') as mock_genai_cls:
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
