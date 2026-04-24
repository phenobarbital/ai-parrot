"""Unit tests for NvidiaClient, NvidiaModel, and factory registration.

Tests cover initialization, env-var fallback for NVIDIA_API_KEY, the
``enable_thinking`` / ``_merge_thinking_extra_body`` helper, model enum
values, and LLMFactory registration.

No live Nvidia calls are made.  The AsyncOpenAI SDK client is lazy (created
on first ``get_client()`` call), so simple attribute-state tests do not need
any HTTP mocking.
"""
import os

import pytest

from parrot.clients.nvidia import NvidiaClient
from parrot.models.nvidia import NvidiaModel
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """NvidiaClient with an explicit API key — no env-var lookup needed."""
    return NvidiaClient(api_key="test-key-123")


@pytest.fixture
def env_key(monkeypatch):
    """Patch navconfig.config.get so NvidiaClient() (no api_key) picks up a fake key."""
    from parrot.clients import nvidia as nvidia_mod

    monkeypatch.setattr(
        nvidia_mod.config,
        "get",
        lambda key, default=None: "env-nvidia-key" if key == "NVIDIA_API_KEY" else default,
    )
    return "env-nvidia-key"


# ---------------------------------------------------------------------------
# TestNvidiaClientInit
# ---------------------------------------------------------------------------


class TestNvidiaClientInit:
    """Tests for NvidiaClient constructor and attribute defaults."""

    def test_client_init_explicit_key(self, client):
        """api_key passed explicitly is stored on the client."""
        assert client.api_key == "test-key-123"

    def test_client_init_env_fallback(self, env_key):
        """With api_key=None the client falls back to NVIDIA_API_KEY via config.get."""
        c = NvidiaClient(api_key=None)
        assert c.api_key == "env-nvidia-key"

    def test_client_base_url(self, client):
        """base_url points to the Nvidia NIM gateway."""
        assert client.base_url == "https://integrate.api.nvidia.com/v1"

    def test_client_type_and_name(self, client):
        """client_type and client_name are both 'nvidia'."""
        assert client.client_type == "nvidia"
        assert client.client_name == "nvidia"

    def test_default_model(self, client):
        """_default_model is KIMI_K2_INSTRUCT_0905."""
        assert NvidiaClient._default_model == NvidiaModel.KIMI_K2_INSTRUCT_0905.value


# ---------------------------------------------------------------------------
# TestNvidiaThinkingHelper
# ---------------------------------------------------------------------------


class TestNvidiaThinkingHelper:
    """Tests for the _merge_thinking_extra_body static helper."""

    def test_enable_thinking_injects_extra_body(self):
        """Calling with enable_thinking=True on None body returns the right dict."""
        result = NvidiaClient._merge_thinking_extra_body(None, True, False)

        assert result is not None
        assert "chat_template_kwargs" in result
        assert result["chat_template_kwargs"]["enable_thinking"] is True
        assert result["chat_template_kwargs"]["clear_thinking"] is False

    def test_enable_thinking_preserves_existing_extra_body(self):
        """Existing keys in extra_body and chat_template_kwargs are kept."""
        existing = {"k": 1, "chat_template_kwargs": {"other": 1}}
        result = NvidiaClient._merge_thinking_extra_body(existing, True, True)

        assert result is not None
        # top-level key preserved
        assert result["k"] == 1
        ctk = result["chat_template_kwargs"]
        # nested pre-existing key preserved
        assert ctk["other"] == 1
        # new flags injected
        assert ctk["enable_thinking"] is True
        assert ctk["clear_thinking"] is True

    def test_enable_thinking_default_off(self):
        """When enable_thinking=False the helper is a no-op."""
        # None extra_body → still None
        assert NvidiaClient._merge_thinking_extra_body(None, False, False) is None

        # Existing dict → returned unchanged
        existing = {"k": 1}
        result = NvidiaClient._merge_thinking_extra_body(existing, False, True)
        assert result is existing  # same object, not a copy


# ---------------------------------------------------------------------------
# TestNvidiaModelEnum
# ---------------------------------------------------------------------------


class TestNvidiaModelEnum:
    """Tests that NvidiaModel enum members have the correct values."""

    EXPECTED = {
        "KIMI_K2_THINKING": "moonshotai/kimi-k2-thinking",
        "KIMI_K2_INSTRUCT_0905": "moonshotai/kimi-k2-instruct-0905",
        "KIMI_K2_5": "moonshotai/kimi-k2.5",
        "MINIMAX_M2_5": "minimaxai/minimax-m2.5",
        "MINIMAX_M2_7": "minimaxai/minimax-m2.7",
        "MAMBA_CODESTRAL_7B": "mistralai/mamba-codestral-7b-v0.1",
        "DEEPSEEK_V3_1_TERMINUS": "deepseek-ai/deepseek-v3.1-terminus",
        "QWEN3_5_397B": "qwen/qwen3.5-397b-a17b",
        "GLM_5_1": "z-ai/glm-5.1",
    }

    def test_nvidia_model_enum_values(self):
        """All 9 model slugs are present and match spec-defined strings."""
        for member_name, expected_value in self.EXPECTED.items():
            member = NvidiaModel[member_name]
            assert member.value == expected_value, (
                f"NvidiaModel.{member_name}.value expected {expected_value!r}, "
                f"got {member.value!r}"
            )


# ---------------------------------------------------------------------------
# TestNvidiaFactory
# ---------------------------------------------------------------------------


class TestNvidiaFactory:
    """Tests for LLMFactory registration of NvidiaClient."""

    def test_factory_registration(self):
        """'nvidia' key is present in SUPPORTED_CLIENTS and maps to NvidiaClient."""
        assert "nvidia" in SUPPORTED_CLIENTS
        assert SUPPORTED_CLIENTS["nvidia"] is NvidiaClient

        # Factory creates the right client type with the right model
        c = LLMFactory.create(
            "nvidia:moonshotai/kimi-k2-thinking",
            api_key="test-key",
        )
        assert isinstance(c, NvidiaClient)
        assert c.model == "moonshotai/kimi-k2-thinking"

    def test_factory_default_model(self):
        """LLMFactory.create('nvidia') returns an NvidiaClient (no model kwarg)."""
        c = LLMFactory.create("nvidia", api_key="test-key")
        assert isinstance(c, NvidiaClient)


# ---------------------------------------------------------------------------
# Live integration tests (skipped unless NVIDIA_API_KEY is set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("NVIDIA_API_KEY"),
    reason="NVIDIA_API_KEY not set — skipping live integration test",
)
class TestNvidiaIntegration:
    """End-to-end tests that require a real NVIDIA_API_KEY."""

    @pytest.mark.asyncio
    async def test_completion_e2e_kimi(self):
        """Live completion against moonshotai/kimi-k2-thinking."""
        c = NvidiaClient(model=NvidiaModel.KIMI_K2_THINKING.value)
        response = await c.ask("Say hello in one word.")
        assert response is not None

    @pytest.mark.asyncio
    async def test_streaming_e2e_glm_reasoning(self):
        """Live streaming + enable_thinking against z-ai/glm-5.1."""
        c = NvidiaClient(model=NvidiaModel.GLM_5_1.value)
        chunks = []
        async for chunk in c.ask_stream("Count to three.", enable_thinking=True):
            chunks.append(chunk)
        assert len(chunks) > 0
