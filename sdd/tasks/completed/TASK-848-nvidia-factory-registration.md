# TASK-848: Register NvidiaClient in LLMFactory

**Feature**: FEAT-122 — Nvidia Client
**Spec**: `sdd/specs/nvidia-client.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-847
**Assigned-to**: unassigned

---

## Context

Add `"nvidia"` to `SUPPORTED_CLIENTS` in `parrot.clients.factory` so users
can construct an `NvidiaClient` via `LLMFactory.create("nvidia:moonshotai/kimi-k2-thinking")`.
Implements Module 3 of the spec (§3 Module Breakdown).

This is a single-line-plus-import change. `LLMFactory.parse_llm_string`
(factory.py:46) already handles the `"provider:model"` form and forwards
arbitrary model slugs to the client's `model` kwarg, so no parser changes
are needed.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/clients/factory.py`:
  - Add `from .nvidia import NvidiaClient` alongside the other client imports.
  - Add `"nvidia": NvidiaClient,` to `SUPPORTED_CLIENTS`.

**NOT in scope**:
- Modifying `LLMFactory.parse_llm_string` (already handles the format).
- Modifying `LLMFactory.create` (already forwards `model` kwarg correctly).
- Adding aliases like `"nim"` or `"integrate"` — only `"nvidia"` per spec §1 Goals.
- Lazy-loading the client — Nvidia SDK is just the OpenAI SDK, which is
  always imported; no reason for the `_lazy_gemma4` pattern.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/factory.py` | MODIFY | Import `NvidiaClient`; add `"nvidia"` key to `SUPPORTED_CLIENTS` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already present in factory.py — do NOT duplicate
from .base import AbstractClient
from .claude import AnthropicClient
from .google import GoogleGenAIClient
from .gpt import OpenAIClient
from .groq import GroqClient
from .grok import GrokClient
from .openrouter import OpenRouterClient
from .localllm import LocalLLMClient
from .vllm import vLLMClient

# NEW — add this line alongside the block above
from .nvidia import NvidiaClient   # created by TASK-847
```

### Existing Signatures to Use
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
    def create(llm, model_args=None, tool_manager=None, **kwargs) -> AbstractClient: ...  # line 68
```

### Does NOT Exist
- ~~Alias key `"nim"`, `"nvidia-nim"`, `"integrate"`~~ — not in spec; do NOT add.
- ~~A lazy loader like `_lazy_nvidia`~~ — unnecessary; import directly.
- ~~A new kwarg on `LLMFactory.create` for Nvidia-specific parameters~~ — none needed.

---

## Implementation Notes

### Exact change
Two edits to `packages/ai-parrot/src/parrot/clients/factory.py`:

1. **Insert** the import. Place it after `from .vllm import vLLMClient`:
   ```python
   from .vllm import vLLMClient
   from .nvidia import NvidiaClient          # <-- new line
   ```

2. **Insert** the registration. Place it alphabetically near `"openrouter"`,
   or at the end before `"gemma4"` — either is acceptable. Suggested location:
   right after the `"openrouter": OpenRouterClient,` line:
   ```python
       "openrouter": OpenRouterClient,
       "nvidia": NvidiaClient,               # <-- new line
       "local": LocalLLMClient,
   ```

### Key Constraints
- Do not reorder existing entries.
- Do not remove or rename any existing entries.
- Do not add aliases beyond `"nvidia"`.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/factory.py:18` — `SUPPORTED_CLIENTS`.
- `packages/ai-parrot/src/parrot/clients/factory.py:46` — `parse_llm_string` already handles `"provider:model"`.

---

## Acceptance Criteria

- [ ] `from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS` still works.
- [ ] `"nvidia" in SUPPORTED_CLIENTS` is True.
- [ ] `SUPPORTED_CLIENTS["nvidia"] is NvidiaClient`.
- [ ] No other entries of `SUPPORTED_CLIENTS` were mutated.
- [ ] `LLMFactory.create("nvidia:moonshotai/kimi-k2-thinking")` returns
  an `NvidiaClient` whose `.model == "moonshotai/kimi-k2-thinking"`.
- [ ] `LLMFactory.create("nvidia")` returns an `NvidiaClient` (no model
  set on the instance — inherits `_default_model` at call time).
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/factory.py`.

---

## Test Specification

Formal tests live in TASK-849 (`test_factory_registration`,
`test_factory_default_model`). Smoke check after implementation:

```python
# venv activated, NVIDIA_API_KEY set to anything (not called live)
python -c "
import os; os.environ.setdefault('NVIDIA_API_KEY', 'test-key')
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.nvidia import NvidiaClient

assert 'nvidia' in SUPPORTED_CLIENTS
assert SUPPORTED_CLIENTS['nvidia'] is NvidiaClient

c = LLMFactory.create('nvidia:moonshotai/kimi-k2-thinking')
assert isinstance(c, NvidiaClient)
assert c.model == 'moonshotai/kimi-k2-thinking'

print('ok')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-847 must be in `tasks/completed/`.
3. **Verify the Codebase Contract** — before editing:
   - `read packages/ai-parrot/src/parrot/clients/factory.py` and confirm
     `SUPPORTED_CLIENTS` is still at line ~18 with the listed keys.
   - `read packages/ai-parrot/src/parrot/clients/nvidia.py` and confirm
     `NvidiaClient` is importable.
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID.
5. **Implement** the two-line edit per §Implementation Notes. No other changes.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `tasks/completed/TASK-848-nvidia-factory-registration.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Code (sdd-worker)
**Date**: 2026-04-24
**Notes**: Added `from .nvidia import NvidiaClient` import after `from .vllm import vLLMClient`
and registered `"nvidia": NvidiaClient` in `SUPPORTED_CLIENTS` dict after `"openrouter"`.
All acceptance criteria verified: `"nvidia" in SUPPORTED_CLIENTS`, factory creates `NvidiaClient`
with correct model from `"nvidia:model-slug"` strings.

**Deviations from spec**: none
