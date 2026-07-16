# TASK-1796: Factory Registration for MoonshotClient

**Feature**: FEAT-311 — Moonshot Client (MoonshotClient)
**Spec**: `sdd/specs/moonshot-client-llm.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1795
**Assigned-to**: unassigned

---

## Context

Register `MoonshotClient` in the `LLMFactory` so users can create clients via
`LLMFactory.create("moonshot:kimi-k3")` or `LLMFactory.create("kimi:kimi-k2.6")`.

Implements spec §3 Module 3.

---

## Scope

- Add `from .moonshot import MoonshotClient` import to `factory.py`
- Add `"moonshot": MoonshotClient` entry to `SUPPORTED_CLIENTS`
- Add `"kimi": MoonshotClient` entry to `SUPPORTED_CLIENTS`

**NOT in scope**: Client implementation (TASK-1795), tests (TASK-1797)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | Add import + two dict entries |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/clients/factory.py:1-12
from typing import Any, Dict, Optional, Tuple
from .base import AbstractClient
from .claude import AnthropicClient
from .google import GoogleGenAIClient
from .gpt import OpenAIClient
from .groq import GroqClient
from .grok import GrokClient
from .openrouter import OpenRouterClient
from .localllm import LocalLLMClient
from .vllm import vLLMClient
from .nvidia import NvidiaClient
from .zai import ZaiClient
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/factory.py:64-91
SUPPORTED_CLIENTS = {
    "claude": AnthropicClient,                # line 65
    "anthropic": AnthropicClient,             # line 66
    "bedrock": AnthropicClient,               # line 69
    "anthropic-aws": AnthropicClient,         # line 70
    "bedrock-converse": _lazy_bedrock_converse,  # line 73
    "google": GoogleGenAIClient,              # line 74
    "openai": OpenAIClient,                   # line 75
    "groq": GroqClient,                       # line 76
    "grok": GrokClient,                       # line 77
    "xai": GrokClient,                        # line 78
    "zai": ZaiClient,                         # line 79
    "z.ai": ZaiClient,                        # line 80
    "openrouter": OpenRouterClient,           # line 81
    "nvidia": NvidiaClient,                   # line 82
    "local": LocalLLMClient,                  # line 83
    "localllm": LocalLLMClient,               # line 84
    "ollama": LocalLLMClient,                 # line 85
    "vllm": vLLMClient,                       # line 86
    "llamacpp": LocalLLMClient,               # line 87
    "gemma4": _lazy_gemma4,                   # line 88
    "claude-agent": _lazy_claude_agent,       # line 89
    "claude-code": _lazy_claude_agent,        # line 90
}
```

### Does NOT Exist

- ~~`"moonshot"` in SUPPORTED_CLIENTS~~ — not registered yet; this task adds it
- ~~`"kimi"` in SUPPORTED_CLIENTS~~ — not registered yet; this task adds it

---

## Implementation Notes

### Exact Changes

1. Add import after the `ZaiClient` import (line 12):
```python
from .moonshot import MoonshotClient
```

2. Add two entries to `SUPPORTED_CLIENTS` dict, after `"nvidia"` (line 82):
```python
    "moonshot": MoonshotClient,
    "kimi": MoonshotClient,
```

### Key Constraints

- Direct import (not lazy loader) — `MoonshotClient` has no heavy optional
  dependencies that would justify lazy loading. It uses the `openai` SDK
  which is already a dependency via `OpenAIClient`.
- Both `"moonshot"` and `"kimi"` map to the same class (like `"grok"` and
  `"xai"` both map to `GrokClient`).

### References in Codebase

- `packages/ai-parrot/src/parrot/clients/factory.py` — the only file to modify

---

## Acceptance Criteria

- [ ] `from .moonshot import MoonshotClient` added to factory.py imports
- [ ] `"moonshot": MoonshotClient` in SUPPORTED_CLIENTS
- [ ] `"kimi": MoonshotClient` in SUPPORTED_CLIENTS
- [ ] `LLMFactory.create("moonshot")` returns a MoonshotClient
- [ ] `LLMFactory.create("kimi:kimi-k3")` returns a MoonshotClient with model="kimi-k3"
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/factory.py`

---

## Test Specification

```python
# Covered by TASK-1797 tests
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.moonshot import MoonshotClient

assert "moonshot" in SUPPORTED_CLIENTS
assert "kimi" in SUPPORTED_CLIENTS
assert SUPPORTED_CLIENTS["moonshot"] is MoonshotClient
assert SUPPORTED_CLIENTS["kimi"] is MoonshotClient
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — verify TASK-1795 is completed
2. **Read `factory.py`** — confirm current structure matches the contract
3. **Add the import and dict entries** — minimal change, 3 lines
4. **Verify** all acceptance criteria
5. **Move this file** to `sdd/tasks/completed/TASK-1796-moonshot-factory-registration.md`
6. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
