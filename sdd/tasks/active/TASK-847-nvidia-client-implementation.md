# TASK-847: Implement NvidiaClient

**Feature**: FEAT-122 — Nvidia Client
**Spec**: `sdd/specs/nvidia-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-846
**Assigned-to**: unassigned

---

## Context

Create the `NvidiaClient` class that extends `OpenAIClient` and routes
requests through Nvidia NIM's OpenAI-compatible gateway at
`https://integrate.api.nvidia.com/v1`. Implements Module 2 of the spec
(§3 Module Breakdown).

The key design point: Nvidia's endpoint is OpenAI-compatible, so ALL
existing OpenAI machinery (completion, streaming, tool calling, retry,
invoke, per-loop cache) is inherited unchanged. The only Nvidia-specific
affordance is the `enable_thinking` keyword on `ask`/`ask_stream` that
injects `chat_template_kwargs` into `extra_body` for reasoning-capable
models such as `z-ai/glm-5.1`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/clients/nvidia.py`.
- Define `NvidiaClient(OpenAIClient)` with:
  - `client_type = "nvidia"`, `client_name = "nvidia"`,
    `_default_model = NvidiaModel.KIMI_K2_INSTRUCT_0905.value`.
  - `__init__(api_key: Optional[str] = None, **kwargs)` that resolves
    the key from `config.get("NVIDIA_API_KEY")` when missing, calls
    `super().__init__(api_key=..., base_url="https://integrate.api.nvidia.com/v1", **kwargs)`,
    and re-sets `self.api_key` after `super().__init__` (same guard as
    `OpenRouterClient`).
  - A private static helper `_merge_thinking_extra_body(extra_body, enable_thinking, clear_thinking)` that returns
    the merged `extra_body` dict (or `None`).
  - An overridden `async def ask(prompt, *, enable_thinking=False, clear_thinking=False, **kwargs)` that merges
    and delegates to `super().ask(prompt, **kwargs)`.
  - An overridden `async def ask_stream(prompt, *, enable_thinking=False, clear_thinking=False, **kwargs)` that
    merges and delegates to `super().ask_stream(prompt, **kwargs)`.

**NOT in scope**:
- Factory registration (TASK-848).
- Unit tests (TASK-849).
- `list_models()` helper — explicit open question, deferred.
- Overriding `get_client`, `_chat_completion`, or `invoke`.
- Any custom header injection (no `default_headers` — unlike OpenRouter).
- `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` expansion — spec §7 explicitly
  says do NOT expand this set here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/nvidia.py` | CREATE | `NvidiaClient(OpenAIClient)` implementation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Third-party — already in pyproject
from navconfig import config                       # verified: packages/ai-parrot/src/parrot/clients/gpt.py:17

# Parent class
from .gpt import OpenAIClient                      # verified: packages/ai-parrot/src/parrot/clients/gpt.py:90

# Enum created in TASK-846
from ..models.nvidia import NvidiaModel            # will exist after TASK-846

# Stdlib
from typing import Any, Dict, Optional
from logging import getLogger
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(AbstractClient):                                   # line 90
    client_type: str = 'openai'                                       # line 93
    client_name: str = 'openai'                                       # line 95
    _default_model: str = 'gpt-4o-mini'                               # line 96

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
```

Reference pattern (exact analog — copy the `super().__init__` + re-set
`self.api_key` idiom):
```python
# packages/ai-parrot/src/parrot/clients/openrouter.py
class OpenRouterClient(OpenAIClient):                                 # line 23
    client_type: str = "openrouter"                                   # line 49
    client_name: str = "openrouter"                                   # line 50
    _default_model: str = OpenRouterModel.DEEPSEEK_R1.value           # line 51

    def __init__(self, api_key=None, ..., **kwargs):                  # line 53
        ...
        resolved_key = api_key or config.get('OPENROUTER_API_KEY')    # line 68
        super().__init__(
            api_key=resolved_key,
            base_url="https://openrouter.ai/api/v1",
            **kwargs,
        )                                                             # line 69-73
        self.api_key = resolved_key                                   # line 75 — guard against super overwrite
```

### Does NOT Exist
- ~~`OpenAIClient.enable_thinking`~~ — not a parent attribute; must be added here.
- ~~`OpenAIClient.supports_reasoning`~~ — no such flag exists.
- ~~`AsyncOpenAI(reasoning=...)`~~ — not a constructor kwarg.
- ~~`parrot.clients.NvidiaClient`~~ — does not exist yet; this task creates it.
- ~~A separate `NvidiaUsage`/`NvidiaGenerationStats`~~ — Nvidia has no
  generation-stats endpoint. Do NOT invent one.
- ~~Subpackage `parrot/clients/nvidia/__init__.py`~~ — this is a single
  file `parrot/clients/nvidia.py` (mirror openrouter, grok, groq, vllm).
- ~~`get_client` override~~ — inherited parent implementation already
  honours `self.base_url`; do NOT reimplement.
- ~~`_chat_completion` override~~ — inherited retry/completion path is
  sufficient (see spec §2 Overview).

---

## Implementation Notes

### Pattern to Follow
Directly mirror `OpenRouterClient.__init__` but without `app_name`, `site_url`, or `provider_preferences`.
Do NOT override `get_client` — parent `OpenAIClient.get_client` already
constructs `AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, ...)`,
which is what we want.

### Reference implementation sketch (from spec §7)
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

### Key Constraints
- Async-first: `ask`/`ask_stream` remain `async`. `ask_stream` must be an
  `async def` that yields via `async for ... yield`.
- The `_merge_thinking_extra_body` helper MUST preserve any pre-existing
  keys in `extra_body` and any pre-existing keys inside
  `extra_body["chat_template_kwargs"]`.
- When `enable_thinking=False`, the helper returns `extra_body` UNCHANGED
  (including returning `None` if it was `None` — do not materialise an
  empty dict).
- Use `config.get("NVIDIA_API_KEY")` — not `os.getenv` — to match project
  convention (see `openrouter.py:68`, `gpt.py:106`).
- `self.api_key` must be re-set after `super().__init__` (see reference
  pattern at `openrouter.py:75`).
- `getLogger(__name__)` at module level is fine (matches `openrouter.py:20`),
  but inside the class use `self.logger` which is inherited from
  `AbstractClient`.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/openrouter.py` — direct analog.
- `packages/ai-parrot/src/parrot/clients/gpt.py` — parent class.
- `packages/ai-parrot/src/parrot/clients/vllm.py:70-104` — another
  `__init__`-only subclass pattern (of `LocalLLMClient`).

---

## Acceptance Criteria

- [ ] File `packages/ai-parrot/src/parrot/clients/nvidia.py` exists.
- [ ] `from parrot.clients.nvidia import NvidiaClient` works.
- [ ] `NvidiaClient` is a subclass of `OpenAIClient` (`issubclass(NvidiaClient, OpenAIClient) is True`).
- [ ] Constructing `NvidiaClient(api_key="x")` produces an instance with:
  - `client.base_url == "https://integrate.api.nvidia.com/v1"`
  - `client.api_key == "x"`
  - `client.client_type == "nvidia"`
  - `client.client_name == "nvidia"`
  - `client._default_model == "moonshotai/kimi-k2-instruct-0905"`
- [ ] When `api_key` is `None`, the client falls back to
  `config.get("NVIDIA_API_KEY")`.
- [ ] `_merge_thinking_extra_body(None, False, False)` returns `None`.
- [ ] `_merge_thinking_extra_body({"k": 1}, True, False)` returns
  `{"k": 1, "chat_template_kwargs": {"enable_thinking": True, "clear_thinking": False}}`.
- [ ] `_merge_thinking_extra_body({"chat_template_kwargs": {"other": 1}}, True, True)`
  returns `{"chat_template_kwargs": {"other": 1, "enable_thinking": True, "clear_thinking": True}}`.
- [ ] `ask(prompt, enable_thinking=True)` reaches
  `OpenAIClient.ask` with `kwargs["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True`.
- [ ] `ask(prompt)` without `enable_thinking` does NOT add
  `chat_template_kwargs` (the `extra_body` passed to super is either
  absent or unchanged from caller).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/nvidia.py`.
- [ ] No new runtime dependencies introduced.

---

## Test Specification

Formal tests live in TASK-849. For this task, run the following smoke
checks after implementation:

```python
# venv activated
python -c "
from parrot.clients.nvidia import NvidiaClient
from parrot.clients.gpt import OpenAIClient

assert issubclass(NvidiaClient, OpenAIClient)

c = NvidiaClient(api_key='x')
assert c.base_url == 'https://integrate.api.nvidia.com/v1'
assert c.api_key == 'x'
assert c.client_type == 'nvidia'
assert c._default_model == 'moonshotai/kimi-k2-instruct-0905'

# Helper behaviour
assert NvidiaClient._merge_thinking_extra_body(None, False, False) is None
assert NvidiaClient._merge_thinking_extra_body({'k': 1}, True, False) == {
    'k': 1,
    'chat_template_kwargs': {'enable_thinking': True, 'clear_thinking': False},
}

print('ok')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-846 must be in `tasks/completed/`.
3. **Verify the Codebase Contract** — before writing code:
   - `read packages/ai-parrot/src/parrot/clients/gpt.py` and confirm the
     signature of `OpenAIClient.__init__` at line 100 still matches.
   - `read packages/ai-parrot/src/parrot/clients/openrouter.py` and
     confirm the `super().__init__ + self.api_key=resolved_key` guard
     is still at ~line 69-75.
   - `read packages/ai-parrot/src/parrot/models/nvidia.py` and confirm
     `NvidiaModel.KIMI_K2_INSTRUCT_0905.value == "moonshotai/kimi-k2-instruct-0905"`.
   - If anything drifted, update the contract FIRST, then implement.
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID.
5. **Implement** strictly per the reference implementation sketch.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `tasks/completed/TASK-847-nvidia-client-implementation.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
