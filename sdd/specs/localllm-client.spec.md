# Feature Specification: LocalLLMClient

**Feature ID**: FEAT-006
**Date**: 2026-02-18
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement
AI-Parrot currently requires cloud-hosted LLM providers (OpenAI, Anthropic, Google, etc.)
for all interactions. Users running local LLM servers — Ollama, vLLM, or llama.cpp —
cannot use the framework without manually configuring the OpenAIClient with a custom
`base_url` and workarounds. A dedicated `LocalLLMClient` would provide first-class
support for local/self-hosted OpenAI-compatible LLM servers with sensible defaults
(no API key required, configurable base URL, local-friendly model defaults).

### Goals
- Provide a dedicated `LocalLLMClient` that inherits from `AbstractClient` and follows
  the same pattern as `OpenAIClient`
- Support any OpenAI-compatible local server (Ollama, vLLM, llama.cpp, LM Studio, etc.)
  via a configurable `base_url`
- Full feature parity with `OpenAIClient`: completion, streaming, tool calling,
  structured output, vision, embeddings
- Optional API key (defaults to `None` / no auth for local servers)
- Register in `LLMFactory` as `"local"` / `"localllm"` / `"ollama"` / `"vllm"`

### Non-Goals (explicitly out of scope)
- Backend-specific optimizations (auto-detecting Ollama vs vLLM)
- Ollama-native API support (only OpenAI-compatible `/v1` endpoints)
- Model management (pulling/deleting models from Ollama, etc.)
- Embedding-only specialized client

---

## 2. Architectural Design

### Overview
`LocalLLMClient` extends `OpenAIClient` (not `AbstractClient` directly) to reuse all
OpenAI-compatible logic — chat completions, tool loop, streaming, structured output,
vision. The key differences are:

1. **Default `base_url`**: `http://localhost:8000/v1` (vLLM default)
2. **Optional `api_key`**: Defaults to `None`; sends `"no-key"` placeholder when `None`
   (some servers require a non-empty bearer token)
3. **Model enum**: A new `LocalLLMModel` enum with common local model names
4. **Client type**: `client_type = "localllm"`
5. **No Responses API**: Local servers don't support OpenAI Responses API; always
   use Chat Completions path
6. **Relaxed model guards**: Skip `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` checks
   (local servers may support structured output on any model)

### Component Diagram
```
LocalLLMClient ──extends──→ OpenAIClient ──extends──→ AbstractClient
       │                          │
       │                          └──→ AsyncOpenAI(base_url=...)
       │
       └──→ LocalLLMModel (enum)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OpenAIClient` | extends | Inherits completion, streaming, tool loop, vision |
| `AbstractClient` | extends (indirect) | Via OpenAIClient |
| `LLMFactory` | registers | Added as `local`, `localllm`, `ollama`, `vllm`, `llamacpp` |
| `AsyncOpenAI` | uses | OpenAI SDK with custom `base_url` |
| `AIMessageFactory` | uses | Same message factory as OpenAIClient |

### Data Models
```python
from enum import Enum

class LocalLLMModel(Enum):
    """Common local LLM model identifiers."""
    LLAMA3_8B = "llama3:8b"
    LLAMA3_70B = "llama3:70b"
    LLAMA3_1_8B = "llama3.1:8b"
    LLAMA3_1_70B = "llama3.1:70b"
    LLAMA3_2_3B = "llama3.2:3b"
    LLAMA3_3_70B = "llama3.3:70b"
    MISTRAL_7B = "mistral:7b"
    MIXTRAL_8X7B = "mixtral:8x7b"
    CODELLAMA_13B = "codellama:13b"
    QWEN2_5_7B = "qwen2.5:7b"
    QWEN2_5_72B = "qwen2.5:72b"
    DEEPSEEK_R1 = "deepseek-r1"
    DEEPSEEK_V3 = "deepseek-v3"
    PHI3_MINI = "phi3:mini"
    GEMMA2_9B = "gemma2:9b"
    # Generic placeholder for any custom model
    CUSTOM = "custom"
```

### New Public Interfaces
```python
class LocalLLMClient(OpenAIClient):
    """Client for local/self-hosted OpenAI-compatible LLM servers."""

    client_type: str = "localllm"
    client_name: str = "localllm"
    model: str = "llama3.1:8b"
    _default_model: str = "llama3.1:8b"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "http://localhost:8000/v1",
        model: Optional[str] = None,
        **kwargs
    ):
        ...

    async def get_client(self) -> AsyncOpenAI:
        """Initialize AsyncOpenAI with local server URL."""
        ...

    def _is_responses_model(self, model_str: str) -> bool:
        """Always returns False — local servers don't support Responses API."""
        return False

    async def list_models(self) -> List[str]:
        """List models available on the local server."""
        ...

    async def health_check(self) -> bool:
        """Check if the local server is reachable."""
        ...
```

---

## 3. Module Breakdown

### Module 1: LocalLLMModel Enum
- **Path**: `parrot/models/localllm.py`
- **Responsibility**: Define common local model identifiers as an Enum
- **Depends on**: None

### Module 2: LocalLLMClient
- **Path**: `parrot/clients/localllm.py`
- **Responsibility**: Main client class extending OpenAIClient for local servers
- **Depends on**: Module 1, `OpenAIClient`, `AbstractClient`

### Module 3: Factory Registration
- **Path**: `parrot/clients/factory.py` (modify)
- **Responsibility**: Register LocalLLMClient in `SUPPORTED_CLIENTS` and `LLMFactory`
- **Depends on**: Module 2

### Module 4: Unit Tests
- **Path**: `tests/test_localllm_client.py`
- **Responsibility**: Unit tests for LocalLLMClient initialization, config, overrides
- **Depends on**: Module 2

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_default_init` | Module 2 | Default base_url, no api_key, default model |
| `test_custom_base_url` | Module 2 | Custom base_url for Ollama (`localhost:11434/v1`) |
| `test_custom_model` | Module 2 | Pass custom model string |
| `test_api_key_optional` | Module 2 | Client works with `api_key=None` |
| `test_api_key_provided` | Module 2 | Client accepts explicit API key |
| `test_responses_api_disabled` | Module 2 | `_is_responses_model()` always returns False |
| `test_client_type` | Module 2 | `client_type == "localllm"` |
| `test_factory_registration` | Module 3 | `LLMFactory.create("local")` returns `LocalLLMClient` |
| `test_factory_with_model` | Module 3 | `LLMFactory.create("ollama:llama3:8b")` works |
| `test_list_models` | Module 2 | `list_models()` returns available models |
| `test_health_check` | Module 2 | `health_check()` returns True/False |

### Integration Tests
| Test | Description |
|---|---|
| `test_local_completion` | Full ask() call against a running local server (skip if unavailable) |
| `test_local_streaming` | Streaming ask_stream() against local server |
| `test_local_tool_calling` | Tool calling loop with local model |

### Test Data / Fixtures
```python
import pytest

@pytest.fixture
def local_client():
    """Create a LocalLLMClient with default settings."""
    return LocalLLMClient()

@pytest.fixture
def ollama_client():
    """Create a LocalLLMClient pointing to Ollama."""
    return LocalLLMClient(
        base_url="http://localhost:11434/v1",
        model="llama3.1:8b"
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `LocalLLMClient` class exists at `parrot/clients/localllm.py`
- [ ] Extends `OpenAIClient` and inherits all completion/streaming/tool/vision behavior
- [ ] Default `base_url` is `http://localhost:8000/v1`
- [ ] `api_key` is optional (defaults to `None`)
- [ ] `_is_responses_model()` always returns `False`
- [ ] `LocalLLMModel` enum exists at `parrot/models/localllm.py`
- [ ] Registered in `LLMFactory` as `local`, `localllm`, `ollama`, `vllm`, `llamacpp`
- [ ] `list_models()` queries the server's `/models` endpoint
- [ ] `health_check()` verifies server connectivity
- [ ] All unit tests pass: `pytest tests/test_localllm_client.py -v`
- [ ] No breaking changes to existing clients or public API
- [ ] Google-style docstrings on all public methods
- [ ] Type hints on all function signatures

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Follow `OpenAIClient` pattern exactly — extend, don't rewrite
- Use `AsyncOpenAI` from the `openai` SDK with custom `base_url`
- Use `navconfig.config` for environment variable fallbacks (`LOCAL_LLM_BASE_URL`, `LOCAL_LLM_API_KEY`)
- Pydantic models for any structured data
- `self.logger` for all logging

### Key Overrides from OpenAIClient
```python
# 1. No Responses API
def _is_responses_model(self, model_str: str) -> bool:
    return False

# 2. Relaxed structured output check — don't switch models
# Override or skip the STRUCTURED_OUTPUT_COMPATIBLE_MODELS guard

# 3. API key handling — use placeholder for servers that require non-empty bearer
async def get_client(self) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=self.api_key or "no-key",
        base_url=self.base_url,
        timeout=config.get('LOCAL_LLM_TIMEOUT', 120),
    )
```

### Known Risks / Gotchas
- Local servers may have inconsistent tool-calling support — some models support it,
  others don't. The client should work gracefully when tools are not supported.
- Ollama uses model names like `llama3:8b` with colons, which conflicts with
  `LLMFactory.parse_llm_string()` that splits on `:`. Need to handle
  `"ollama:llama3:8b"` → provider=`ollama`, model=`llama3:8b` (split on first `:` only).
  **Already handled**: `parse_llm_string` uses `split(':', 1)`.
- Timeout should be higher for local servers (default 120s vs 60s for cloud).
- Some local servers don't support `max_tokens` — should handle gracefully.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `openai` | `>=1.0` | AsyncOpenAI client with custom base_url |

No new dependencies required — reuses existing `openai` SDK.

---

## 7. Open Questions

- [ ] Should we add a `model_supports_tools` flag to let users declare tool support
      for their specific local model? — *Owner: engineer*
- [ ] Should `list_models()` cache results to avoid repeated API calls? — *Owner: engineer*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-18 | Claude | Initial draft |
