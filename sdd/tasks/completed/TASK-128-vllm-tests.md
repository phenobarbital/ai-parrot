# TASK-128: vLLM Client Unit Tests

**Feature**: FEAT-022 vLLM Client Integration
**Spec**: `sdd/specs/vllm-client.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-125, TASK-126, TASK-127
**Assigned-to**: claude-session

---

## Context

> This task implements Module 5 from the spec: Unit Tests.

Write comprehensive unit tests for vLLMClient and vLLM models.

---

## Scope

- Test vLLM Pydantic models
- Test vLLMClient initialization and env var resolution
- Test `ask()` with standard and vLLM-specific parameters
- Test `ask_stream()` streaming functionality
- Test `structured_output` parameter (Pydantic → guided_json)
- Test guided output parameters (json, regex, choice)
- Test LoRA adapter parameter
- Test extended sampling parameters
- Test `health_check()`, `list_models()`, `server_info()`
- Test `batch_process()` functionality
- Test error handling (connection, timeout, model not found)

**NOT in scope**:
- Integration tests with real vLLM server (requires running server)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_vllm_client.py` | CREATE | vLLMClient unit tests |
| `tests/test_vllm_models.py` | CREATE | vLLM model tests |

---

## Implementation Notes

### Test Structure

```python
# tests/test_vllm_models.py
import pytest
from pydantic import BaseModel
from parrot.models.vllm import (
    VLLMConfig,
    VLLMSamplingParams,
    VLLMGuidedParams,
    VLLMLoRARequest,
    pydantic_to_guided_json,
)


class TestVLLMConfig:
    def test_default_values(self):
        config = VLLMConfig()
        assert config.base_url == "http://localhost:8000/v1"
        assert config.api_key is None
        assert config.timeout == 120

    def test_custom_values(self):
        config = VLLMConfig(base_url="http://custom:9000/v1", api_key="secret", timeout=60)
        assert config.base_url == "http://custom:9000/v1"


class TestVLLMSamplingParams:
    def test_default_values(self):
        params = VLLMSamplingParams()
        assert params.top_k == -1
        assert params.min_p == 0.0
        assert params.repetition_penalty == 1.0

    def test_validation(self):
        with pytest.raises(ValueError):
            VLLMSamplingParams(min_p=2.0)  # Must be <= 1.0


class TestPydanticToGuidedJson:
    def test_simple_model(self):
        class Person(BaseModel):
            name: str
            age: int

        schema = pydantic_to_guided_json(Person)
        assert schema["type"] == "object"
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]
```

### Client Tests

```python
# tests/test_vllm_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.clients.vllm import vLLMClient


class TestVLLMClientInit:
    def test_default_base_url(self):
        client = vLLMClient()
        assert "localhost:8000" in client.base_url

    def test_env_var_base_url(self, monkeypatch):
        monkeypatch.setenv("VLLM_BASE_URL", "http://custom:9000/v1")
        client = vLLMClient()
        assert client.base_url == "http://custom:9000/v1"

    def test_explicit_base_url_overrides_env(self, monkeypatch):
        monkeypatch.setenv("VLLM_BASE_URL", "http://env:9000/v1")
        client = vLLMClient(base_url="http://explicit:8000/v1")
        assert client.base_url == "http://explicit:8000/v1"


class TestVLLMClientAsk:
    @pytest.mark.asyncio
    async def test_basic_ask(self):
        client = vLLMClient()
        with patch.object(client, 'client') as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]
            mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            result = await client.ask("Hi", model="test-model")
            assert result.content == "Hello!"

    @pytest.mark.asyncio
    async def test_guided_json_parameter(self):
        client = vLLMClient()
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        with patch.object(client, 'client') as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content='{"name": "Alice"}'))]
            mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            await client.ask("Extract name", model="test", guided_json=schema)

            # Verify extra_body was passed with guided_json
            call_args = mock_client.chat.completions.create.call_args
            assert call_args.kwargs.get("extra_body", {}).get("guided_json") == schema

    @pytest.mark.asyncio
    async def test_structured_output_converts_to_guided_json(self):
        from pydantic import BaseModel

        class Person(BaseModel):
            name: str
            age: int

        client = vLLMClient()
        with patch.object(client, 'client') as mock_client:
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content='{"name": "Bob", "age": 30}'))]
            mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            await client.ask("Get person info", model="test", structured_output=Person)

            # Verify guided_json schema was generated
            call_args = mock_client.chat.completions.create.call_args
            extra_body = call_args.kwargs.get("extra_body", {})
            assert "guided_json" in extra_body
            assert extra_body["guided_json"]["properties"]["name"]["type"] == "string"


class TestVLLMClientDiagnostics:
    @pytest.mark.asyncio
    async def test_health_check_success(self):
        client = vLLMClient()
        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            result = await client.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        client = vLLMClient()
        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.return_value.__aenter__.return_value.get.side_effect = Exception("Connection refused")

            result = await client.health_check()
            assert result is False


class TestVLLMClientBatch:
    @pytest.mark.asyncio
    async def test_batch_process(self):
        client = vLLMClient()
        with patch.object(client, 'ask', new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = MagicMock(content="Response")

            requests = [
                {"prompt": "Question 1", "model": "test"},
                {"prompt": "Question 2", "model": "test"},
            ]

            results = await client.batch_process(requests)

            assert len(results) == 2
            assert mock_ask.call_count == 2
```

---

## Acceptance Criteria

- [ ] All vLLM model tests pass
- [ ] vLLMClient initialization tests pass
- [ ] Environment variable resolution tests pass
- [ ] `ask()` with guided_json parameter tests pass
- [ ] `ask()` with structured_output parameter tests pass
- [ ] `ask()` with lora_adapter parameter tests pass
- [ ] `ask()` with extended sampling parameters tests pass
- [ ] `ask_stream()` tests pass
- [ ] `health_check()` tests pass (success and failure cases)
- [ ] `list_models()` tests pass
- [ ] `server_info()` tests pass
- [ ] `batch_process()` tests pass
- [ ] Error handling tests pass
- [ ] All tests pass: `pytest tests/test_vllm_client.py tests/test_vllm_models.py -v`
- [ ] Code coverage > 90%

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-125, TASK-126, TASK-127 are in `tasks/completed/`
3. **Read** the actual implementation files to understand what to test
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Create** test files with comprehensive coverage
6. **Run tests** and ensure all pass
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-128-vllm-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-04
**Notes**:
- Created `tests/test_vllm_models.py` with 37 tests covering all vLLM Pydantic models
- Created `tests/test_vllm_client.py` with 43 tests covering vLLMClient
- Tests cover:
  - VLLMConfig, VLLMSamplingParams, VLLMLoRARequest, VLLMGuidedParams models
  - VLLMBatchRequest, VLLMBatchResponse, VLLMServerInfo models
  - pydantic_to_guided_json helper function
  - vLLMClient initialization and env var resolution
  - ask() with guided_json, guided_regex, guided_choice, guided_grammar
  - ask() with structured_output parameter
  - ask() with lora_adapter parameter
  - ask() with extended sampling parameters
  - ask_stream() streaming functionality
  - health_check() success and failure cases
  - server_info() success and error handling
  - list_models() success and error handling
  - batch_process() with various scenarios
  - Error handling and validation
- All 80 tests pass
- Linting passes
