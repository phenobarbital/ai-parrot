# Feature Specification: Nvidia Client

**Feature ID**: FEAT-122
**Date**: 2026-04-23
**Author**: Jesus
**Status**: approved
**Target version**: 0.9.x

---

## 1. Motivation & Business Requirements

> Access Nvidia's NIM model catalog (Moonshot Kimi, Minimax, DeepSeek, Qwen,
> Mistral Mamba, Z-AI GLM, etc.) through a single OpenAI-compatible gateway
> at `https://integrate.api.nvidia.com/v1`.

### Problem Statement
Nvidia's NIM API hosts a curated set of frontier OSS models (reasoning,
coding, long-context) behind an OpenAI-compatible endpoint. AI-Parrot does
not currently expose this provider. Without it, users must either spin up
`vLLMClient` against a self-hosted deployment or use `OpenRouter` (different
catalog, different cost model). A dedicated `NvidiaClient` gives direct,
low-latency access to Nvidia-hosted models and avoids provider-routing
overhead, while reusing the fully-featured `OpenAIClient` async machinery
(tool calling, streaming, structured output, retry, per-loop cache).

### Goals
- Provide an `NvidiaClient` that extends `OpenAIClient` with `base_url`
  pointing at `https://integrate.api.nvidia.com/v1`.
- Source API key from constructor argument, or fall back to
  `NVIDIA_API_KEY` via `navconfig.config`.
- Expose a `NvidiaModel` enum covering the user-tested model set
  (Moonshot Kimi K2, Minimax M2, DeepSeek V3, Qwen 3, Mistral Mamba
  Codestral, Z-AI GLM 5.1).
- Support Nvidia-specific reasoning payload for models that expose
  `reasoning_content` in the streaming delta (e.g. `z-ai/glm-5.1`) via
  an `extra_body` `chat_template_kwargs` shortcut.
- Register in `LLMFactory` under `"nvidia"` so users can write
  `"nvidia:moonshotai/kimi-k2-thinking"`.
- Reuse inherited streaming, tool calling, and structured output — zero
  new completion/stream code paths.

### Non-Goals (explicitly out of scope)
- Wrapping Nvidia's non-LLM NIM endpoints (image, speech, vision, RAG
  retriever microservices) — only the OpenAI-compatible chat completion
  endpoint is in scope.
- Per-request billing/cost tracking — Nvidia does not publish a cost
  endpoint analogous to OpenRouter's `/generation`.
- Embedding models (`nv-embed-*`) — future spec.
- Automatic fallback between Nvidia and other providers — orchestration
  is handled by `AgentCrew`, not the client.
- A dedicated Nvidia reasoning-response data model — `reasoning_content`
  is surfaced as-is in the streamed delta; callers that want it typed
  can post-process.

---

## 2. Architectural Design

### Overview
`NvidiaClient` extends `OpenAIClient`, overriding only `__init__` to set
`base_url="https://integrate.api.nvidia.com/v1"` and to resolve the API
key from `NVIDIA_API_KEY`. Because Nvidia's NIM endpoint is OpenAI-compatible,
every inherited method — `ask`, `ask_stream`, `invoke`, `_chat_completion`,
tool calling, structured output, retry — works unchanged.

The only Nvidia-specific affordance is a convenience for models that
support server-side reasoning (`z-ai/glm-5.1` and similar). The client
exposes an `enable_thinking: bool` keyword on `ask`/`ask_stream` that
injects the documented payload:

```python
extra_body={"chat_template_kwargs": {"enable_thinking": True,
                                     "clear_thinking": False}}
```

No new `_chat_completion` override is needed — the helper merges into
`kwargs["extra_body"]` before delegating to `super().ask(...)`.

### Component Diagram
```
User Code
    │
    ▼
NvidiaClient (extends OpenAIClient)
    │  ├── base_url = https://integrate.api.nvidia.com/v1
    │  ├── api_key  ← NVIDIA_API_KEY (navconfig)
    │  └── enable_thinking shortcut (merges into extra_body)
    │
    ▼
AsyncOpenAI SDK (inherited OpenAIClient.get_client())
    │
    ▼
Nvidia NIM API ──→ Moonshot | Minimax | DeepSeek | Qwen | Mistral | Z-AI
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OpenAIClient` (`parrot/clients/gpt.py:90`) | extends | Inherits completion, streaming, tool calling, invoke, retry |
| `LLMFactory` (`parrot/clients/factory.py:18`) | registers | Add `"nvidia"` to `SUPPORTED_CLIENTS` |
| `AbstractClient` (`parrot/clients/base.py:231`) | conforms | Per-loop client cache, tool manager, conversation memory all inherited unchanged |
| `navconfig.config` | consumes | `NVIDIA_API_KEY` lookup |

### Data Models
```python
from enum import Enum


class NvidiaModel(str, Enum):
    """Nvidia NIM-hosted model identifiers.

    String-valued enum so members interchange with raw model strings
    in OpenAI SDK calls (model=NvidiaModel.KIMI_K2_THINKING.value).
    """
    # Moonshot AI
    KIMI_K2_THINKING = "moonshotai/kimi-k2-thinking"
    KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905"
    KIMI_K2_5 = "moonshotai/kimi-k2.5"

    # Minimax
    MINIMAX_M2_5 = "minimaxai/minimax-m2.5"
    MINIMAX_M2_7 = "minimaxai/minimax-m2.7"

    # Mistral
    MAMBA_CODESTRAL_7B = "mistralai/mamba-codestral-7b-v0.1"

    # DeepSeek
    DEEPSEEK_V3_1_TERMINUS = "deepseek-ai/deepseek-v3.1-terminus"

    # Qwen
    QWEN3_5_397B = "qwen/qwen3.5-397b-a17b"

    # Z-AI (reasoning-capable; emits reasoning_content in deltas)
    GLM_5_1 = "z-ai/glm-5.1"
```

### New Public Interfaces
```python
class NvidiaClient(OpenAIClient):
    """Client for Nvidia NIM's OpenAI-compatible API gateway."""

    client_type: str = "nvidia"
    client_name: str = "nvidia"
    _default_model: str = NvidiaModel.KIMI_K2_INSTRUCT_0905.value

    def __init__(
        self,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        """Initialize Nvidia client.

        Args:
            api_key: Nvidia NIM API key. Falls back to NVIDIA_API_KEY env var.
            **kwargs: Passed to OpenAIClient / AbstractClient.
        """
        ...

    async def ask(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ):
        """See OpenAIClient.ask. Adds enable_thinking shortcut that injects
        chat_template_kwargs into extra_body for reasoning-capable models.
        """
        ...

    async def ask_stream(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ):
        """See OpenAIClient.ask_stream. Same extra_body injection as ask()."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Nvidia Data Models
- **Path**: `parrot/models/nvidia.py`
- **Responsibility**: `NvidiaModel` enum listing tested/supported
  Nvidia NIM models. No Pydantic wrappers needed — Nvidia's response
  shape is the OpenAI Chat Completion shape and is already covered by
  existing `AIMessage` / `CompletionUsage` models.
- **Depends on**: None.

### Module 2: Nvidia Client
- **Path**: `parrot/clients/nvidia.py`
- **Responsibility**: `NvidiaClient` class extending `OpenAIClient`.
  Overrides `__init__` only. Adds the `enable_thinking` helper on
  `ask`/`ask_stream`. No override of `_chat_completion`, `get_client`,
  or any internal OpenAI machinery.
- **Depends on**: Module 1, `OpenAIClient`.

### Module 3: Factory Registration
- **Path**: `parrot/clients/factory.py` (modify)
- **Responsibility**: Import `NvidiaClient`; add `"nvidia"` entry to
  `SUPPORTED_CLIENTS`. Single-line change — `LLMFactory.parse_llm_string`
  already handles the `"provider:model"` form for arbitrary model slugs.
- **Depends on**: Module 2.

### Module 4: Unit Tests
- **Path**: `tests/test_nvidia_client.py` (mirrors
  `tests/test_openrouter_client.py` at `packages/ai-parrot/tests/`)
- **Responsibility**: Verify initialization, base URL override, API
  key fallback from `NVIDIA_API_KEY`, `enable_thinking` extra_body
  injection, factory registration. Mock `AsyncOpenAI` — no live calls.
- **Depends on**: Module 2, Module 3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_client_init_explicit_key` | Module 2 | Client stores api_key from constructor argument |
| `test_client_init_env_fallback` | Module 2 | Client falls back to NVIDIA_API_KEY via navconfig.config when api_key is None |
| `test_client_base_url` | Module 2 | `client.base_url == "https://integrate.api.nvidia.com/v1"` |
| `test_client_type_and_name` | Module 2 | `client_type == "nvidia"` and `client_name == "nvidia"` |
| `test_default_model` | Module 2 | `client._default_model == NvidiaModel.KIMI_K2_INSTRUCT_0905.value` |
| `test_enable_thinking_injects_extra_body` | Module 2 | `ask(..., enable_thinking=True)` adds `chat_template_kwargs={"enable_thinking": True, "clear_thinking": False}` inside `extra_body` when forwarding to parent |
| `test_enable_thinking_preserves_existing_extra_body` | Module 2 | Existing keys in `extra_body` survive the merge |
| `test_enable_thinking_default_off` | Module 2 | `ask(...)` without `enable_thinking` does NOT inject `chat_template_kwargs` |
| `test_nvidia_model_enum_values` | Module 1 | All 9 user-listed models enumerate to the documented strings |
| `test_factory_registration` | Module 3 | `LLMFactory.create("nvidia:moonshotai/kimi-k2-thinking")` returns an `NvidiaClient` with the correct `model` |
| `test_factory_default_model` | Module 3 | `LLMFactory.create("nvidia")` uses `_default_model` |

### Integration Tests
| Test | Description |
|---|---|
| `test_completion_e2e_kimi` | Live completion request to `moonshotai/kimi-k2-instruct-0905`. Gated behind `NVIDIA_API_KEY` env var — skip in CI when unset. |
| `test_streaming_e2e_glm_reasoning` | Live stream against `z-ai/glm-5.1` with `enable_thinking=True`; asserts at least one chunk carries `reasoning_content` on the delta. |

### Test Data / Fixtures
```python
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def client():
    from parrot.clients.nvidia import NvidiaClient
    return NvidiaClient(api_key="test-key-123")


@pytest.fixture
def env_key(monkeypatch):
    """Patches navconfig.config.get to return a test NVIDIA_API_KEY."""
    from parrot.clients import nvidia as nvidia_mod
    monkeypatch.setattr(
        nvidia_mod.config, "get",
        lambda key, default=None: "env-nvidia-key" if key == "NVIDIA_API_KEY" else default
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `NvidiaClient` extends `OpenAIClient` (from `parrot.clients.gpt`)
- [ ] `base_url` is `https://integrate.api.nvidia.com/v1`
- [ ] API key sourced in this order: constructor `api_key` → `config.get('NVIDIA_API_KEY')`
- [ ] `NvidiaModel` enum is in `parrot/models/nvidia.py` and contains all 9 user-listed models
- [ ] `client_type == "nvidia"`, `client_name == "nvidia"`, `_default_model == NvidiaModel.KIMI_K2_INSTRUCT_0905.value`
- [ ] `enable_thinking=True` on `ask` / `ask_stream` injects `extra_body["chat_template_kwargs"] = {"enable_thinking": True, "clear_thinking": <value>}` and preserves pre-existing `extra_body` keys
- [ ] `LLMFactory.SUPPORTED_CLIENTS["nvidia"]` points at `NvidiaClient`; `LLMFactory.create("nvidia:moonshotai/kimi-k2-thinking")` returns an `NvidiaClient` with `model="moonshotai/kimi-k2-thinking"`
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/test_nvidia_client.py -v`
- [ ] No modification to `OpenAIClient`, `AbstractClient`, or any other existing client
- [ ] No new runtime dependencies (uses already-installed `openai`, `navconfig`, `pydantic`)

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every entry below was verified by `read` on the source file at the given
> line. Implementation agents MUST NOT reference imports, attributes, or
> methods not listed here without first verifying they exist.

### Verified Imports
```python
# Third-party (already in pyproject)
from openai import AsyncOpenAI                                       # verified: openai>=1.0 in deps
from navconfig import config                                         # verified: packages/ai-parrot/src/parrot/clients/gpt.py:17

# Parent class — the client to extend
from parrot.clients.gpt import OpenAIClient                          # verified: packages/ai-parrot/src/parrot/clients/gpt.py:90

# Factory registration target
from parrot.clients.factory import SUPPORTED_CLIENTS                 # verified: packages/ai-parrot/src/parrot/clients/factory.py:18

# Nvidia enum lives here after implementation
# from parrot.models.nvidia import NvidiaModel                       # NEW in this spec
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(AbstractClient):                                   # line 90
    client_type: str = 'openai'                                       # line 93
    model: str = OpenAIModel.GPT4_TURBO.value                         # line 94
    client_name: str = 'openai'                                       # line 95
    _default_model: str = 'gpt-4o-mini'                               # line 96
    _fallback_model: str = 'gpt-4.1-nano'                             # line 97
    _lightweight_model: str = "gpt-4.1"                               # line 98

    def __init__(
        self,
        api_key: str = None,                                          # line 102
        base_url: str = "https://api.openai.com/v1",                  # line 103
        **kwargs,
    ):                                                                # line 100
        self.api_key = api_key or config.get('OPENAI_API_KEY')        # line 106
        self.base_url = base_url                                      # line 107
        self.base_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        super().__init__(**kwargs)                                    # line 112

    async def get_client(self) -> AsyncOpenAI:                        # line 126
        return AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=config.get('OPENAI_TIMEOUT', 60),
        )

    async def _chat_completion(                                        # line 224
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs,
    ): ...
```

```python
# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS = {                                                 # line 18
    "claude": AnthropicClient,
    "anthropic": AnthropicClient,
    "google": GoogleGenAIClient,
    "openai": OpenAIClient,
    "groq": GroqClient,
    "grok": GrokClient,
    "xai": GrokClient,
    "openrouter": OpenRouterClient,
    "local": LocalLLMClient,
    "localllm": LocalLLMClient,
    "ollama": LocalLLMClient,
    "vllm": vLLMClient,
    "llamacpp": LocalLLMClient,
    "gemma4": _lazy_gemma4,
}

class LLMFactory:                                                     # line 36
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]: ...  # line 46
    @staticmethod
    def create(
        llm: str,
        model_args: Optional[Dict[str, Any]] = None,
        tool_manager: Optional[Any] = None,
        **kwargs,
    ) -> AbstractClient: ...                                          # line 68
```

```python
# Reference pattern — this is the closest analog to NvidiaClient
# packages/ai-parrot/src/parrot/clients/openrouter.py
class OpenRouterClient(OpenAIClient):                                 # line 23
    client_type: str = "openrouter"                                   # line 49
    client_name: str = "openrouter"                                   # line 50
    _default_model: str = OpenRouterModel.DEEPSEEK_R1.value           # line 51

    def __init__(
        self,
        api_key: Optional[str] = None,
        app_name: Optional[str] = None,
        site_url: Optional[str] = None,
        provider_preferences: Optional[ProviderPreferences] = None,
        **kwargs,
    ):                                                                # line 53
        ...
        resolved_key = api_key or config.get('OPENROUTER_API_KEY')    # line 68
        super().__init__(
            api_key=resolved_key,
            base_url="https://openrouter.ai/api/v1",
            **kwargs,
        )                                                             # line 69-73
        self.api_key = resolved_key                                   # line 75
```

### User-Provided Reference Code (verified against Nvidia docs)
```python
# From the feature request — streaming example against z-ai/glm-5.1
# Shows reasoning_content on delta when chat_template_kwargs.enable_thinking=True
extra_body={
    "chat_template_kwargs": {
        "enable_thinking": True,
        "clear_thinking": False,
    }
}
# delta attributes to consume:
#   - delta.reasoning_content (str | None)   — reasoning tokens
#   - delta.content (str | None)             — final answer tokens
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `NvidiaClient.__init__` | `OpenAIClient.__init__` | `super().__init__(api_key=..., base_url="https://integrate.api.nvidia.com/v1", **kwargs)` | `packages/ai-parrot/src/parrot/clients/gpt.py:100` |
| `NvidiaClient.ask` | `OpenAIClient.ask` | `await super().ask(..., extra_body=merged)` | inherited method, see openrouter pattern at `packages/ai-parrot/src/parrot/clients/openrouter.py:106` |
| `NvidiaClient` → `LLMFactory` | `SUPPORTED_CLIENTS["nvidia"] = NvidiaClient` | dict key insertion | `packages/ai-parrot/src/parrot/clients/factory.py:18` |
| `NvidiaClient.api_key` | `navconfig.config` | `config.get('NVIDIA_API_KEY')` | `navconfig` already used at `packages/ai-parrot/src/parrot/clients/openrouter.py:68` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.clients.NvidiaClient`~~ — does not exist yet; being created by this spec.
- ~~`parrot.models.nvidia.NvidiaModel`~~ — does not exist yet; being created by this spec.
- ~~`OpenAIClient.enable_thinking`~~ — not a real attribute on the parent.
- ~~`AsyncOpenAI(..., reasoning=...)`~~ — not a constructor kwarg; reasoning is per-request via `extra_body`.
- ~~`NvidiaUsage` / `NvidiaGenerationStats`~~ — Nvidia does not expose a `/generation` stats endpoint equivalent to OpenRouter; do NOT invent one.
- ~~`parrot.clients.base.AbstractClient._chat_completion`~~ — exists only on subclasses; do not assume base-class presence.
- ~~`parrot/clients/nvidia/__init__.py` (subpackage)~~ — Nvidia client is a single-module file at `parrot/clients/nvidia.py`, matching the openrouter/grok/groq/vllm convention; do NOT create a subpackage.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Direct analog**: mirror `OpenRouterClient` (`parrot/clients/openrouter.py`).
  Same pattern — subclass `OpenAIClient`, override `__init__`, call
  `super().__init__(api_key=..., base_url=..., **kwargs)`, re-set
  `self.api_key` after super to survive any base-class overwrites.
- **Simpler than OpenRouter**: no custom headers, no provider preferences,
  no `get_client` override, no `_chat_completion` override, no generation-stats
  endpoint. Keep it minimal.
- **Environment key**: use `config.get('NVIDIA_API_KEY')` from `navconfig`,
  not `os.getenv`. Matches the project convention (see `openrouter.py:68`
  and `gpt.py:106`).
- **Async-first**: rely on the inherited `AsyncOpenAI` client created via
  `OpenAIClient.get_client()`; do not add sync code paths.
- **Logger**: use `self.logger` inherited from `AbstractClient`; no
  `print`, no new `getLogger(__name__)` at module level beyond what
  the parent pattern already does.

### Implementation Sketch (for the executor agent)
```python
# parrot/clients/nvidia.py
"""Nvidia NIM client for AI-Parrot.

Extends OpenAIClient to route requests through Nvidia's OpenAI-compatible
NIM gateway at https://integrate.api.nvidia.com/v1.
"""
from typing import Any, Dict, Optional
from logging import getLogger

from navconfig import config

from .gpt import OpenAIClient
from ..models.nvidia import NvidiaModel

logger = getLogger(__name__)


class NvidiaClient(OpenAIClient):
    """Client for Nvidia NIM's OpenAI-compatible API gateway.

    Args:
        api_key: Nvidia API key. Falls back to NVIDIA_API_KEY env var.
        **kwargs: Additional arguments passed to OpenAIClient.
    """

    client_type: str = "nvidia"
    client_name: str = "nvidia"
    _default_model: str = NvidiaModel.KIMI_K2_INSTRUCT_0905.value

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        resolved_key = api_key or config.get("NVIDIA_API_KEY")
        super().__init__(
            api_key=resolved_key,
            base_url="https://integrate.api.nvidia.com/v1",
            **kwargs,
        )
        # Re-set after super().__init__ because AbstractClient may overwrite
        self.api_key = resolved_key

    @staticmethod
    def _merge_thinking_extra_body(
        extra_body: Optional[Dict[str, Any]],
        enable_thinking: bool,
        clear_thinking: bool,
    ) -> Optional[Dict[str, Any]]:
        if not enable_thinking:
            return extra_body
        merged: Dict[str, Any] = dict(extra_body or {})
        kwargs_block = dict(merged.get("chat_template_kwargs") or {})
        kwargs_block["enable_thinking"] = True
        kwargs_block["clear_thinking"] = clear_thinking
        merged["chat_template_kwargs"] = kwargs_block
        return merged

    async def ask(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ):
        kwargs["extra_body"] = self._merge_thinking_extra_body(
            kwargs.get("extra_body"), enable_thinking, clear_thinking
        )
        return await super().ask(prompt, **kwargs)

    async def ask_stream(
        self,
        prompt: str,
        *,
        enable_thinking: bool = False,
        clear_thinking: bool = False,
        **kwargs,
    ):
        kwargs["extra_body"] = self._merge_thinking_extra_body(
            kwargs.get("extra_body"), enable_thinking, clear_thinking
        )
        async for chunk in super().ask_stream(prompt, **kwargs):
            yield chunk
```

### Known Risks / Gotchas
- **Super-init overwrites `self.api_key`**: `AbstractClient.__init__` reads
  `api_key` from `kwargs`; `OpenAIClient.__init__` then sets it. To guarantee
  the resolved NVIDIA key survives, re-set `self.api_key` after `super().__init__`
  (same guard the OpenRouter client uses at `openrouter.py:75`).
- **Responses-only models**: `OpenAIClient` has `RESPONSES_ONLY_MODELS`
  for `o3/o4-mini` that routes through the Responses API. Nvidia model slugs
  (e.g. `moonshotai/kimi-k2-thinking`) are not in that set and will correctly
  take the Chat Completions path — no additional handling needed.
- **Tool calling**: Not every Nvidia-hosted model supports tool calling
  (e.g. `mistralai/mamba-codestral-7b-v0.1`). Caller must enable tools
  selectively; no client-side filtering is attempted.
- **Rate limits**: Nvidia rate-limits are per-API-key. Inherited retry
  (tenacity `retry_if_exception_type((APIConnectionError, RateLimitError, APIError))`
  at `gpt.py:232`) covers 429/5xx already.
- **Structured output**: `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` in `gpt.py:69`
  is keyed on OpenAI model strings — not Nvidia slugs. The `response_format`
  path will still be attempted by the parent; failure is the caller's
  responsibility. Do NOT expand the compatible-models set in this spec.
- **`reasoning_content` on non-reasoning models**: silently ignored by the
  server; no client-side validation of `enable_thinking` against model
  capability.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `openai` | `>=1.0` | Already a dependency — reused via `base_url` override |
| `navconfig` | current pin | Already a dependency — for `NVIDIA_API_KEY` resolution |

No new dependencies required.

---

## Worktree Strategy
- **Isolation unit**: `per-spec` (sequential).
- **Rationale**: Three tiny modules with strict ordering:
  Module 1 (enum) → Module 2 (client) → Module 3 (factory edit) →
  Module 4 (tests). No cross-task parallelism payoff — one worktree,
  one branch, tasks run sequentially via `/sdd-start`.
- **Branch suggestion**: `feat-122-nvidia-client`.
- **Cross-feature dependencies**: none.

---

## 8. Open Questions

- [ ] Should we expose a `stop_thinking_after_tokens` / truncation helper for
      GLM-5.1-style reasoning traces, or leave trace length entirely to the
      caller's `max_tokens`? — *Owner: Jesus*: add when GLM-5.1 is used
- [ ] Do we want a `list_models()` method analogous to `OpenRouterClient.list_models()`?
      Nvidia exposes `GET /v1/models` — trivial to add, but not in the user's
      minimal task list. — *Owner: Jesus*: Add it
- [ ] Add `nvidia-embed-*` embedding models in a follow-up spec, or extend this
      one? Current spec explicitly excludes embeddings (§1 Non-Goals). — *Owner: Jesus*: not in the scope, embed models are managed by another part of parrot (parrot.embeddings)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-23 | Jesus | Initial draft |
