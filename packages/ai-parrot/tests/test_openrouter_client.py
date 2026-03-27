"""Unit tests for OpenRouterClient."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.clients.openrouter import OpenRouterClient
from parrot.models.openrouter import (
    ProviderPreferences,
    OpenRouterUsage,
    OpenRouterModel,
)


@pytest.fixture
def client():
    return OpenRouterClient(
        api_key="test-key-123",
        app_name="ai-parrot-test",
        site_url="https://example.com"
    )


@pytest.fixture
def client_with_prefs():
    prefs = ProviderPreferences(
        allow_fallbacks=True,
        order=["DeepInfra", "Together"],
        ignore=["Azure"]
    )
    return OpenRouterClient(
        api_key="test-key-123",
        provider_preferences=prefs
    )


class TestOpenRouterClientInit:
    def test_default_base_url(self, client):
        """Client uses OpenRouter base URL."""
        assert client.base_url == "https://openrouter.ai/api/v1"

    def test_client_type(self, client):
        """Client type is openrouter."""
        assert client.client_type == "openrouter"
        assert client.client_name == "openrouter"

    def test_api_key_stored(self, client):
        """API key is stored from constructor."""
        assert client.api_key == "test-key-123"

    def test_app_name_and_site(self, client):
        """App name and site URL are stored."""
        assert client.app_name == "ai-parrot-test"
        assert client.site_url == "https://example.com"

    def test_provider_preferences_stored(self, client_with_prefs):
        """Provider preferences are stored."""
        assert client_with_prefs.provider_preferences is not None
        assert client_with_prefs.provider_preferences.order == [
            "DeepInfra", "Together"
        ]

    def test_no_provider_preferences_by_default(self, client):
        """No provider preferences by default."""
        assert client.provider_preferences is None

    def test_inherits_openai_client(self, client):
        """Client is a subclass of OpenAIClient."""
        from parrot.clients.gpt import OpenAIClient
        assert isinstance(client, OpenAIClient)


class TestOpenRouterGetClient:
    @pytest.mark.asyncio
    async def test_get_client_returns_async_openai(self, client):
        """get_client returns AsyncOpenAI instance."""
        from openai import AsyncOpenAI
        openai_client = await client.get_client()
        assert isinstance(openai_client, AsyncOpenAI)

    @pytest.mark.asyncio
    async def test_get_client_base_url(self, client):
        """get_client configures OpenRouter base URL."""
        openai_client = await client.get_client()
        assert "openrouter.ai" in str(openai_client.base_url)

    @pytest.mark.asyncio
    async def test_get_client_custom_headers(self, client):
        """get_client sets HTTP-Referer and X-Title headers."""
        openai_client = await client.get_client()
        headers = openai_client._custom_headers
        assert headers.get("HTTP-Referer") == "https://example.com"
        assert headers.get("X-Title") == "ai-parrot-test"


class TestOpenRouterDefaultModel:
    def test_default_model(self, client):
        """Default model is DeepSeek R1."""
        assert client._default_model == OpenRouterModel.DEEPSEEK_R1.value
        assert "deepseek" in client._default_model

    def test_model_override_via_kwargs(self):
        """Model can be overridden via kwargs."""
        client = OpenRouterClient(
            api_key="test-key",
            model="meta-llama/llama-3.3-70b-instruct"
        )
        assert client.model == "meta-llama/llama-3.3-70b-instruct"


class TestProviderExtraBody:
    def test_build_provider_extra_body_with_prefs(self, client_with_prefs):
        """Builds extra_body with provider preferences."""
        extra = client_with_prefs._build_provider_extra_body()
        assert extra is not None
        assert "provider" in extra
        assert extra["provider"]["order"] == ["DeepInfra", "Together"]
        assert extra["provider"]["ignore"] == ["Azure"]

    def test_build_provider_extra_body_without_prefs(self, client):
        """Returns None when no provider preferences set."""
        extra = client._build_provider_extra_body()
        assert extra is None

    def test_extra_body_excludes_none(self, client_with_prefs):
        """Provider preferences exclude None fields."""
        extra = client_with_prefs._build_provider_extra_body()
        provider = extra["provider"]
        assert "data_collection" not in provider
        assert "quantizations" not in provider


class TestOpenRouterUsageTracking:
    @pytest.mark.asyncio
    async def test_get_generation_stats(self, client):
        """get_generation_stats fetches and parses from OpenRouter API."""
        mock_response_data = {
            "data": {
                "id": "gen-abc123",
                "model": "deepseek/deepseek-r1",
                "total_cost": 0.0042,
                "tokens_prompt": 150,
                "tokens_completion": 300,
                "native_tokens_prompt": 145,
                "native_tokens_completion": 295,
                "provider_name": "DeepInfra"
            }
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response_data)
        mock_resp.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False)
        ))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("parrot.clients.openrouter.aiohttp.ClientSession",
                    return_value=mock_session):
            usage = await client.get_generation_stats("gen-abc123")

        assert isinstance(usage, OpenRouterUsage)
        assert usage.generation_id == "gen-abc123"
        assert usage.model == "deepseek/deepseek-r1"
        assert usage.total_cost == 0.0042
        assert usage.prompt_tokens == 150
        assert usage.completion_tokens == 300
        assert usage.native_tokens_prompt == 145
        assert usage.native_tokens_completion == 295
        assert usage.provider_name == "DeepInfra"

    @pytest.mark.asyncio
    async def test_list_models(self, client):
        """list_models fetches and returns model list."""
        mock_response_data = {
            "data": [
                {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1"},
                {"id": "meta-llama/llama-3.3-70b-instruct", "name": "Llama 3.3 70B"},
            ]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response_data)
        mock_resp.raise_for_status = MagicMock()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False)
        ))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("parrot.clients.openrouter.aiohttp.ClientSession",
                    return_value=mock_session):
            models = await client.list_models()

        assert isinstance(models, list)
        assert len(models) == 2
        assert models[0]["id"] == "deepseek/deepseek-r1"
        assert models[1]["id"] == "meta-llama/llama-3.3-70b-instruct"


class TestChatCompletionOverride:
    @pytest.mark.asyncio
    async def test_chat_completion_injects_provider_prefs(self, client_with_prefs):
        """_chat_completion injects provider preferences in extra_body."""
        with patch(
            "parrot.clients.gpt.OpenAIClient._chat_completion",
            new_callable=AsyncMock
        ) as mock_super:
            mock_super.return_value = MagicMock()
            await client_with_prefs._chat_completion(
                model="deepseek/deepseek-r1",
                messages=[{"role": "user", "content": "hi"}],
            )
            _, kwargs = mock_super.call_args
            assert "extra_body" in kwargs
            assert "provider" in kwargs["extra_body"]
            assert kwargs["extra_body"]["provider"]["order"] == [
                "DeepInfra", "Together"
            ]

    @pytest.mark.asyncio
    async def test_chat_completion_no_extra_body_without_prefs(self, client):
        """_chat_completion does not inject extra_body without preferences."""
        with patch(
            "parrot.clients.gpt.OpenAIClient._chat_completion",
            new_callable=AsyncMock
        ) as mock_super:
            mock_super.return_value = MagicMock()
            await client._chat_completion(
                model="deepseek/deepseek-r1",
                messages=[{"role": "user", "content": "hi"}],
            )
            _, kwargs = mock_super.call_args
            assert "extra_body" not in kwargs

    @pytest.mark.asyncio
    async def test_chat_completion_merges_existing_extra_body(self, client_with_prefs):
        """_chat_completion merges with existing extra_body."""
        with patch(
            "parrot.clients.gpt.OpenAIClient._chat_completion",
            new_callable=AsyncMock
        ) as mock_super:
            mock_super.return_value = MagicMock()
            await client_with_prefs._chat_completion(
                model="deepseek/deepseek-r1",
                messages=[{"role": "user", "content": "hi"}],
                extra_body={"custom_key": "custom_value"}
            )
            _, kwargs = mock_super.call_args
            assert kwargs["extra_body"]["custom_key"] == "custom_value"
            assert "provider" in kwargs["extra_body"]
