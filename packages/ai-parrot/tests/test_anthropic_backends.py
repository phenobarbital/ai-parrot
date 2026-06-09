"""Unit tests for parrot.clients.anthropic_backends (TASK-1517).

SDK classes are mocked throughout so these tests run without AWS credentials
or the anthropic[aws] extra installed.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from parrot.clients.anthropic_backends import (
    DirectBackend,
    BedrockBackend,
    AWSWorkspaceBackend,
    AnthropicBackendProtocol,
)


# ── DirectBackend ────────────────────────────────────────────────────────────

# FIX-9: test_direct_builds_async_anthropic was removed — it monkeypatched
# DirectBackend.build_client with a lambda that called _fake_direct, effectively
# testing its own mock rather than production code.  The real code path is fully
# covered by test_direct_build_client_returns_async_anthropic below.

@pytest.mark.asyncio
async def test_direct_build_client_returns_async_anthropic():
    """DirectBackend.build_client() delegates to AsyncAnthropic with api_key."""
    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)
    with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropic=mock_cls)}):
        backend = DirectBackend(api_key="fake-key")
        result = await backend.build_client()
    assert result is mock_instance
    mock_cls.assert_called_once_with(api_key="fake-key", max_retries=2)


def test_direct_translate_model_is_identity():
    """DirectBackend.translate_model() returns the input unchanged."""
    backend = DirectBackend()
    assert backend.translate_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert backend.translate_model("some-other-model") == "some-other-model"


@pytest.mark.asyncio
async def test_direct_missing_sdk_raises_import_error(monkeypatch):
    """DirectBackend.build_client() raises ImportError with hint when SDK absent."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="pip install ai-parrot"):
        backend = DirectBackend()
        await backend.build_client()


# ── BedrockBackend ───────────────────────────────────────────────────────────

def test_bedrock_translate_applied():
    """BedrockBackend.translate_model() calls Bedrock translation."""
    backend = BedrockBackend(region_prefix="us", aws_region="us-east-1")
    result = backend.translate_model("claude-sonnet-4-6")
    assert result.startswith("us.anthropic.")
    assert result.endswith(":0")


def test_bedrock_translate_no_prefix():
    """BedrockBackend.translate_model() without region_prefix gives base Bedrock ID."""
    backend = BedrockBackend(aws_region="us-east-1")
    result = backend.translate_model("claude-sonnet-4-6")
    assert result.startswith("anthropic.")
    assert result.endswith(":0")


@pytest.mark.asyncio
async def test_bedrock_build_client():
    """BedrockBackend.build_client() returns AsyncAnthropicBedrock instance."""
    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)
    with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropicBedrock=mock_cls)}):
        backend = BedrockBackend(aws_region="us-east-1", aws_access_key="AKIA_TEST")
        result = await backend.build_client()
    assert result is mock_instance


@pytest.mark.asyncio
async def test_bedrock_missing_sdk_raises_import_error(monkeypatch):
    """BedrockBackend.build_client() raises ImportError with hint when SDK absent."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="pip install ai-parrot"):
        backend = BedrockBackend(aws_region="us-east-1")
        await backend.build_client()


# ── AWSWorkspaceBackend ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aws_requires_region_and_workspace_both_missing():
    """AWSWorkspaceBackend.build_client() raises ValueError when both fields missing."""
    with pytest.raises(ValueError, match="aws_region"):
        await AWSWorkspaceBackend(aws_region=None, workspace_id=None).build_client()


@pytest.mark.asyncio
async def test_aws_requires_region():
    """AWSWorkspaceBackend.build_client() raises ValueError when aws_region missing."""
    with pytest.raises(ValueError, match="AWS_REGION_NAME"):
        await AWSWorkspaceBackend(aws_region=None, workspace_id="wrkspc_123").build_client()


@pytest.mark.asyncio
async def test_aws_requires_workspace_id():
    """AWSWorkspaceBackend.build_client() raises ValueError when workspace_id missing."""
    with pytest.raises(ValueError, match="ANTHROPIC_AWS_WORKSPACE_ID"):
        await AWSWorkspaceBackend(aws_region="us-east-1", workspace_id=None).build_client()


@pytest.mark.asyncio
async def test_aws_workspace_build_client_success():
    """AWSWorkspaceBackend.build_client() returns AsyncAnthropicAWS when both fields present."""
    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)
    with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropicAWS=mock_cls)}):
        backend = AWSWorkspaceBackend(aws_region="us-east-1", workspace_id="wrkspc_test")
        result = await backend.build_client()
    assert result is mock_instance
    mock_cls.assert_called_once_with(aws_region="us-east-1", workspace_id="wrkspc_test")


def test_aws_translate_model_is_identity():
    """AWSWorkspaceBackend.translate_model() returns the input unchanged."""
    backend = AWSWorkspaceBackend(aws_region="us-east-1", workspace_id="wrkspc_x")
    assert backend.translate_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_aws_missing_sdk_raises_import_error(monkeypatch):
    """AWSWorkspaceBackend.build_client() raises ImportError with hint when SDK absent."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match="pip install ai-parrot"):
        backend = AWSWorkspaceBackend(
            aws_region="us-east-1", workspace_id="wrkspc_test"
        )
        await backend.build_client()


# ── AnthropicBackendProtocol (FIX-6) ────────────────────────────────────────

def test_all_backends_satisfy_protocol():
    """All three backend classes satisfy AnthropicBackendProtocol at runtime."""
    direct = DirectBackend()
    bedrock = BedrockBackend()
    aws = AWSWorkspaceBackend()
    assert isinstance(direct, AnthropicBackendProtocol)
    assert isinstance(bedrock, AnthropicBackendProtocol)
    assert isinstance(aws, AnthropicBackendProtocol)
