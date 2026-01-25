import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.grok import GrokClient
from parrot.models import AIMessage

@pytest.fixture
def mock_xai_client():
    with patch("parrot.clients.grok.AsyncClient") as mock:
        client_instance = AsyncMock()
        # client.chat.create is synchronous in the xAI SDK usage shown in grok.py
        client_instance.chat.create = MagicMock()
        mock.return_value = client_instance
        yield client_instance

@pytest.fixture
def grok_client(mock_xai_client):
    """Fixture for GrokClient with mocked dependencies."""
    with patch.dict("os.environ", {"XAI_API_KEY": "fake_key"}):
        client = GrokClient(api_key="verify_key")
        # Pre-inject client for direct usage if needed, 
        # but we also mock AsyncClient constructor so it works when re-instantiated
        client.client = mock_xai_client
        return client

@pytest.mark.asyncio
async def test_grok_init(mock_xai_client):
    """Test initialization of GrokClient."""
    with patch.dict("os.environ", {"XAI_API_KEY": "env_key"}):
        client = GrokClient()
        assert client.api_key == "env_key"

@pytest.mark.asyncio
async def test_ask_simple(grok_client, mock_xai_client):
    """Test a simple ask call (happy path)."""
    # Setup Mock Response
    mock_response = MagicMock()
    mock_response.content = "I am Grok"
    # Explicitly set list-like attributes to empty to prevent MagicMock from creating truthy mocks
    mock_response.tool_calls = []
    mock_response.message.tool_calls = [] 
    
    mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=3)
    
    # Setup Chat Mock
    mock_chat = MagicMock()
    mock_chat.sample = AsyncMock(return_value=mock_response)
    
    mock_xai_client.chat.create.return_value = mock_chat

    # Patch AIMessageFactory
    with patch('parrot.models.responses.AIMessageFactory') as mock_factory:
        mock_factory.create_message.return_value = AIMessage(content="I am Grok")
        
        async with grok_client as client:
            response = await client.ask(prompt="Hello")

        assert isinstance(response, AIMessage)
        assert response.content == "I am Grok"
        
        # Verify xAI SDK interactions
        mock_xai_client.chat.create.assert_called_once()
        mock_chat.sample.assert_called_once()


@pytest.mark.asyncio
async def test_ask_stream(grok_client, mock_xai_client):
    """Test streaming response."""
    # Setup Chat Mock
    mock_chat = MagicMock()
    
    # Create an async iterator for the stream
    async def stream_generator():
        # Chunk 1
        c1 = MagicMock()
        c1.choices = [MagicMock(delta=MagicMock(content="Hello"))]
        yield c1
        # Chunk 2
        c2 = MagicMock()
        c2.choices = [MagicMock(delta=MagicMock(content=" "))]
        yield c2
        # Chunk 3
        c3 = MagicMock()
        c3.choices = [MagicMock(delta=MagicMock(content="World"))]
        yield c3

    mock_chat.stream.return_value = stream_generator()
    mock_xai_client.chat.create.return_value = mock_chat

    # Collect chunks
    chunks = []
    async with grok_client as client:
        async for chunk in client.ask_stream(prompt="Hi"):
            chunks.append(chunk)

    assert "".join(chunks) == "Hello World"
    # Verify stream=True was passed
    call_kwargs = mock_xai_client.chat.create.call_args.kwargs
    assert call_kwargs.get("stream") is True

@pytest.mark.asyncio
async def test_tool_calls(grok_client, mock_xai_client):
    """Test proper handling of tool calls in the loop."""
    
    # Tool Call Mock
    tool_call_mock = MagicMock()
    tool_call_mock.id = "call_123"
    tool_call_mock.function.name = "get_weather"
    tool_call_mock.function.arguments = '{"location": "London"}'
    
    # 1. Response WITH Tool Call
    response_with_tool = MagicMock()
    response_with_tool.tool_calls = [tool_call_mock]
    response_with_tool.content = None 
    
    # 2. Final Response
    response_final = MagicMock()
    response_final.tool_calls = [] 
    # Important: Also mock the nested check for message.tool_calls
    response_final.message.tool_calls = []
    response_final.content = "It is sunny in London."
    
    # Setup Chat Mock
    mock_chat = MagicMock()
    mock_chat.sample = AsyncMock(side_effect=[response_with_tool, response_final])
    
    mock_xai_client.chat.create.return_value = mock_chat
    
    # Mock internal _execute_tool
    grok_client._execute_tool = AsyncMock(return_value="Sunny, 25C")

    # Patch AIMessageFactory
    with patch('parrot.models.responses.AIMessageFactory') as mock_factory:
        mock_factory.create_message.return_value = AIMessage(content="It is sunny in London.")

        # Act
        async with grok_client:
            response = await grok_client.ask(prompt="Weather?", use_tools=True)

        assert response.content == "It is sunny in London."
        
        # Verify Tool execution
        grok_client._execute_tool.assert_awaited_with("get_weather", {"location": "London"})
        
        # Verify calls to sample: Expect 2
    # Verify calls to sample: Expect 2
        assert mock_chat.sample.call_count == 2

@pytest.mark.integration
@pytest.mark.asyncio
async def test_grok_real_integration():
    """
    Real Integration test for GrokClient.
    WARNING: CONSUMES CREDITS.
    """
    import os
    if not os.getenv("XAI_API_KEY"):
        pytest.skip("XAI_API_KEY not found")

    # Real instantiation
    client = GrokClient()
    
    try:
        response = await client.ask("Where is the capital of France?")
        assert response.content is not None
        assert "Paris" in response.content
        print(f"Real Grok Response: {response.content}")
    finally:
        await client.close()
