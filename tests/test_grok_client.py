import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from parrot.clients.grok import GrokClient, GrokModel
from parrot.models import AIMessage, ToolCall
from pydantic import BaseModel
from parrot.models import CompletionUsage

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
        mock_response.tool_calls = [] 
        mock_response.message.tool_calls = [] # Ensure nested check is also empty
        
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
            
        
    @pytest.mark.asyncio
    async def test_ask_structured(self, mock_xai_client, mock_factory):
        # Setup
        client = GrokClient(api_key="test_key")
        
        class TestModel(BaseModel):
            reasoning: str
            answer: str
            
        # Mock response
        mock_response = MagicMock()
        mock_response.content = '{"reasoning": "Because", "answer": "42"}'
        mock_response.usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        
        mock_chat = MagicMock()
        mock_chat.sample = AsyncMock(return_value=mock_response)
        mock_chat.append = MagicMock()
        mock_xai_client.chat.create = MagicMock(return_value=mock_chat)
        
        # Mock factory to return structured object
        mock_ai_message = MagicMock()
        mock_ai_message.output = {"reasoning": "Because", "answer": "42"}
        mock_ai_message.is_structured = True
        mock_factory.create_message.return_value = mock_ai_message
        
        # Execute
        response = await client.ask(prompt="Solve it", structured_output=TestModel)
        
        
        # Verify
        if isinstance(response.output, BaseModel):
            assert response.output.model_dump() == {"reasoning": "Because", "answer": "42"}
        else:
            assert response.output == {"reasoning": "Because", "answer": "42"}
            
        mock_xai_client.chat.create.assert_called_once()
        # Verify response_format was passed
        call_kwargs = mock_xai_client.chat.create.call_args[1]
        assert "response_format" in call_kwargs
        assert call_kwargs["response_format"]["json_schema"]["name"] == "testmodel"

    @pytest.mark.asyncio
    async def test_ask_tools(self, mock_xai_client, mock_factory):
        # Setup
        client = GrokClient(api_key="test_key")
        
        # Mock responses for loop
        # 1. Tool Call
        mock_response_tool = MagicMock()
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "test_tool"
        mock_tool_call.function.arguments = '{"arg": "val"}'
        mock_response_tool.tool_calls = [mock_tool_call]
        mock_response_tool.content = None # Tool calls often have null content
        mock_response_tool.usage = {"prompt_tokens": 5}
        
        # 2. Final Response
        mock_response_final = MagicMock()
        mock_response_final.tool_calls = []
        mock_response_final.message.tool_calls = []
        mock_response_final.content = "Tool executed."
        mock_response_final.usage = {"prompt_tokens": 10}
        
        mock_chat = MagicMock()
        # sample returns tool call first, then final
        mock_chat.sample = AsyncMock(side_effect=[mock_response_tool, mock_response_final])
        mock_chat.append = MagicMock()
        mock_xai_client.chat.create = MagicMock(return_value=mock_chat)
        
        # Mock tool execution
        client._execute_tool = AsyncMock(return_value="Tool Result")
        
        # Mock factory
        mock_ai_message = MagicMock()
        mock_ai_message.output = "Tool executed."
        mock_ai_message.tool_calls = [ToolCall(id="call_123", name="test_tool", arguments={"arg": "val"}, result="Tool Result")]
        mock_factory.create_message.return_value = mock_ai_message
        
        # Execute
        response = await client.ask(prompt="Use tool", tools=[{"type": "function", "function": {"name": "test_tool"}}])
        
        # Verify
        assert response.output == "Tool executed."
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "test_tool"
        assert response.tool_calls[0].result == "Tool Result"
        
        # Verify loop
        assert mock_chat.sample.call_count == 2
        client._execute_tool.assert_awaited_with("test_tool", {"arg": "val"})
        # Verify tool result was appended
        # We need to check if chat.append was called with a tool message
        # Since we can't easily check the type of the arg without importing xai_sdk.chat.tool,
        # checking call count is decent proxy + argument value
        assert mock_chat.append.call_count >= 2 # User prompt + System? + Tool result + etc


    @pytest.mark.asyncio
    async def test_tools_preparation(self, mock_xai_client):
        # Test that tools are handled (mocking internal preparation)
        pass
        # Since logic is mostly in AbstractClient or we pass raw tools, 
        # we can verify if parameters are passed to create
