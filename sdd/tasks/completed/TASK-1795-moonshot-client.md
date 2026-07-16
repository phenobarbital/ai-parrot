# TASK-1795: MoonshotClient Implementation

**Feature**: FEAT-311 — Moonshot Client (MoonshotClient)
**Spec**: `sdd/specs/moonshot-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1794
**Assigned-to**: unassigned

---

## Context

This is the core task — implement `MoonshotClient` extending `OpenAIClient`
following the NvidiaClient pattern. Handles all Moonshot-specific behaviors:
parameter stripping, thinking mode, reasoning_content, prompt_cache_key,
and max_completion_tokens translation.

Implements spec §2 (Architectural Design) and §3 Module 2.

---

## Scope

- Create `MoonshotClient` class extending `OpenAIClient`
- Implement `__init__()` with `base_url`, `MOONSHOT_API_KEY`, `prompt_cache_key`
- Implement `_chat_completion()` override with:
  - Parameter stripping for K-series models via `_sanitize_params_for_model()`
  - Thinking mode injection into `extra_body` (read from contextvars)
  - `max_tokens` → `max_completion_tokens` translation
  - `prompt_cache_key` injection
  - Always use `client.chat.completions.create()` (never `parse()`)
  - Retry policy (same as NvidiaClient)
- Implement `ask()` override accepting `thinking` and `reasoning_effort` kwargs
- Implement `ask_stream()` override accepting `thinking` and `reasoning_effort` kwargs
- Use `contextvars.ContextVar` to propagate thinking flags (NvidiaClient pattern)

**NOT in scope**: Factory registration (TASK-1796), tests (TASK-1797), model enum (TASK-1794)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/moonshot.py` | CREATE | Full MoonshotClient implementation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import contextvars                                             # stdlib
from typing import Any, AsyncIterator, Dict, Optional, Union   # stdlib
from navconfig import config                                    # verified: nvidia.py:15
from tenacity import (                                          # verified: nvidia.py:16-20
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from ..models import AIMessage                                  # verified: models/__init__.py:9
from .gpt import OpenAIClient                                   # verified: nvidia.py:24
from ..models.moonshot import (                                 # TASK-1794 creates this
    MoonshotModel,
    K_SERIES_MODELS,
    ALWAYS_THINKING_MODELS,
    REASONING_EFFORT_MODELS,
    THINKING_DICT_MODELS,
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(AbstractClient):                            # line 79
    client_type: str = "openai"                                # line 82
    client_name: str = "openai"                                # line 84
    _default_model: str = "gpt-5-mini"                         # line 85
    _fallback_model: str = "gpt-5-nano"                        # line 86
    _min_cache_tokens: int = 1024                              # line 89

    def __init__(self, api_key=None,
                 base_url="https://api.openai.com/v1",
                 **kwargs):                                    # line 91
        self.api_key = api_key or config.get("OPENAI_API_KEY") # line 92
        self.base_url = base_url                               # line 93
        super().__init__(**kwargs)                              # line 97

    async def get_client(self) -> "AsyncOpenAI":               # line 203
        # Creates AsyncOpenAI(api_key, base_url, timeout)
        # Inherited as-is — no override needed

    async def _chat_completion(self, model: str, messages: Any,
                               use_tools: bool = False,
                               **kwargs):                      # line 300
        # Retry policy, routes to parse() or create()
        # MoonshotClient MUST override this

    async def ask(self, prompt: str, model=...,
                  max_tokens=None, temperature=None,
                  ...) -> AIMessage:                            # line 666

    async def ask_stream(self, prompt: str, model=...,
                         ...) -> AsyncIterator[Union[str, AIMessage]]:  # line 1190


# packages/ai-parrot/src/parrot/clients/nvidia.py (PATTERN TO FOLLOW)
_thinking_ctx: contextvars.ContextVar[Dict[str, Any]]          # line 31

class NvidiaClient(OpenAIClient):                              # line 36
    def __init__(self, api_key=None, **kwargs):                # line 74
        resolved_key = api_key or config.get("NVIDIA_API_KEY")
        super().__init__(api_key=resolved_key,
                         base_url="https://integrate.api.nvidia.com/v1",
                         **kwargs)
        self.api_key = resolved_key  # re-set after super().__init__

    async def _chat_completion(self, model, messages,
                               use_tools=False, **kwargs):     # line 124
        thinking = _thinking_ctx.get()
        if thinking.get("enable_thinking"):
            kwargs["extra_body"] = self._merge_thinking_extra_body(...)
        # ... retry policy ...
        return await self.client.chat.completions.create(
            model=model, messages=messages, **kwargs)

    async def ask(self, prompt, *,
                  enable_thinking=False, **kwargs):             # line 175
        token = _thinking_ctx.set({...})
        try:
            return await super().ask(prompt, **kwargs)
        finally:
            _thinking_ctx.reset(token)

    async def ask_stream(self, prompt, *,
                         enable_thinking=False, **kwargs):      # line 214
        # Same pattern as ask() with async for


# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                                     # line 72
    metadata: Dict[str, Any]                                    # line 202
    # reasoning_content stored in metadata["reasoning_content"]
    # (see zai.py:256-260)
```

### Does NOT Exist

- ~~`OpenAIClient._sanitize_params()`~~ — no such method; MoonshotClient creates its own
- ~~`OpenAIClient.enable_thinking`~~ — not a kwarg on OpenAIClient
- ~~`OpenAIClient.reasoning_effort`~~ — not a kwarg on OpenAIClient
- ~~`AIMessage.reasoning_content`~~ — not a top-level field; stored in `metadata` dict
- ~~`AbstractClient.max_completion_tokens`~~ — not an attribute; API parameter only
- ~~`OpenAIClient.prompt_cache_key`~~ — not an attribute; MoonshotClient creates this

---

## Implementation Notes

### Pattern to Follow

Follow `nvidia.py` exactly:

```python
_thinking_ctx: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "_moonshot_thinking_ctx", default={}
)

class MoonshotClient(OpenAIClient):
    client_type: str = "moonshot"
    client_name: str = "moonshot"
    _default_model: str = MoonshotModel.KIMI_K2_6.value
    _fallback_model: str = MoonshotModel.MOONSHOT_V1_128K.value
    _min_cache_tokens: int = 0  # automatic caching

    def __init__(self, api_key=None, prompt_cache_key=None, **kwargs):
        resolved_key = api_key or config.get("MOONSHOT_API_KEY")
        super().__init__(
            api_key=resolved_key,
            base_url="https://api.moonshot.ai/v1",
            **kwargs,
        )
        self.api_key = resolved_key
        self.prompt_cache_key = prompt_cache_key
```

### Parameter Stripping

```python
_PARAMS_TO_STRIP = frozenset({"temperature", "top_p", "n",
                               "presence_penalty", "frequency_penalty"})

@staticmethod
def _sanitize_params_for_model(model: str, kwargs: dict) -> dict:
    if model in K_SERIES_MODELS:
        for param in _PARAMS_TO_STRIP:
            kwargs.pop(param, None)
    return kwargs
```

### Thinking Mode Injection

Three thinking modes, handled in `_chat_completion()`:

```python
thinking = _thinking_ctx.get()
model_str = model

if model_str in REASONING_EFFORT_MODELS:
    # K3: uses reasoning_effort
    effort = thinking.get("reasoning_effort", "max")
    extra = dict(kwargs.get("extra_body") or {})
    extra["reasoning_effort"] = effort
    kwargs["extra_body"] = extra
elif model_str in THINKING_DICT_MODELS:
    # K2.6: uses thinking dict
    thinking_val = thinking.get("thinking")
    if thinking_val is not None:
        extra = dict(kwargs.get("extra_body") or {})
        if isinstance(thinking_val, bool):
            extra["thinking"] = {"type": "enabled" if thinking_val else "disabled"}
        elif isinstance(thinking_val, dict):
            extra["thinking"] = thinking_val
        kwargs["extra_body"] = extra
# K2.7: always-on — no injection needed
```

### max_tokens Translation

```python
if "max_tokens" in kwargs:
    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
```

### Key Constraints

- Always use `client.chat.completions.create()` (never `parse()`)
- Re-set `self.api_key` after `super().__init__()` (AbstractClient may overwrite)
- Use `from openai import APIConnectionError, RateLimitError, APIError` inside method (lazy import)
- Retry policy: 3 attempts, exponential backoff (2-10s)

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/nvidia.py` — primary pattern analog
- `packages/ai-parrot/src/parrot/clients/openrouter.py` — custom headers pattern (lines 93-96)
- `packages/ai-parrot/src/parrot/clients/zai.py:256-260` — reasoning_content handling

---

## Acceptance Criteria

- [ ] `MoonshotClient` extends `OpenAIClient`
- [ ] `client_type == "moonshot"` and `client_name == "moonshot"`
- [ ] `__init__()` resolves API key from `MOONSHOT_API_KEY` env var
- [ ] `__init__()` sets `base_url = "https://api.moonshot.ai/v1"`
- [ ] K-series models have sampling params stripped in `_chat_completion()`
- [ ] Legacy models preserve sampling params
- [ ] Thinking mode works for K3 (`reasoning_effort`)
- [ ] Thinking mode works for K2.6 (`thinking` dict)
- [ ] K2.7-code thinking is always-on (no injection)
- [ ] `max_tokens` translated to `max_completion_tokens`
- [ ] `prompt_cache_key` injected when provided
- [ ] Uses `client.chat.completions.create()` (never `parse()`)
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/moonshot.py`

---

## Test Specification

```python
# Tests are in TASK-1797 — this section shows expected behavior for reference
from parrot.clients.moonshot import MoonshotClient

client = MoonshotClient.__new__(MoonshotClient)
assert client.client_type == "moonshot"
assert client.client_name == "moonshot"
assert client._default_model == "kimi-k2.6"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/moonshot-client-llm.spec.md` for full context
2. **Check dependencies** — verify TASK-1794 is completed
3. **Read `nvidia.py`** (254 lines) — this is your primary reference
4. **Verify the Codebase Contract** — confirm all imports and signatures
5. **Implement** following the scope and patterns above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1795-moonshot-client.md`
8. **Update index** → `"done"`

---

## Completion Note

Implemented `packages/ai-parrot/src/parrot/clients/moonshot.py` following
the `NvidiaClient` pattern exactly (contextvar-based thinking propagation,
`__init__` API-key resolution + re-set after `super().__init__()`,
always-`.create()` retry policy). All task-level acceptance criteria are
met and verified via `ruff check` (clean) and an inline script confirming
`client_type`/`client_name`/`_default_model`/`_fallback_model` and
`_sanitize_params_for_model()` stripping behavior for K-series vs legacy
models.

**Flagged concern (not in this task's scope, noted for follow-up)**: the
spec's top-level Acceptance Criteria (§5) requires `reasoning_content` to
be captured in `AIMessage.metadata["reasoning_content"]`. Verified via
codebase research that `OpenAIClient.ask()`'s call to
`AIMessageFactory.from_openai()` (`models/responses.py:433-479`) does NOT
extract `reasoning_content` from the SDK response — unlike `ZaiClient`,
which builds `AIMessage` itself. Since `MoonshotClient.ask()`/`ask_stream()`
delegate to `super().ask()`/`super().ask_stream()` unmodified (matching
this task's specified Scope, which did not include an `AIMessage`
post-processing override), `reasoning_content` is only reachable today via
`AIMessage.raw_response` (the serialized SDK response dict), not via
`metadata`. This is a pre-existing gap inherited from the NvidiaClient
pattern this task was instructed to follow — flagging per spec §5 AC
rather than silently expanding this task's scope to add an
`ask()`/`ask_stream()` metadata post-processing step that wasn't listed in
Files to Create/Modify or Scope.
