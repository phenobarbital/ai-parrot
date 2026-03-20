# Feature Specification: OpenRouter Client

**Feature ID**: FEAT-005
**Date**: 2026-02-18
**Author**: Jesus
**Status**: approved
**Target version**: 0.9.x

---

## 1. Motivation & Business Requirements

> Access 200+ LLM models (DeepSeek, Llama, Mistral, Qwen, etc.) through a single
> unified API endpoint via [OpenRouter](https://openrouter.ai/).

### Problem Statement
AI-Parrot currently supports a fixed set of providers (OpenAI, Anthropic, Google,
Groq, xAI). Adding each new provider requires a dedicated client implementation.
OpenRouter aggregates 200+ models behind an OpenAI-compatible API, giving instant
access to new models without per-provider code.

### Goals
- Provide an `OpenRouterClient` that extends `OpenAIClient` with OpenRouter-specific features
- Register in `LLMFactory` so users can write `"openrouter:deepseek/deepseek-r1"`
- Support OpenRouter's model routing, provider preferences, and fallback
- Expose cost/usage tracking via OpenRouter response headers
- Support provider filtering and transforms

### Non-Goals (explicitly out of scope)
- OAuth/user-level authentication (we use API keys only)
- OpenRouter's web UI or playground integration
- Automatic credit/billing management
- Replacing existing direct-provider clients (OpenRouter is additive)

---

## 2. Architectural Design

### Overview
`OpenRouterClient` extends `OpenAIClient`, overriding `base_url` to
`https://openrouter.ai/api/v1` and injecting OpenRouter-specific headers
(`HTTP-Referer`, `X-Title`). OpenRouter's API is OpenAI-compatible, so
completion, streaming, tool calling, and structured output work out of the box.

OpenRouter-specific features (routing, provider preferences, cost tracking)
are layered on top via extra request parameters and response header parsing.

### Component Diagram
```
User Code
    │
    ▼
OpenRouterClient (extends OpenAIClient)
    │  ├── base_url = https://openrouter.ai/api/v1
    │  ├── OpenRouter headers (HTTP-Referer, X-Title)
    │  ├── Provider preferences & routing config
    │  └── Cost/usage tracking from response headers
    │
    ▼
AsyncOpenAI SDK (with base_url override)
    │
    ▼
OpenRouter API ──→ Upstream Provider (OpenAI, Anthropic, etc.)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OpenAIClient` | extends | Inherit completion, streaming, tool calling |
| `LLMFactory` | registers | `"openrouter"` key in `SUPPORTED_CLIENTS` |
| `AbstractClient` | conforms | All base interface methods work unchanged |
| `ToolManager` | uses | Tool calling passes through OpenAI-compatible format |

### Data Models
```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class OpenRouterModel(str, Enum):
    """Common OpenRouter model identifiers."""
    DEEPSEEK_R1 = "deepseek/deepseek-r1"
    DEEPSEEK_V3 = "deepseek/deepseek-chat"
    LLAMA_3_3_70B = "meta-llama/llama-3.3-70b-instruct"
    MISTRAL_LARGE = "mistralai/mistral-large-latest"
    QWEN_2_5_72B = "qwen/qwen-2.5-72b-instruct"
    GEMMA_2_27B = "google/gemma-2-27b-it"


class ProviderPreferences(BaseModel):
    """OpenRouter provider routing preferences."""
    allow_fallbacks: bool = Field(
        default=True,
        description="Allow OpenRouter to fall back to alternative providers"
    )
    require_parameters: bool = Field(
        default=False,
        description="Only use providers that support all requested parameters"
    )
    data_collection: Optional[str] = Field(
        default=None,
        description="Data collection preference: 'deny' or 'allow'"
    )
    order: Optional[List[str]] = Field(
        default=None,
        description="Ordered list of preferred providers, e.g. ['DeepInfra', 'Together']"
    )
    ignore: Optional[List[str]] = Field(
        default=None,
        description="List of providers to exclude"
    )
    quantizations: Optional[List[str]] = Field(
        default=None,
        description="Allowed quantization levels, e.g. ['bf16', 'fp8']"
    )


class OpenRouterUsage(BaseModel):
    """Cost and usage information from OpenRouter response headers."""
    generation_id: Optional[str] = None
    model: Optional[str] = None
    total_cost: Optional[float] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    native_tokens_prompt: Optional[int] = None
    native_tokens_completion: Optional[int] = None
    provider_name: Optional[str] = None
```

### New Public Interfaces
```python
class OpenRouterClient(OpenAIClient):
    """Client for OpenRouter's multi-model API gateway."""

    client_type: str = "openrouter"
    client_name: str = "openrouter"
    _default_model: str = "deepseek/deepseek-r1"

    def __init__(
        self,
        api_key: str = None,
        app_name: str = None,
        site_url: str = None,
        provider_preferences: ProviderPreferences = None,
        **kwargs
    ):
        ...

    async def get_client(self) -> AsyncOpenAI:
        """Initialize AsyncOpenAI with OpenRouter base_url and headers."""
        ...

    async def get_generation_stats(
        self, generation_id: str
    ) -> OpenRouterUsage:
        """Fetch cost/usage stats for a specific generation."""
        ...

    async def list_models(self) -> List[Dict[str, Any]]:
        """List all available models from OpenRouter."""
        ...
```

---

## 3. Module Breakdown

### Module 1: OpenRouter Data Models
- **Path**: `parrot/models/openrouter.py`
- **Responsibility**: `OpenRouterModel` enum, `ProviderPreferences`, `OpenRouterUsage` Pydantic models
- **Depends on**: None

### Module 2: OpenRouter Client
- **Path**: `parrot/clients/openrouter.py`
- **Responsibility**: `OpenRouterClient` class extending `OpenAIClient`
- **Depends on**: Module 1, `OpenAIClient`

### Module 3: Factory Registration
- **Path**: `parrot/clients/factory.py` (modify)
- **Responsibility**: Add `"openrouter"` to `SUPPORTED_CLIENTS`
- **Depends on**: Module 2

### Module 4: Unit Tests
- **Path**: `tests/test_openrouter_client.py`
- **Responsibility**: Test initialization, header injection, provider preferences, model listing, cost tracking
- **Depends on**: Module 2

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_client_init_default` | Module 2 | Client initializes with env var API key and correct base_url |
| `test_client_init_custom` | Module 2 | Client accepts custom api_key, app_name, site_url |
| `test_openrouter_headers` | Module 2 | Verifies HTTP-Referer and X-Title headers are set |
| `test_provider_preferences_serialization` | Module 1 | ProviderPreferences serializes to correct dict format |
| `test_provider_preferences_in_request` | Module 2 | Provider preferences are included in completion extra_body |
| `test_usage_parsing` | Module 1 | OpenRouterUsage parses response header data correctly |
| `test_factory_registration` | Module 3 | `LLMFactory.create("openrouter:deepseek/deepseek-r1")` returns OpenRouterClient |
| `test_model_override` | Module 2 | Model string is passed through without modification |
| `test_streaming_passthrough` | Module 2 | Streaming works via inherited OpenAIClient.stream() |

### Integration Tests
| Test | Description |
|---|---|
| `test_completion_e2e` | Full completion request to OpenRouter (requires API key, skip in CI) |
| `test_list_models_e2e` | Fetch available models from OpenRouter API |

### Test Data / Fixtures
```python
@pytest.fixture
def openrouter_client():
    return OpenRouterClient(
        api_key="test-key-123",
        app_name="ai-parrot-test",
        site_url="https://example.com"
    )

@pytest.fixture
def provider_prefs():
    return ProviderPreferences(
        allow_fallbacks=True,
        order=["DeepInfra", "Together"],
        ignore=["Azure"],
        quantizations=["bf16"]
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `OpenRouterClient` extends `OpenAIClient` and overrides base_url to `https://openrouter.ai/api/v1`
- [ ] API key sourced from `OPENROUTER_API_KEY` env var or constructor parameter
- [ ] OpenRouter headers (`HTTP-Referer`, `X-Title`) injected via `default_headers`
- [ ] `ProviderPreferences` model supports all OpenRouter routing options
- [ ] Provider preferences passed as `extra_body` in completion requests
- [ ] `get_generation_stats()` fetches cost data from OpenRouter's generation endpoint
- [ ] `list_models()` returns available models from OpenRouter API
- [ ] Registered in `LLMFactory` as `"openrouter"` — `LLMFactory.create("openrouter:model")` works
- [ ] All unit tests pass: `pytest tests/test_openrouter_client.py -v`
- [ ] Completion, streaming, and tool calling work through inherited OpenAIClient methods
- [ ] No breaking changes to existing clients or factory

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Extend `OpenAIClient` (see `parrot/clients/gpt.py`) — override `__init__` and `get_client()`
- Use `navconfig.config` for environment variables (`OPENROUTER_API_KEY`)
- Follow the `GrokClient` pattern for a clean client that wraps an external SDK
- Pydantic models for all structured data (`ProviderPreferences`, `OpenRouterUsage`)
- Async-first: use `aiohttp` for any direct HTTP calls (e.g., generation stats endpoint)

### Key Implementation Details

**Header injection via AsyncOpenAI:**
```python
AsyncOpenAI(
    api_key=self.api_key,
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": self.site_url,
        "X-Title": self.app_name,
    }
)
```

**Provider preferences via extra_body:**
```python
# In completion calls, OpenRouter accepts extra_body for routing
response = await client.chat.completions.create(
    model=model,
    messages=messages,
    extra_body={
        "provider": provider_preferences.model_dump(exclude_none=True)
    }
)
```

**Cost tracking via generation endpoint:**
```
GET https://openrouter.ai/api/v1/generation?id={generation_id}
```

### Known Risks / Gotchas
- OpenRouter may add latency compared to direct provider access — document this tradeoff
- Some models on OpenRouter don't support tool calling — client should handle gracefully
- Rate limits are per-account, not per-model — respect `429` responses
- The `extra_body` parameter in OpenAI SDK must be used carefully; test with real API

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `openai` | `>=1.0` | Already a dependency — reused via base_url override |
| `aiohttp` | `>=3.0` | Already a dependency — for generation stats HTTP call |

No new dependencies required.

---

## 7. Open Questions

- [ ] Should we cache the model list from `list_models()` with a TTL? — *Owner: Jesus*
- [ ] Do we need a `transforms` parameter for OpenRouter's middle-out transforms? — *Owner: Jesus*
- [ ] Should `OpenRouterUsage` be integrated into the existing `CompletionUsage` model or remain separate? — *Owner: Jesus*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-18 | Jesus | Initial draft |
