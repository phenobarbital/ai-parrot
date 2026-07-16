---
type: feature
base_branch: dev
---

# Feature Specification: Moonshot Client (MoonshotClient)

**Feature ID**: FEAT-311
**Date**: 2026-07-17
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot currently accesses Kimi/Moonshot models only through third-party
gateways (Nvidia NIM, Groq), which limits the system to:

- **Older models only** — kimi-k3 (1M context, 2.8T params flagship) and
  kimi-k2.7-code (code-focused) are not available via Nvidia/Groq.
- **No Moonshot-native features** — `prompt_cache_key` (session-based cache
  optimization), `partial` mode (assistant prefill), dynamic tool loading
  (K3-only), and video understanding are all unavailable through gateways.
- **Gateway latency** — an extra network hop adds latency vs direct API access.

Moonshot's API is fully OpenAI-compatible at `https://api.moonshot.ai/v1`,
making a direct client straightforward to implement following the established
NvidiaClient pattern.

### Goals

- G1: Provide a native `MoonshotClient` extending `OpenAIClient` for direct
  access to Moonshot's OpenAI-compatible API at `https://api.moonshot.ai/v1`.
- G2: Support all 7 models: kimi-k3, kimi-k2.7-code, kimi-k2.7-code-highspeed,
  kimi-k2.6, moonshot-v1-128k, moonshot-v1-8k-vision-preview,
  moonshot-v1-128k-vision-preview.
- G3: Handle K-series parameter constraints — strip `temperature`, `top_p`, `n`,
  `presence_penalty`, `frequency_penalty` for models that reject them.
- G4: Support tri-mode thinking: `reasoning_effort` (K3), `thinking` dict
  (K2.6/K2.5), always-on (K2.7-code).
- G5: Preserve `reasoning_content` in responses and multi-turn message history.
- G6: Support Moonshot-specific features: `prompt_cache_key`,
  `max_completion_tokens` preference over `max_tokens`.
- G7: Register in `LLMFactory` as `"moonshot"` and `"kimi"`.
- G8: Support streaming, tool calling, structured output, and vision (all
  inherited from OpenAIClient with minor adjustments).

### Non-Goals (explicitly out of scope)

- Video understanding via `video_url` content type (P2 — deferred to follow-up).
- Dynamic tool loading via system messages with `tools` field (P2 — K3-only,
  deferred to follow-up).
- Partial mode / assistant prefill (P2 — deferred to follow-up).
- `safety_identifier` parameter (P3 — deferred).
- Moonshot File API (`/v1/files`) integration.
- Moonshot Batch API (`/v1/batches`) integration.

---

## 2. Architectural Design

### Overview

`MoonshotClient` extends `OpenAIClient` (not `AbstractClient` directly),
inheriting all OpenAI-compatible machinery: `ask()`, `ask_stream()`, `invoke()`,
tool calling, structured output, streaming, and vision.

The client overrides only what Moonshot requires:
1. `__init__()` — sets `base_url` and resolves `MOONSHOT_API_KEY`
2. `_chat_completion()` — strips fixed parameters for K-series models, injects
   thinking mode into `extra_body`, translates `max_tokens` →
   `max_completion_tokens`
3. `ask()` / `ask_stream()` — accept `thinking` and `reasoning_effort` kwargs,
   propagate via `contextvars.ContextVar` (NvidiaClient pattern)

Context caching is automatic and transparent — no `_apply_cache_hints()`
override needed.

### Component Diagram

```
LLMFactory.create("moonshot:kimi-k3")
    │
    ▼
MoonshotClient(OpenAIClient)
    │
    ├── __init__() → base_url="https://api.moonshot.ai/v1"
    │                 api_key=MOONSHOT_API_KEY
    │
    ├── _chat_completion() → _sanitize_params(model, kwargs)
    │                       → inject thinking extra_body
    │                       → max_tokens → max_completion_tokens
    │                       → inject prompt_cache_key
    │                       → client.chat.completions.create()
    │
    ├── ask() → set _thinking_ctx → super().ask()
    │
    └── ask_stream() → set _thinking_ctx → super().ask_stream()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OpenAIClient` | extends | Inherits all OpenAI machinery |
| `LLMFactory` | registered | `"moonshot"` and `"kimi"` keys |
| `MoonshotModel` enum | uses | Model identifiers in `parrot/models/` |
| `AIMessage` | returns | Standard response model with `metadata["reasoning_content"]` |
| `navconfig.config` | reads | `MOONSHOT_API_KEY` env var resolution |

### Data Models

```python
# parrot/models/moonshot.py
class MoonshotModel(str, Enum):
    """Moonshot model identifiers."""
    KIMI_K3 = "kimi-k3"
    KIMI_K2_7_CODE = "kimi-k2.7-code"
    KIMI_K2_7_CODE_HIGHSPEED = "kimi-k2.7-code-highspeed"
    KIMI_K2_6 = "kimi-k2.6"
    MOONSHOT_V1_128K = "moonshot-v1-128k"
    MOONSHOT_V1_8K_VISION = "moonshot-v1-8k-vision-preview"
    MOONSHOT_V1_128K_VISION = "moonshot-v1-128k-vision-preview"

# Models with fixed sampling parameters (temperature, top_p, etc.)
K_SERIES_MODELS: frozenset[str]

# Models where thinking is always on (no parameter needed)
ALWAYS_THINKING_MODELS: frozenset[str]

# Models that support reasoning_effort parameter
REASONING_EFFORT_MODELS: frozenset[str]

# Models that support thinking dict parameter
THINKING_DICT_MODELS: frozenset[str]
```

### New Public Interfaces

```python
class MoonshotClient(OpenAIClient):
    client_type: str = "moonshot"
    client_name: str = "moonshot"
    _default_model: str = MoonshotModel.KIMI_K2_6.value
    _fallback_model: str = MoonshotModel.MOONSHOT_V1_128K.value
    _min_cache_tokens: int = 0  # automatic caching, no explicit threshold

    def __init__(
        self,
        api_key: Optional[str] = None,
        prompt_cache_key: Optional[str] = None,
        **kwargs,
    ) -> None: ...

    async def _chat_completion(
        self,
        model: str,
        messages: Any,
        use_tools: bool = False,
        **kwargs,
    ) -> Any: ...

    async def ask(
        self,
        prompt: str,
        *,
        thinking: Optional[Union[bool, Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> AIMessage: ...

    async def ask_stream(
        self,
        prompt: str,
        *,
        thinking: Optional[Union[bool, Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[Union[str, AIMessage]]: ...
```

---

## 3. Module Breakdown

### Module 1: MoonshotModel Enum
- **Path**: `packages/ai-parrot/src/parrot/models/moonshot.py`
- **Responsibility**: Define model identifiers, model capability frozensets
  (K_SERIES_MODELS, ALWAYS_THINKING_MODELS, REASONING_EFFORT_MODELS,
  THINKING_DICT_MODELS), and any Moonshot-specific constants.
- **Depends on**: None

### Module 2: MoonshotClient
- **Path**: `packages/ai-parrot/src/parrot/clients/moonshot.py`
- **Responsibility**: Full client implementation extending OpenAIClient with
  parameter stripping, thinking mode, reasoning_content handling,
  prompt_cache_key, and max_completion_tokens translation.
- **Depends on**: Module 1 (MoonshotModel)

### Module 3: Factory Registration
- **Path**: `packages/ai-parrot/src/parrot/clients/factory.py`
- **Responsibility**: Add `"moonshot"` and `"kimi"` entries to
  `SUPPORTED_CLIENTS`, import `MoonshotClient`.
- **Depends on**: Module 2 (MoonshotClient)

### Module 4: Unit Tests
- **Path**: `tests/clients/test_moonshot_client.py`
- **Responsibility**: Test parameter stripping, thinking mode injection, factory
  creation, model defaults, capacity error detection.
- **Depends on**: Modules 1-3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_client_type_and_name` | M2 | Validates `client_type="moonshot"`, `client_name="moonshot"` |
| `test_default_model` | M2 | Default model is `kimi-k2.6` |
| `test_fallback_model` | M2 | Fallback model is `moonshot-v1-128k` |
| `test_sanitize_strips_temperature_for_k_series` | M2 | K3/K2.7/K2.6 requests have temperature stripped |
| `test_sanitize_strips_top_p_for_k_series` | M2 | K3/K2.7/K2.6 requests have top_p stripped |
| `test_sanitize_strips_penalties_for_k_series` | M2 | K3/K2.7/K2.6 requests have penalties stripped |
| `test_sanitize_preserves_params_for_legacy_models` | M2 | moonshot-v1-* models keep temperature/top_p |
| `test_max_tokens_translated_to_max_completion_tokens` | M2 | `max_tokens` kwarg becomes `max_completion_tokens` |
| `test_thinking_k3_reasoning_effort` | M2 | K3 injects `reasoning_effort` in extra_body |
| `test_thinking_k26_thinking_dict` | M2 | K2.6 injects `thinking` dict in extra_body |
| `test_thinking_k27_always_on` | M2 | K2.7-code does not inject thinking params (always on) |
| `test_prompt_cache_key_injected` | M2 | `prompt_cache_key` appears in request body |
| `test_factory_create_moonshot` | M3 | `LLMFactory.create("moonshot:kimi-k3")` returns MoonshotClient |
| `test_factory_create_kimi` | M3 | `LLMFactory.create("kimi:kimi-k2.6")` returns MoonshotClient |
| `test_model_enum_values` | M1 | All enum values match expected model strings |

### Test Data / Fixtures

```python
def _make_moonshot_client(**attrs):
    """Create a minimal MoonshotClient instance without __init__."""
    client = MoonshotClient.__new__(MoonshotClient)
    for key, value in attrs.items():
        setattr(client, key, value)
    return client
```

---

## 5. Acceptance Criteria

- [x] All unit tests pass (`pytest tests/clients/test_moonshot_client.py -v`)
- [ ] `LLMFactory.create("moonshot:kimi-k3")` returns a `MoonshotClient` instance
- [ ] `LLMFactory.create("kimi:kimi-k2.6")` returns a `MoonshotClient` instance
- [ ] K-series models (kimi-k3, kimi-k2.7-*, kimi-k2.6) have `temperature`,
      `top_p`, `n`, `presence_penalty`, `frequency_penalty` stripped from requests
- [ ] Legacy models (moonshot-v1-*) preserve sampling parameters normally
- [ ] Thinking mode works for K3 (`reasoning_effort`), K2.6 (`thinking` dict),
      and K2.7-code (always-on, no parameter)
- [ ] `reasoning_content` is captured in `AIMessage.metadata["reasoning_content"]`
- [ ] `max_tokens` is translated to `max_completion_tokens` in requests
- [ ] `prompt_cache_key` is injected into request body when provided
- [ ] No breaking changes to existing public API
- [ ] MoonshotModel enum contains all 7 models

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
from parrot.clients.gpt import OpenAIClient          # verified: packages/ai-parrot/src/parrot/clients/gpt.py:79
from parrot.models import AIMessage                    # verified: packages/ai-parrot/src/parrot/models/__init__.py:9
from parrot.models.moonshot import MoonshotModel       # NEW — will be created by Module 1
from navconfig import config                           # verified: used by all clients (gpt.py:17, nvidia.py:15)
import contextvars                                     # stdlib — used by nvidia.py:12
from tenacity import (AsyncRetrying, retry_if_exception_type,  # verified: nvidia.py:16-20
    stop_after_attempt, wait_exponential)
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(AbstractClient):                            # line 79
    client_type: str = "openai"                                # line 82
    client_name: str = "openai"                                # line 84
    _default_model: str = "gpt-5-mini"                         # line 85
    _fallback_model: str = "gpt-5-nano"                        # line 86
    _min_cache_tokens: int = 1024                              # line 89

    def __init__(self, api_key: str = None,
                 base_url: str = "https://api.openai.com/v1",
                 **kwargs):                                    # line 91

    async def get_client(self) -> "AsyncOpenAI":               # line 203
        # Creates AsyncOpenAI(api_key, base_url, timeout)

    async def _chat_completion(self, model: str, messages: Any,
                               use_tools: bool = False,
                               **kwargs):                      # line 300
        # Retry policy, routes to parse() or create()

    async def ask(self, prompt: str,
                  model=OpenAIModel.GPT4_1,
                  max_tokens=None, temperature=None,
                  ...) -> AIMessage:                            # line 666

    async def ask_stream(self, prompt: str,
                         model=OpenAIModel.GPT5_MINI,
                         ...) -> AsyncIterator[Union[str, AIMessage]]:  # line 1190


# packages/ai-parrot/src/parrot/clients/nvidia.py (PATTERN ANALOG)
class NvidiaClient(OpenAIClient):                              # line 36
    client_type: str = "nvidia"                                # line 70
    client_name: str = "nvidia"                                # line 71
    _default_model: str = NvidiaModel.KIMI_K2_INSTRUCT_0905.value  # line 72

    def __init__(self, api_key: Optional[str] = None, **kwargs):  # line 74
        resolved_key = api_key or config.get("NVIDIA_API_KEY")
        super().__init__(api_key=resolved_key,
                         base_url="https://integrate.api.nvidia.com/v1",
                         **kwargs)
        self.api_key = resolved_key  # re-set after super().__init__

    async def _chat_completion(self, model, messages,
                               use_tools=False, **kwargs):     # line 124
        # Reads _thinking_ctx, merges into extra_body
        # Always uses client.chat.completions.create (never parse())

    async def ask(self, prompt, *,
                  enable_thinking=False,
                  clear_thinking=False, **kwargs):              # line 175
        # Sets _thinking_ctx, delegates to super().ask()

    async def ask_stream(self, prompt, *,
                         enable_thinking=False,
                         clear_thinking=False, **kwargs):       # line 214


# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                     # line 72
    input: str                                                  # line 76
    output: Any                                                 # line 79
    response: Optional[str]                                     # line 82
    model: str                                                  # line 111
    provider: str                                               # line 114
    usage: CompletionUsage                                      # line 118
    metadata: Dict[str, Any]                                    # line 202
    # reasoning_content stored in metadata["reasoning_content"]
    # (see ZaiClient zai.py:256-260 for the pattern)


# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS: Dict[str, type]                              # line 64
# Add "moonshot": MoonshotClient, "kimi": MoonshotClient


# packages/ai-parrot/src/parrot/models/nvidia.py (enum pattern)
class NvidiaModel(str, Enum):                                   # line 11
    KIMI_K2_THINKING = "moonshotai/kimi-k2-thinking"            # line 23
    KIMI_K2_INSTRUCT_0905 = "moonshotai/kimi-k2-instruct-0905" # line 24
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `MoonshotClient.__init__()` | `OpenAIClient.__init__()` | `super().__init__(api_key, base_url)` | `gpt.py:91` |
| `MoonshotClient._chat_completion()` | `self.client.chat.completions.create()` | OpenAI SDK | `gpt.py:310` |
| `MoonshotClient.ask()` | `OpenAIClient.ask()` | `super().ask()` | `gpt.py:666` |
| `MoonshotClient.ask_stream()` | `OpenAIClient.ask_stream()` | `super().ask_stream()` | `gpt.py:1190` |
| `reasoning_content` | `AIMessage.metadata` | `metadata["reasoning_content"]` | `responses.py:202`, `zai.py:260` |
| Factory registration | `SUPPORTED_CLIENTS` dict | direct entry | `factory.py:64` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.clients.moonshot`~~ — does not exist yet (Module 2 creates it)
- ~~`parrot.models.moonshot`~~ — does not exist yet (Module 1 creates it)
- ~~`OpenAIClient._sanitize_params()`~~ — no such method on the parent; MoonshotClient creates its own `_sanitize_params_for_model()`
- ~~`OpenAIClient.enable_thinking`~~ — not a kwarg on OpenAIClient; only NvidiaClient has this
- ~~`AIMessage.reasoning_content`~~ — not a top-level field; stored in `metadata` dict
- ~~`AbstractClient.max_completion_tokens`~~ — no such attribute; this is a Moonshot API parameter
- ~~`MoonshotClient` in SUPPORTED_CLIENTS~~ — not registered yet (Module 3 adds it)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **NvidiaClient pattern** (`nvidia.py`): extend OpenAIClient, override
  `_chat_completion()`, use `contextvars.ContextVar` for thinking mode
  propagation. This is the canonical pattern for OpenAI-compatible providers.
- **API key resolution** (`nvidia.py:75`): `api_key or config.get("MOONSHOT_API_KEY")`
  with re-set after `super().__init__()`.
- **`reasoning_content` handling** (`zai.py:256-260`): use `getattr(message,
  "reasoning_content", None)` and store in `metadata["reasoning_content"]`.
- **Test pattern** (`test_openai_fallback.py:6-11`): use `__new__` to create
  minimal instances without API keys for unit testing.
- **Always use `client.chat.completions.create()`** (never `parse()`) because
  Moonshot, like Nvidia NIM, may not support the SDK's parse shortcut.

### Parameter Stripping Logic

```python
# K-series models have fixed sampling parameters.
# Passing them returns invalid_request_error.
_FIXED_PARAM_MODELS = frozenset({
    "kimi-k3",
    "kimi-k2.7-code", "kimi-k2.7-code-highspeed",
    "kimi-k2.6",
})

_PARAMS_TO_STRIP = {"temperature", "top_p", "n", "presence_penalty", "frequency_penalty"}

@staticmethod
def _sanitize_params_for_model(model: str, kwargs: dict) -> dict:
    if model in _FIXED_PARAM_MODELS:
        for param in _PARAMS_TO_STRIP:
            kwargs.pop(param, None)
    return kwargs
```

### Thinking Mode Logic

| Model | Parameter | Behavior |
|-------|-----------|----------|
| kimi-k3 | `reasoning_effort` (top-level or extra_body) | Always reasons; `reasoning_effort="max"` |
| kimi-k2.7-code | None needed | Always-on thinking; response includes `reasoning_content` |
| kimi-k2.7-code-highspeed | None needed | Same as k2.7-code |
| kimi-k2.6 | `extra_body={"thinking": {"type": "enabled"}}` | Default on; can disable with `"type": "disabled"` |
| moonshot-v1-* | N/A | No thinking support |

### `max_tokens` → `max_completion_tokens` Translation

Moonshot deprecates `max_tokens` in favor of `max_completion_tokens`. The
`_chat_completion()` override should check for `max_tokens` in kwargs and
rename it to `max_completion_tokens`.

### Known Risks / Gotchas

- **Streaming usage location**: Moonshot reports usage in `choices[0].usage`
  in the last chunk, not top-level `chunk.usage`. The OpenAI SDK may not parse
  this automatically. Monitor in integration testing; may need a streaming
  override if usage is lost.
- **No image URLs**: Moonshot only accepts base64-encoded images and `ms://`
  file references for vision — no HTTP URLs. The inherited
  `_encode_image_for_openai()` already uses base64, so this should work
  without changes, but URL-based image inputs would silently fail.
- **K2.5 sunset**: `kimi-k2.5` is being sunset Aug 31 2026 — not included in
  the model enum. If needed, users can pass the string directly.
- **`tool_choice: "required"`**: Only works on kimi-k3. K2.6 and K2.7 return
  errors. No special handling needed since tool_choice is user-specified.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `openai` | `>=1.0` | OpenAI SDK (already a dependency via OpenAIClient) |
| `navconfig` | existing | Config/env var resolution |
| `tenacity` | existing | Retry policy |

No new external dependencies required.

---

## 8. Open Questions

- [x] Architecture: extend OpenAIClient vs AbstractClient? — *Resolved in
  proposal*: Extend OpenAIClient. Moonshot is fully OpenAI-compatible; only
  ~5 behaviors need overrides.
- [x] Default model? — *Resolved*: `kimi-k2.6` (general-purpose, latest
  non-flagship, good balance of capability and cost).
- [x] Context caching implementation? — *Resolved in proposal*: Automatic
  and transparent. No `_apply_cache_hints()` override needed. Set
  `_min_cache_tokens = 0` (sentinel for auto-caching).

---

## Worktree Strategy

- **Isolation unit**: per-spec (all 4 tasks run sequentially in one worktree)
- **Rationale**: Modules 1-4 have linear dependencies; no parallelism benefit.
- **Cross-feature dependencies**: None — this is a standalone new client.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-07-17 | Jesus Lara | Initial draft from FEAT-311 proposal |
