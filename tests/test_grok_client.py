
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from parrot.clients.grok import GrokClient, GrokModel
from parrot.models import AIMessage, CompletionUsage

class TestGrokClient:
    
    @pytest.fixture
    def mock_xai_client(self):
        with patch("parrot.clients.grok.AsyncClient") as mock:
            client_instance = AsyncMock()
            mock.return_value = client_instance
            yield client_instance

    @pytest.mark.asyncio
    async def test_initialization(self, mock_xai_client):
        # Test initialization with explicit API key
        with patch("os.getenv", return_value="fake_env_key"):
            client = GrokClient(api_key="test_key")
            assert client.api_key == "test_key"
            
            # Verify AsyncClient creation
            await client.get_client()
            mock_xai_client.assert_not_called() # Should be called on get_client? No, patch is on init.
            # wait, patch("parrot.clients.grok.AsyncClient") patches the class constructor.
            # So when we call AsyncClient(api_key=..., timeout=...) in get_client, verify it.
            
    @pytest.fixture
    def mock_factory(self):
        with patch("parrot.models.responses.AIMessageFactory") as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_ask(self, mock_xai_client, mock_factory):
        # Setup
        client = GrokClient(api_key="test_key")
        
        # Mock response
        mock_response = MagicMock()
        mock_response.content = "I am Grok"
        mock_response.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        
        # Mock chat object
        mock_chat = MagicMock() 
        mock_chat.sample = AsyncMock(return_value=mock_response)
        mock_chat.append = MagicMock()
        
        # chat.create is synchronous in the SDK
        mock_xai_client.chat.create = MagicMock(return_value=mock_chat)
        
        # Mock AIMessageFactory return
        mock_ai_message = MagicMock()
        mock_ai_message.output = "I am Grok"
        # Since usage is nested in real AIMessage, let's mock validation
        # But for unit test asserting attribute access is enough
        mock_ai_message.usage.prompt_tokens = 10
        mock_ai_message.usage.completion_tokens = 5
        mock_ai_message.model = GrokModel.GROK_4.value
        mock_factory.create_message.return_value = mock_ai_message

        # Execute
        response = await client.ask(prompt="Who are you?")
        
        # Verify
        assert response.output == "I am Grok"
        assert response.model == GrokModel.GROK_4.value
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 5
        
        # Verify calls
        mock_xai_client.chat.create.assert_called_once()
        mock_chat.append.assert_called() 
        mock_chat.sample.assert_called_once()
        mock_factory.create_message.assert_called_once()
        
    @pytest.mark.asyncio
    async def test_ask_stream(self, mock_xai_client):
        # Setup
        client = GrokClient(api_key="test_key")
        
        # Mock chat object
        mock_chat = MagicMock()
        
        # Mock stream iterator
        async def async_gen():
            # Create mocks that Don't have 'choices' attribute
            chunk1 = MagicMock(spec=['content'], content="I ")
            chunk2 = MagicMock(spec=['content'], content="am ")
            chunk3 = MagicMock(spec=['content'], content="Grok")
            yield chunk1
            yield chunk2
            yield chunk3

        mock_chat.stream.return_value = async_gen()
        mock_xai_client.chat.create = MagicMock(return_value=mock_chat)

        # Execute
        chunks = []
        async for chunk in client.ask_stream(prompt="Who are you?"):
            chunks.append(chunk)
            
        # Verify
        assert "".join(chunks) == "I am Grok"
        
        # Verify calls
        mock_xai_client.chat.create.assert_called_with(
            model=GrokModel.GROK_4.value,
            max_tokens=4096,
            temperature=0.7,
            stream=True
        )

    @pytest.mark.asyncio
    async def test_tools_preparation(self, mock_xai_client):
        # Test that tools are handled (mocking internal preparation)
        pass
        # Since logic is mostly in AbstractClient or we pass raw tools, 
        # we can verify if parameters are passed to create
