"""Unit tests for LocalLLMClient and LocalLLMModel."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.clients.localllm import LocalLLMClient
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.models.localllm import LocalLLMModel


# ---- Model Enum Tests ----

class TestLocalLLMModel:
    """Tests for LocalLLMModel enum."""

    def test_enum_values(self):
        """Enum values match expected model strings."""
        assert LocalLLMModel.LLAMA3_1_8B.value == "llama3.1:8b"
        assert LocalLLMModel.MISTRAL_7B.value == "mistral:7b"
        assert LocalLLMModel.DEEPSEEK_R1.value == "deepseek-r1"
        assert LocalLLMModel.QWEN2_5_7B.value == "qwen2.5:7b"

    def test_custom_placeholder(self):
        """CUSTOM placeholder exists."""
        assert LocalLLMModel.CUSTOM.value == "custom"

    def test_enum_count(self):
        """Enum has at least 15 models."""
        assert len(LocalLLMModel) >= 15


# ---- Client Initialization Tests ----

class TestLocalLLMClientInit:
    """Tests for LocalLLMClient initialization."""

    def test_default_init(self):
        """Default init has correct base_url, no api_key, default model."""
        client = LocalLLMClient()
        assert client.client_type == "localllm"
        assert client.base_url == "http://localhost:8000/v1"
        assert client.api_key is None
        assert client.model == "llama3.1:8b"

    def test_custom_base_url(self):
        """Custom base_url for Ollama."""
        client = LocalLLMClient(base_url="http://localhost:11434/v1")
        assert client.base_url == "http://localhost:11434/v1"

    def test_custom_model(self):
        """Custom model string is set."""
        client = LocalLLMClient(model="mistral:7b")
        assert client.model == "mistral:7b"

    def test_api_key_optional(self):
        """Client works with api_key=None."""
        client = LocalLLMClient()
        assert client.api_key is None

    def test_api_key_provided(self):
        """Client accepts explicit API key."""
        client = LocalLLMClient(api_key="my-secret-key")
        assert client.api_key == "my-secret-key"

    def test_client_type_and_name(self):
        """client_type and client_name are 'localllm'."""
        client = LocalLLMClient()
        assert client.client_type == "localllm"
        assert client.client_name == "localllm"

    def test_all_params_together(self):
        """All params set together."""
        client = LocalLLMClient(
            api_key="key",
            base_url="http://my-server:9000/v1",
            model="phi3:mini"
        )
        assert client.api_key == "key"
        assert client.base_url == "http://my-server:9000/v1"
        assert client.model == "phi3:mini"


# ---- Override Tests ----

class TestLocalLLMClientOverrides:
    """Tests for method overrides."""

    def test_responses_api_always_false(self):
        """_is_responses_model() always returns False for any input."""
        client = LocalLLMClient()
        assert client._is_responses_model("o3") is False
        assert client._is_responses_model("o4-mini") is False
        assert client._is_responses_model("gpt-5") is False
        assert client._is_responses_model("llama3:8b") is False
        assert client._is_responses_model("") is False

    @pytest.mark.asyncio
    async def test_get_client_no_key_placeholder(self):
        """get_client() uses 'no-key' placeholder when api_key is None."""
        client = LocalLLMClient()
        openai_client = await client.get_client()
        assert openai_client.api_key == "no-key"

    @pytest.mark.asyncio
    async def test_get_client_with_key(self):
        """get_client() uses actual key when provided."""
        client = LocalLLMClient(api_key="real-key")
        openai_client = await client.get_client()
        assert openai_client.api_key == "real-key"

    @pytest.mark.asyncio
    async def test_get_client_base_url(self):
        """get_client() uses configured base_url."""
        client = LocalLLMClient(base_url="http://myhost:5000/v1")
        openai_client = await client.get_client()
        # AsyncOpenAI appends trailing slash
        assert "myhost:5000" in str(openai_client.base_url)


# ---- Factory Tests ----

class TestLocalLLMFactory:
    """Tests for LLMFactory registration."""

    @pytest.mark.parametrize("alias", [
        "local", "localllm", "ollama", "vllm", "llamacpp"
    ])
    def test_factory_alias_registered(self, alias):
        """Each alias maps to LocalLLMClient in SUPPORTED_CLIENTS."""
        assert alias in SUPPORTED_CLIENTS
        assert SUPPORTED_CLIENTS[alias] is LocalLLMClient

    def test_factory_create_local(self):
        """LLMFactory.create('local') returns LocalLLMClient."""
        client = LLMFactory.create("local")
        assert isinstance(client, LocalLLMClient)
        assert client.client_type == "localllm"

    def test_factory_create_with_model(self):
        """LLMFactory.create('ollama:llama3:8b') parses model correctly."""
        client = LLMFactory.create("ollama:llama3:8b")
        assert isinstance(client, LocalLLMClient)
        assert client.model == "llama3:8b"

    def test_factory_create_vllm(self):
        """LLMFactory.create('vllm') returns LocalLLMClient."""
        client = LLMFactory.create("vllm")
        assert isinstance(client, LocalLLMClient)

    def test_factory_with_model_args(self):
        """Factory passes model_args through correctly."""
        client = LLMFactory.create(
            "local",
            model_args={"temperature": 0.5, "max_tokens": 2048}
        )
        assert isinstance(client, LocalLLMClient)
        assert client.temperature == 0.5
        assert client.max_tokens == 2048


# ---- Utility Method Tests ----

class TestLocalLLMUtilities:
    """Tests for list_models() and health_check()."""

    @pytest.mark.asyncio
    async def test_list_models(self):
        """list_models() returns model IDs from server."""
        client = LocalLLMClient()

        mock_model_1 = MagicMock()
        mock_model_1.id = "llama3.1:8b"
        mock_model_2 = MagicMock()
        mock_model_2.id = "mistral:7b"
        mock_response = MagicMock()
        mock_response.data = [mock_model_1, mock_model_2]

        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=mock_response)
        client.client = mock_client

        models = await client.list_models()
        assert models == ["llama3.1:8b", "mistral:7b"]

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """health_check() returns True when server responds."""
        client = LocalLLMClient()

        mock_response = MagicMock()
        mock_response.data = []
        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=mock_response)
        client.client = mock_client

        result = await client.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """health_check() returns False when server is unreachable."""
        client = LocalLLMClient()

        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        client.client = mock_client

        result = await client.health_check()
        assert result is False
