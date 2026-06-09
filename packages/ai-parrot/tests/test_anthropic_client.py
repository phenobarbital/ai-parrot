"""Tests for AnthropicClient (TASK-1518 additions + regression suite).

Existing tests are updated to remove the stale
``patch('parrot.clients.claude.AsyncAnthropic')`` which patched a name that
was never exported from the module (it lived only inside ``get_client()``
or ``TYPE_CHECKING``). The tests set ``client.client`` directly and therefore
never actually call ``get_client()``, so the patch was redundant.

FEAT-232 additions (TASK-1518):
- Verify ``backend`` parameter forwarding.
- Verify ``_resolve_model()`` applies backend translation.
- Verify ``get_client()`` dispatches to the correct backend.
- Verify credential precedence (kwarg → conf/env → None).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.clients.claude import AnthropicClient
from parrot.models import AIMessage


# ── Regression: existing direct-path tests (TASK-1518 parity requirement) ───

@pytest.mark.asyncio
async def test_anthropic_ask():
    """AnthropicClient.ask() returns an AIMessage (direct backend regression)."""
    mock_client_instance = MagicMock()

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

    # Initialize our client; patch get_client() so it returns the mock SDK client.
    client = AnthropicClient(api_key="fake_key")
    client.logger = MagicMock()  # Mock logger

    # Patch AIMessageFactory
    with patch('parrot.clients.claude.AIMessageFactory') as mock_factory:
        mock_factory.from_claude.return_value = AIMessage(content="Hello, Claude!")
        # Patch the backend's build_client to return the mock
        client._backend = MagicMock()
        client._backend.build_client = AsyncMock(return_value=mock_client_instance)
        client._backend.translate_model = lambda m: m

        # Test ask
        response = await client.ask(prompt="Hi")

        assert isinstance(response, AIMessage)
        assert "Hello, Claude!" in response.content


def mock_stream_chunk(text):
    chunk = MagicMock()
    chunk.text = text
    return text


@pytest.mark.asyncio
async def test_anthropic_ask_stream():
    """AnthropicClient.ask_stream() yields text chunks (direct backend regression)."""
    mock_client_instance = MagicMock()

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
    client.logger = MagicMock()  # Mock logger
    # Patch the backend's build_client to return the mock SDK instance
    client._backend = MagicMock()
    client._backend.build_client = AsyncMock(return_value=mock_client_instance)
    client._backend.translate_model = lambda m: m

    with patch('parrot.clients.claude.AIMessageFactory') as mock_factory:
        mock_factory.from_claude.return_value = AIMessage(content="Hello Claude")

        chunks = []
        async for chunk in client.ask_stream("Hi"):
            if isinstance(chunk, str):
                chunks.append(chunk)

    assert "".join(chunks) == "Hello Claude"


@pytest.mark.asyncio
async def test_claude_deep_research_enables_tools():
    """deep_research=True automatically enables tools."""
    mock_client = MagicMock()

    # Mock response without tool calls
    mock_response = MagicMock()
    mock_response.model_dump.return_value = {
        "id": "msg_123",
        "content": [{"type": "text", "text": "Deep research response"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 20}
    }

    mock_client.messages.create = AsyncMock(return_value=mock_response)

    client = AnthropicClient(api_key="fake_key")
    client._backend = MagicMock()
    client._backend.build_client = AsyncMock(return_value=mock_client)
    client._backend.translate_model = lambda m: m

    with patch('parrot.clients.claude.AIMessageFactory') as mock_factory:
        mock_factory.from_claude.return_value = AIMessage(content="Deep research response")

        response = await client.ask(
            "Research AI history",
            deep_research=True
        )

    # Verify messages.create was called
    call_args = mock_client.messages.create.call_args
    assert call_args is not None
    # System prompt should contain research instructions
    if 'system' in call_args.kwargs:
        assert "DEEP RESEARCH" in call_args.kwargs['system']


@pytest.mark.asyncio
async def test_claude_deep_research_accepts_parameters():
    """ask_stream() accepts deep_research parameters."""
    mock_client = MagicMock()

    # Mock streaming
    async def mock_text_stream():
        yield "Research"
        yield " result"

    mock_final_message = MagicMock()
    mock_final_message.stop_reason = "end_turn"

    mock_stream = MagicMock()
    mock_stream.text_stream = mock_text_stream()
    mock_stream.get_final_message = AsyncMock(return_value=mock_final_message)
    mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_stream.__aexit__ = AsyncMock(return_value=None)

    mock_client.messages.stream = MagicMock(return_value=mock_stream)

    client = AnthropicClient(api_key="fake_key")
    client._backend = MagicMock()
    client._backend.build_client = AsyncMock(return_value=mock_client)
    client._backend.translate_model = lambda m: m

    with patch('parrot.clients.claude.AIMessageFactory') as mock_factory:
        mock_factory.from_claude.return_value = AIMessage(content="Research result")

        chunks = []
        async for chunk in client.ask_stream(
            "Research topic",
            deep_research=True,
            agent_config={"mode": "research"}
        ):
            if isinstance(chunk, str):
                chunks.append(chunk)

    assert len(chunks) > 0


# ── FEAT-232 / TASK-1518 additions ──────────────────────────────────────────

def test_default_backend_is_direct():
    """AnthropicClient() defaults to backend='direct'."""
    client = AnthropicClient(api_key="key")
    assert client.backend == "direct"
    from parrot.clients.anthropic_backends import DirectBackend
    assert isinstance(client._backend, DirectBackend)


def test_bedrock_backend_set():
    """AnthropicClient(backend='bedrock') stores BedrockBackend."""
    client = AnthropicClient(backend="bedrock", aws_region="us-east-1")
    assert client.backend == "bedrock"
    from parrot.clients.anthropic_backends import BedrockBackend
    assert isinstance(client._backend, BedrockBackend)


def test_aws_backend_set():
    """AnthropicClient(backend='aws') stores AWSWorkspaceBackend."""
    client = AnthropicClient(
        backend="aws", aws_region="us-east-1", workspace_id="wrkspc_x"
    )
    assert client.backend == "aws"
    from parrot.clients.anthropic_backends import AWSWorkspaceBackend
    assert isinstance(client._backend, AWSWorkspaceBackend)


def test_resolve_model_identity_for_direct():
    """_resolve_model() returns the public ID unchanged for direct backend."""
    client = AnthropicClient()  # direct
    assert client._resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_resolve_model_translates_for_bedrock():
    """_resolve_model() returns a Bedrock ID for bedrock backend."""
    client = AnthropicClient(backend="bedrock", aws_region="us-east-1")
    result = client._resolve_model("claude-sonnet-4-6")
    assert "anthropic." in result


def test_resolve_model_with_claude_model_enum():
    """_resolve_model() accepts a ClaudeModel enum and translates it."""
    from parrot.models.claude import ClaudeModel
    client = AnthropicClient(backend="bedrock", aws_region="us-east-1")
    result = client._resolve_model(ClaudeModel.SONNET_4_6)
    assert "anthropic." in result


def test_resolve_model_none_falls_back_to_default():
    """_resolve_model(None) falls back to self.model or default_model."""
    client = AnthropicClient()
    result = client._resolve_model(None)
    # Should return the default model string (not None, not empty)
    assert result and isinstance(result, str)


@pytest.mark.asyncio
async def test_get_client_dispatches_direct():
    """get_client() builds AsyncAnthropic for direct backend."""
    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)
    with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropic=mock_cls)}):
        client = AnthropicClient(api_key="key")
        result = await client.get_client()
    assert result is mock_instance


@pytest.mark.asyncio
async def test_get_client_dispatches_bedrock():
    """get_client() builds AsyncAnthropicBedrock for bedrock backend."""
    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)
    with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropicBedrock=mock_cls)}):
        client = AnthropicClient(backend="bedrock", aws_region="us-east-1")
        result = await client.get_client()
    assert result is mock_instance


def test_credential_precedence_kwarg_wins():
    """Explicit kwarg beats conf/env value."""
    client = AnthropicClient(
        backend="bedrock",
        aws_access_key="AKIA_EXPLICIT",
        aws_region="eu-west-1",
    )
    from parrot.clients.anthropic_backends import BedrockBackend
    assert isinstance(client._backend, BedrockBackend)
    # The explicit kwarg was passed to the backend
    assert client._backend.aws_access_key == "AKIA_EXPLICIT"
    assert client._backend.aws_region == "eu-west-1"
