# TASK-859: Factory Registration & Lazy Loader for ClaudeAgentClient

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-858
**Assigned-to**: unassigned

---

## Context

> Spec Module 5. For `ClaudeAgentClient` to be usable via `LLMFactory.create("claude-agent")`,
> it must be registered in `SUPPORTED_CLIENTS` with a lazy loader — mirroring the
> `_lazy_gemma4` pattern at `factory.py:14`. This keeps `claude_agent_sdk` off the
> import path unless explicitly requested.

---

## Scope

- Add `_lazy_claude_agent()` function in `packages/ai-parrot/src/parrot/clients/factory.py`
  that imports and returns `ClaudeAgentClient`.
- Register under keys `"claude-agent"` and `"claude-code"` in `SUPPORTED_CLIENTS`.
- Ensure that when `claude_agent_sdk` is not installed, calling
  `LLMFactory.create("claude-agent")` raises `ImportError` with the hint
  `pip install ai-parrot[claude-agent]`.
- Ensure `LLMFactory.parse_llm_string("claude-agent:claude-sonnet-4-6")` returns
  `("claude-agent", "claude-sonnet-4-6")`.

**NOT in scope**: `ClaudeAgentClient` implementation (TASK-858), tests (TASK-861),
pyproject extras (TASK-860).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | Add `_lazy_claude_agent` and register in `SUPPORTED_CLIENTS` |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from parrot.clients.claude_agent import ClaudeAgentClient  # NEW (TASK-858 creates this)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
def _lazy_gemma4():                                          # line 14
    from .gemma4 import Gemma4Client
    return Gemma4Client

SUPPORTED_CLIENTS = {                                        # line 19
    "claude": AnthropicClient,
    "anthropic": AnthropicClient,
    "google": GoogleGenAIClient,
    "openai": OpenAIClient,
    "groq": GroqClient,
    "grok": GrokClient,
    "xai": GrokClient,
    "openrouter": OpenRouterClient,
    "nvidia": NvidiaClient,
    "local": LocalLLMClient,
    "localllm": LocalLLMClient,
    "ollama": LocalLLMClient,
    "vllm": vLLMClient,
    "llamacpp": LocalLLMClient,
    "gemma4": _lazy_gemma4,
}                                                            # line 35

class LLMFactory:                                            # line 38
    @staticmethod
    def parse_llm_string(llm: str) -> Tuple[str, Optional[str]]:  # line 48
    @staticmethod
    def create(llm, model_args=None, tool_manager=None,
               **kwargs) -> AbstractClient: ...              # line 70
    # Inside create():
    # line 111: if provider not in SUPPORTED_CLIENTS:
    # line 118: client_class = SUPPORTED_CLIENTS[provider]
    # line 119: if callable(client_class) and not isinstance(client_class, type):
    # line 120:     client_class = client_class()  # call lazy loader
```

### Does NOT Exist
- ~~`_lazy_claude_agent`~~ — does not exist yet (this task creates it)
- ~~`SUPPORTED_CLIENTS["claude-agent"]`~~ — does not exist yet
- ~~`SUPPORTED_CLIENTS["claude-code"]`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror _lazy_gemma4 exactly (factory.py:14-16)
def _lazy_claude_agent():
    try:
        from .claude_agent import ClaudeAgentClient
        return ClaudeAgentClient
    except ImportError:
        raise ImportError(
            "ClaudeAgentClient requires claude-agent-sdk. "
            "Install with: pip install ai-parrot[claude-agent]"
        )

# Then add to SUPPORTED_CLIENTS dict:
SUPPORTED_CLIENTS = {
    ...
    "claude-agent": _lazy_claude_agent,
    "claude-code": _lazy_claude_agent,
}
```

### Key Constraints
- The lazy loader MUST catch `ImportError` from `claude_agent_sdk` (raised inside
  `ClaudeAgentClient` methods) and re-raise with a hint message at `create()` time
- Both `"claude-agent"` and `"claude-code"` keys map to the same lazy loader
- Do NOT add a top-level `from .claude_agent import ...` at the top of `factory.py`
- The `parse_llm_string` already handles `"claude-agent:model"` format via `:`-split (line 48)

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/factory.py:14-16` — `_lazy_gemma4` pattern
- `packages/ai-parrot/src/parrot/clients/factory.py:119-120` — lazy loader call in `create()`

---

## Acceptance Criteria

- [ ] `_lazy_claude_agent()` function exists in `factory.py`
- [ ] `SUPPORTED_CLIENTS["claude-agent"]` maps to `_lazy_claude_agent`
- [ ] `SUPPORTED_CLIENTS["claude-code"]` maps to `_lazy_claude_agent`
- [ ] `LLMFactory.parse_llm_string("claude-agent:claude-sonnet-4-6")` returns `("claude-agent", "claude-sonnet-4-6")`
- [ ] `LLMFactory.create("claude-agent")` returns a `ClaudeAgentClient` when SDK is installed
- [ ] `LLMFactory.create("claude-agent")` raises `ImportError` with `pip install` hint when SDK is missing
- [ ] No top-level import of `claude_agent` in `factory.py`

---

## Test Specification

```python
# Quick verification — full tests in TASK-861
def test_factory_resolves_claude_agent():
    from parrot.clients.factory import LLMFactory
    provider, model = LLMFactory.parse_llm_string("claude-agent:claude-sonnet-4-6")
    assert provider == "claude-agent"
    assert model == "claude-sonnet-4-6"

def test_factory_resolves_claude_code_alias():
    from parrot.clients.factory import LLMFactory
    provider, model = LLMFactory.parse_llm_string("claude-code:claude-sonnet-4-6")
    assert provider == "claude-code"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-858 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `factory.py` structure matches
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** the lazy loader and registration
6. **Verify** parse and create work for both keys
7. **Move this file** to `tasks/completed/TASK-859-factory-registration-lazy-loader.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
