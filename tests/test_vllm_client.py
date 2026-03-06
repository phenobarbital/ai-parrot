"""Unit tests for vLLMClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from parrot.clients.vllm import vLLMClient
from parrot.models.vllm import VLLMServerInfo


# ---- Client Initialization Tests ----

class TestVLLMClientInit:
    """Tests for vLLMClient initialization."""

    def test_default_values(self):
        """Default init has correct values."""
        client = vLLMClient()
        assert client.client_type == "vllm"
        assert client.client_name == "vllm"
        assert client.base_url == "http://localhost:8000/v1"
        assert client.timeout == 120

    def test_custom_base_url(self):
        """Custom base_url is used."""
        client = vLLMClient(base_url="http://custom:9000/v1")
        assert client.base_url == "http://custom:9000/v1"

    def test_custom_api_key(self):
        """Custom api_key is used."""
        client = vLLMClient(api_key="my-secret-key")
        assert client.api_key == "my-secret-key"

    def test_custom_timeout(self):
        """Custom timeout is used."""
        client = vLLMClient(timeout=300)
        assert client.timeout == 300

    def test_env_var_vllm_base_url(self, monkeypatch):
        """VLLM_BASE_URL env var is used."""
        monkeypatch.setenv("VLLM_BASE_URL", "http://env-vllm:8000/v1")
        client = vLLMClient()
        assert client.base_url == "http://env-vllm:8000/v1"

    def test_env_var_vllm_api_key(self, monkeypatch):
        """VLLM_API_KEY env var is used."""
        monkeypatch.setenv("VLLM_API_KEY", "env-api-key")
        client = vLLMClient()
        assert client.api_key == "env-api-key"

    def test_explicit_overrides_env_var(self, monkeypatch):
        """Explicit params override env vars."""
        monkeypatch.setenv("VLLM_BASE_URL", "http://env:8000/v1")
        monkeypatch.setenv("VLLM_API_KEY", "env-key")

        client = vLLMClient(
            base_url="http://explicit:9000/v1",
            api_key="explicit-key"
        )
        assert client.base_url == "http://explicit:9000/v1"
        assert client.api_key == "explicit-key"

    def test_fallback_to_local_llm_env_vars(self, monkeypatch):
        """Falls back to LOCAL_LLM_* env vars if VLLM_* not set."""
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://local-llm:8000/v1")
        monkeypatch.setenv("LOCAL_LLM_API_KEY", "local-llm-key")

        client = vLLMClient()
        assert client.base_url == "http://local-llm:8000/v1"
        assert client.api_key == "local-llm-key"


# ---- Helper Method Tests ----

class TestVLLMClientHelpers:
    """Tests for helper methods."""

    def test_get_base_url_root_with_v1(self):
        """_get_base_url_root strips /v1 suffix."""
        client = vLLMClient(base_url="http://localhost:8000/v1")
        assert client._get_base_url_root() == "http://localhost:8000"

    def test_get_base_url_root_with_trailing_slash(self):
        """_get_base_url_root handles trailing slash."""
        client = vLLMClient(base_url="http://localhost:8000/v1/")
        assert client._get_base_url_root() == "http://localhost:8000"

    def test_get_base_url_root_without_v1(self):
        """_get_base_url_root works without /v1."""
        client = vLLMClient(base_url="http://localhost:8000")
        assert client._get_base_url_root() == "http://localhost:8000"


# ---- ask() Method Tests ----

class TestVLLMClientAsk:
    """Tests for vLLMClient.ask() method."""

    @pytest.mark.asyncio
    async def test_basic_ask_calls_parent(self):
        """Basic ask() calls parent with correct params."""
        client = vLLMClient()

        # Mock the parent's ask method
        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_response = MagicMock()
            mock_response.content = "Hello!"
            mock_ask.return_value = mock_response

            await client.ask("Hi", model="test-model")

            mock_ask.assert_called_once()
            call_kwargs = mock_ask.call_args.kwargs
            assert call_kwargs["prompt"] == "Hi"
            assert call_kwargs["model"] == "test-model"

    @pytest.mark.asyncio
    async def test_guided_json_parameter(self):
        """guided_json is passed in extra_body."""
        client = vLLMClient()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content='{"name": "Alice"}')

            await client.ask("Extract name", model="test", guided_json=schema)

            call_kwargs = mock_ask.call_args.kwargs
            assert call_kwargs["extra_body"]["guided_json"] == schema

    @pytest.mark.asyncio
    async def test_guided_regex_parameter(self):
        """guided_regex is passed in extra_body."""
        client = vLLMClient()

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content="123-4567")

            await client.ask("Phone number", model="test", guided_regex=r"\d{3}-\d{4}")

            call_kwargs = mock_ask.call_args.kwargs
            assert call_kwargs["extra_body"]["guided_regex"] == r"\d{3}-\d{4}"

    @pytest.mark.asyncio
    async def test_guided_choice_parameter(self):
        """guided_choice is passed in extra_body."""
        client = vLLMClient()
        choices = ["yes", "no", "maybe"]

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content="yes")

            await client.ask("Choose one", model="test", guided_choice=choices)

            call_kwargs = mock_ask.call_args.kwargs
            assert call_kwargs["extra_body"]["guided_choice"] == choices

    @pytest.mark.asyncio
    async def test_guided_grammar_parameter(self):
        """guided_grammar is passed in extra_body."""
        client = vLLMClient()
        grammar = "root ::= 'hello' | 'world'"

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content="hello")

            await client.ask("Say something", model="test", guided_grammar=grammar)

            call_kwargs = mock_ask.call_args.kwargs
            assert call_kwargs["extra_body"]["guided_grammar"] == grammar

    @pytest.mark.asyncio
    async def test_structured_output_converts_to_guided_json(self):
        """structured_output Pydantic model is converted to guided_json."""

        class Person(BaseModel):
            name: str
            age: int

        client = vLLMClient()

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content='{"name": "Bob", "age": 30}')

            await client.ask("Extract person", model="test", structured_output=Person)

            call_kwargs = mock_ask.call_args.kwargs
            guided_json = call_kwargs["extra_body"]["guided_json"]
            assert "properties" in guided_json
            assert "name" in guided_json["properties"]
            assert "age" in guided_json["properties"]

    @pytest.mark.asyncio
    async def test_lora_adapter_parameter(self):
        """lora_adapter is passed in extra_body."""
        client = vLLMClient()

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response")

            await client.ask("Test", model="test", lora_adapter="my-lora-v1")

            call_kwargs = mock_ask.call_args.kwargs
            assert call_kwargs["extra_body"]["lora_request"] == {"lora_name": "my-lora-v1"}

    @pytest.mark.asyncio
    async def test_extended_sampling_parameters(self):
        """Extended sampling parameters are passed in extra_body."""
        client = vLLMClient()

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response")

            await client.ask(
                "Test",
                model="test",
                top_k=50,
                min_p=0.1,
                repetition_penalty=1.2,
                length_penalty=0.9
            )

            call_kwargs = mock_ask.call_args.kwargs
            extra_body = call_kwargs["extra_body"]
            assert extra_body["top_k"] == 50
            assert extra_body["min_p"] == 0.1
            assert extra_body["repetition_penalty"] == 1.2
            assert extra_body["length_penalty"] == 0.9

    @pytest.mark.asyncio
    async def test_default_sampling_params_not_included(self):
        """Default sampling parameters are not included in extra_body."""
        client = vLLMClient()

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response")

            await client.ask("Test", model="test")

            call_kwargs = mock_ask.call_args.kwargs
            # extra_body should be None or empty when no vLLM params set
            extra_body = call_kwargs.get("extra_body")
            assert extra_body is None or extra_body == {}

    @pytest.mark.asyncio
    async def test_multiple_guided_constraints_raises_error(self):
        """Specifying multiple guided constraints raises ValueError."""
        client = vLLMClient()

        with pytest.raises(ValueError) as exc_info:
            await client.ask(
                "Test",
                model="test",
                guided_json={"type": "object"},
                guided_regex=r"\d+"
            )
        assert "Only one guided constraint" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_structured_output_with_guided_json_uses_explicit(self):
        """When both structured_output and guided_json are provided, guided_json wins."""

        class Person(BaseModel):
            name: str

        client = vLLMClient()
        explicit_schema = {"type": "string"}  # Different from Person schema

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.return_value = MagicMock(content="test")

            await client.ask(
                "Test",
                model="test",
                guided_json=explicit_schema,
                structured_output=Person
            )

            call_kwargs = mock_ask.call_args.kwargs
            # structured_output should be ignored when guided_json is explicit
            assert call_kwargs["extra_body"]["guided_json"] == explicit_schema


# ---- ask_stream() Method Tests ----

class TestVLLMClientAskStream:
    """Tests for vLLMClient.ask_stream() method."""

    @pytest.mark.asyncio
    async def test_basic_stream(self):
        """Basic streaming works."""
        client = vLLMClient()

        async def mock_stream(*args, **kwargs):
            for chunk in ["Hello", " ", "World"]:
                yield chunk

        with patch.object(
            client.__class__.__bases__[0],
            'ask_stream',
            mock_stream
        ):
            chunks = []
            async for chunk in client.ask_stream("Hi", model="test"):
                chunks.append(chunk)

            assert chunks == ["Hello", " ", "World"]

    @pytest.mark.asyncio
    async def test_stream_with_guided_json(self):
        """Streaming with guided_json passes extra_body."""
        client = vLLMClient()
        schema = {"type": "object"}
        captured_kwargs = {}

        async def mock_stream(*args, **kwargs):
            captured_kwargs.update(kwargs)
            yield '{"test": true}'

        with patch.object(
            client.__class__.__bases__[0],
            'ask_stream',
            mock_stream
        ):
            async for _ in client.ask_stream("Test", model="test", guided_json=schema):
                pass

            assert captured_kwargs["extra_body"]["guided_json"] == schema

    @pytest.mark.asyncio
    async def test_stream_multiple_guided_raises_error(self):
        """Multiple guided constraints in stream raises ValueError."""
        client = vLLMClient()

        with pytest.raises(ValueError) as exc_info:
            async for _ in client.ask_stream(
                "Test",
                model="test",
                guided_json={"type": "object"},
                guided_choice=["a", "b"]
            ):
                pass
        assert "Only one guided constraint" in str(exc_info.value)


# ---- health_check() Tests ----

class TestVLLMClientHealthCheck:
    """Tests for vLLMClient.health_check() method."""

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """health_check returns True when server responds 200."""
        client = vLLMClient()

        with patch('parrot.clients.vllm.aiohttp.ClientSession') as mock_session_cls:
            mock_response = MagicMock()
            mock_response.status = 200

            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session.get = MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock()
            ))
            mock_session_cls.return_value = mock_session

            result = await client.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure_non_200(self):
        """health_check returns False when server responds non-200."""
        client = vLLMClient()

        with patch('parrot.clients.vllm.aiohttp.ClientSession') as mock_session_cls:
            mock_response = MagicMock()
            mock_response.status = 503

            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session.get = MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock()
            ))
            mock_session_cls.return_value = mock_session

            result = await client.health_check()
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        """health_check returns False when connection fails."""
        client = vLLMClient()

        with patch('parrot.clients.vllm.aiohttp.ClientSession') as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
            mock_session.__aexit__ = AsyncMock()
            mock_session_cls.return_value = mock_session

            result = await client.health_check()
            assert result is False


# ---- server_info() Tests ----

class TestVLLMClientServerInfo:
    """Tests for vLLMClient.server_info() method."""

    @pytest.mark.asyncio
    async def test_server_info_success(self):
        """server_info returns VLLMServerInfo on success."""
        client = vLLMClient()

        with patch('parrot.clients.vllm.aiohttp.ClientSession') as mock_session_cls:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={
                "version": "0.4.0",
                "model_id": "llama3:8b",
                "gpu_memory_utilization": 0.9,
                "max_model_len": 8192,
                "tensor_parallel_size": 1
            })

            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_session.get = MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock()
            ))
            mock_session_cls.return_value = mock_session

            result = await client.server_info()

            assert isinstance(result, VLLMServerInfo)
            assert result.version == "0.4.0"
            assert result.model_id == "llama3:8b"
            assert result.gpu_memory_utilization == 0.9
            assert result.max_model_len == 8192

    @pytest.mark.asyncio
    async def test_server_info_non_200_raises_error(self):
        """server_info raises ConnectionError on non-200 response."""
        client = vLLMClient()

        # Create a properly nested mock for aiohttp async context managers
        mock_response = MagicMock()
        mock_response.status = 500

        # Mock for `async with session.get(...) as resp`
        mock_get_ctx = MagicMock()
        mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

        # Mock for `async with ClientSession() as session`
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_ctx)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch('parrot.clients.vllm.aiohttp.ClientSession', return_value=mock_session_ctx):
            with pytest.raises(ConnectionError) as exc_info:
                await client.server_info()
            assert "HTTP 500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_server_info_connection_error(self):
        """server_info raises ConnectionError when connection fails."""
        client = vLLMClient()

        import aiohttp

        # Mock for `async with ClientSession() as session`
        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("Connection refused"))

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch('parrot.clients.vllm.aiohttp.ClientSession', return_value=mock_session_ctx):
            with pytest.raises(ConnectionError) as exc_info:
                await client.server_info()
            assert "Cannot connect" in str(exc_info.value)


# ---- list_models() Tests ----

class TestVLLMClientListModels:
    """Tests for vLLMClient.list_models() method."""

    @pytest.mark.asyncio
    async def test_list_models_success(self):
        """list_models returns list of model IDs."""
        client = vLLMClient()

        mock_models = MagicMock()
        mock_models.data = [
            MagicMock(id="llama3:8b"),
            MagicMock(id="mistral:7b"),
            MagicMock(id="qwen2.5:7b"),
        ]

        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(return_value=mock_models)
        client.client = mock_client

        result = await client.list_models()

        assert result == ["llama3:8b", "mistral:7b", "qwen2.5:7b"]

    @pytest.mark.asyncio
    async def test_list_models_connection_error(self):
        """list_models raises ConnectionError on failure."""
        client = vLLMClient()

        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(side_effect=Exception("Server error"))
        client.client = mock_client

        with pytest.raises(ConnectionError) as exc_info:
            await client.list_models()
        assert "Cannot list models" in str(exc_info.value)


# ---- batch_process() Tests ----

class TestVLLMClientBatchProcess:
    """Tests for vLLMClient.batch_process() method."""

    @pytest.mark.asyncio
    async def test_batch_process_single_request(self):
        """batch_process handles single request."""
        client = vLLMClient()

        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response 1")

            requests = [{"prompt": "Question 1", "model": "test"}]
            results = await client.batch_process(requests)

            assert len(results) == 1
            assert mock_ask.call_count == 1

    @pytest.mark.asyncio
    async def test_batch_process_multiple_requests(self):
        """batch_process handles multiple requests concurrently."""
        client = vLLMClient()

        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            mock_ask.side_effect = [
                MagicMock(content="Response 1"),
                MagicMock(content="Response 2"),
                MagicMock(content="Response 3"),
            ]

            requests = [
                {"prompt": "Q1", "model": "test"},
                {"prompt": "Q2", "model": "test"},
                {"prompt": "Q3", "model": "test"},
            ]
            results = await client.batch_process(requests)

            assert len(results) == 3
            assert mock_ask.call_count == 3

    @pytest.mark.asyncio
    async def test_batch_process_with_kwargs(self):
        """batch_process applies default kwargs to all requests."""
        client = vLLMClient()

        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response")

            requests = [{"prompt": "Q1"}, {"prompt": "Q2"}]
            await client.batch_process(requests, model="shared-model", temperature=0.5)

            # Both calls should have the shared kwargs
            for call in mock_ask.call_args_list:
                assert call.kwargs["model"] == "shared-model"
                assert call.kwargs["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_batch_process_request_overrides_kwargs(self):
        """Individual request params override default kwargs."""
        client = vLLMClient()

        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response")

            requests = [
                {"prompt": "Q1", "temperature": 0.9},  # Override
                {"prompt": "Q2"},  # Use default
            ]
            await client.batch_process(requests, temperature=0.5)

            # First call has overridden temperature
            assert mock_ask.call_args_list[0].kwargs["temperature"] == 0.9
            # Second call uses default
            assert mock_ask.call_args_list[1].kwargs["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_batch_process_empty_list_raises_error(self):
        """batch_process raises ValueError for empty list."""
        client = vLLMClient()

        with pytest.raises(ValueError) as exc_info:
            await client.batch_process([])
        assert "cannot be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_batch_process_preserves_order(self):
        """batch_process returns results in same order as requests."""
        client = vLLMClient()

        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            # Simulate different response times (but asyncio.gather preserves order)
            mock_ask.side_effect = [
                MagicMock(content="First"),
                MagicMock(content="Second"),
                MagicMock(content="Third"),
            ]

            requests = [
                {"prompt": "1", "model": "test"},
                {"prompt": "2", "model": "test"},
                {"prompt": "3", "model": "test"},
            ]
            results = await client.batch_process(requests)

            assert results[0].content == "First"
            assert results[1].content == "Second"
            assert results[2].content == "Third"

    @pytest.mark.asyncio
    async def test_batch_process_does_not_mutate_input(self):
        """batch_process does not modify input request dicts."""
        client = vLLMClient()

        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response")

            original_request = {"prompt": "Test", "model": "test"}
            requests = [original_request]
            await client.batch_process(requests)

            # Original dict should be unchanged
            assert "prompt" in original_request
            assert original_request["prompt"] == "Test"

    @pytest.mark.asyncio
    async def test_batch_process_with_guided_json(self):
        """batch_process works with guided_json in requests."""
        client = vLLMClient()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = MagicMock(content='{"name": "Alice"}')

            requests = [
                {"prompt": "Extract name", "model": "test", "guided_json": schema}
            ]
            await client.batch_process(requests)

            call_kwargs = mock_ask.call_args.kwargs
            assert call_kwargs["guided_json"] == schema


# ---- Error Handling Tests ----

class TestVLLMClientErrorHandling:
    """Tests for error handling in vLLMClient."""

    @pytest.mark.asyncio
    async def test_ask_propagates_parent_errors(self):
        """ask() propagates errors from parent class."""
        client = vLLMClient()

        with patch.object(
            client.__class__.__bases__[0],
            'ask',
            new_callable=AsyncMock
        ) as mock_ask:
            mock_ask.side_effect = Exception("API Error")

            with pytest.raises(Exception) as exc_info:
                await client.ask("Test", model="test")
            assert "API Error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_list_models_includes_base_url_in_error(self):
        """list_models error message includes base_url."""
        client = vLLMClient(base_url="http://my-server:8000/v1")

        mock_client = MagicMock()
        mock_client.models.list = AsyncMock(side_effect=Exception("Timeout"))
        client.client = mock_client

        with pytest.raises(ConnectionError) as exc_info:
            await client.list_models()
        assert "my-server:8000" in str(exc_info.value)
