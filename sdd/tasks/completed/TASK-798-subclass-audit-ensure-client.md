# TASK-798: Audit remaining LLM subclasses — migrate "Client not initialized" guards

**Feature**: FEAT-112 — Per-Loop LLM Client Cache
**Spec**: `sdd/specs/per-loop-llm-client-cache.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-795
**Assigned-to**: unassigned

---

## Context

With TASK-795 landed, `self.client` is a property that returns `None` on any
loop that has never called `_ensure_client()`. Existing subclasses fail loudly
when callers forget `async with ...:` — e.g. `AnthropicClient.ask()` has
`if not self.client: raise RuntimeError("Client not initialized. Use async
context manager.")` at `clients/claude.py:108`. Those guards are still useful
*but* they now fire incorrectly on a valid wrapper that has just never been
entered on this loop. Either ensure `ask()` calls `await self._ensure_client()`
itself, or keep the guard and migrate callers to always use `async with`.

Spec §3 Module 3 explicitly directs "have `ask()` call
`await self._ensure_client()` itself" for the non-Grok subclasses.

See spec §3 (Module 3).

---

## Scope

Audit and (where needed) update these subclasses:

- `packages/ai-parrot/src/parrot/clients/claude.py` (`AnthropicClient`)
- `packages/ai-parrot/src/parrot/clients/gpt.py` (`OpenAIClient`)
- `packages/ai-parrot/src/parrot/clients/groq.py` (`GroqClient`)
- `packages/ai-parrot/src/parrot/clients/openrouter.py` (`OpenRouterClient`)
- `packages/ai-parrot/src/parrot/clients/localllm.py` (`LocalLLMClient`)
- `packages/ai-parrot/src/parrot/clients/vllm.py` (`vLLMClient`)

For each file, in this order:

1. Grep for `self.client =` **outside `__init__`**. If any writes exist, replace
   them with returning the constructed client from `get_client()` (matching the
   base contract). Writes to `self.client = None` inside `close()` must also be
   removed — `super().close()` already clears the per-loop entries.
2. Grep for the string `"Client not initialized"`. For each match, locate the
   enclosing method; at the top of that method, add:

   ```python
   await self._ensure_client()   # ← ensures per-loop entry exists
   ```

   and drop the `raise RuntimeError("Client not initialized. ...")` guard.
   Rationale: after the base rewrite, `self.client is None` just means "this
   loop has not yet built one" — which we can fix transparently.
3. For any `get_client()` implementation that caches on `self.client` (like
   Grok did), strip the caching and `return` the constructed client directly.
4. Confirm no `self.client` writes survive in any of these files outside `__init__`.
5. Inspect `__init__`: remove `self.client = None` lines — the base property
   owns the attribute now.

**NOT in scope**:
- `parrot/clients/google/client.py` (TASK-796).
- `parrot/clients/grok.py` (TASK-797).
- `parrot/clients/live.py` (TASK-799).
- `parrot/clients/hf.py` / `parrot/clients/gemma4.py` — both are Transformers-
  based, no SDK HTTP session (spec §2 Component Diagram lists them as N/A).
- `parrot/clients/factory.py` — no change needed (spec §2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/claude.py` | MODIFY | Drop `self.client = None` in `__init__` (line 58); replace the `RuntimeError` guard at line 108 with `await self._ensure_client()`; audit every other `"Client not initialized"` occurrence in the file. |
| `packages/ai-parrot/src/parrot/clients/gpt.py` | MODIFY | Same pattern; audit `ask()` and streaming entry points. |
| `packages/ai-parrot/src/parrot/clients/groq.py` | MODIFY | Same pattern. |
| `packages/ai-parrot/src/parrot/clients/openrouter.py` | MODIFY | Subclass of `OpenAIClient` — likely zero-diff after the `gpt.py` audit; verify and document "no change" in the completion note if so. |
| `packages/ai-parrot/src/parrot/clients/localllm.py` | MODIFY | Same pattern; verify any direct `self.client` writes. |
| `packages/ai-parrot/src/parrot/clients/vllm.py` | MODIFY | Subclass of `LocalLLMClient` — likely zero-diff; verify. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (by file)

```python
# claude.py — verified lines 40-80
from anthropic import AsyncAnthropic                            # line ~20
from parrot.clients.base import AbstractClient                  # base class

# gpt.py — verified line 90, 126
from openai import AsyncOpenAI

# groq.py — verified line 46, 76
from groq import AsyncGroq
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/claude.py
class AnthropicClient(AbstractClient):                          # line 40
    client_type: str = "anthropic"
    client_name: str = "claude"
    use_session: bool = False                                   # line 45

    def __init__(self, api_key=None, base_url=..., **kwargs):   # line 50
        self.api_key = api_key or config.get('ANTHROPIC_API_KEY')
        self.base_url = base_url
        self.client: Optional[AsyncAnthropic] = None            # line 58  <-- REMOVE
        self.base_headers = {...}                               # lines 59-63
        super().__init__(**kwargs)                              # line 64

    async def get_client(self) -> AsyncAnthropic:               # line 66
        return AsyncAnthropic(api_key=self.api_key, max_retries=2)  # line 68-71

    async def ask(self, prompt, ..., context_1m: bool = False):  # line 82
        if not self.client:
            raise RuntimeError("Client not initialized. Use async context manager.")  # line 108-109  <-- MIGRATE

# ClaudeClient = AnthropicClient                                # alias, line 1470 (DO NOT redefine)
```

```python
# packages/ai-parrot/src/parrot/clients/gpt.py
class OpenAIClient(AbstractClient):                             # line 90
    async def get_client(self) -> AsyncOpenAI:                  # line 126
        return AsyncOpenAI(api_key=..., base_url=..., timeout=...)
    # Grep for "Client not initialized" and self.client = writes in this file.
```

```python
# packages/ai-parrot/src/parrot/clients/groq.py
class GroqClient(AbstractClient):                               # line 46
    client_type: str = "groq"                                   # line 56
    async def get_client(self) -> AsyncGroq:                    # line 76
        return AsyncGroq(api_key=self.api_key)
    # Grep for "Client not initialized" and self.client = writes in this file.
```

### Does NOT Exist

- ~~`parrot.clients.ClaudeClient` as a standalone class~~ — it is only an alias
  for `AnthropicClient` at `clients/claude.py:1470`. Do NOT define a separate class.
- ~~`AnthropicClient.client_pool`~~ — Anthropic's `AsyncAnthropic` owns its own httpx pool; no pool attribute here.
- ~~`OpenAIClient.session_factory`~~ — no factory pattern; the client is the pool.
- ~~`LocalLLMClient.session` / `vLLMClient.session`~~ — verify via grep; confirmed no `use_session=True` in any of these subclasses.

---

## Implementation Notes

### Pattern to Follow

Before (example from `claude.py:108`):

```python
async def ask(self, prompt, ...):
    if not self.client:
        raise RuntimeError("Client not initialized. Use async context manager.")
    # ...
```

After:

```python
async def ask(self, prompt, ...):
    await self._ensure_client()
    # ...
```

For `__init__`:

```python
# Before
self.client: Optional[AsyncAnthropic] = None

# After — DELETE the line; base handles it.
```

For any subclass `get_client()` that currently caches internally (Grok-style):

```python
# Before
async def get_client(self):
    if not self.client:
        self.client = Foo(...)
    return self.client

# After
async def get_client(self):
    return Foo(...)
```

### Key Constraints

- `await self._ensure_client()` at the top of a public method is sufficient —
  no need to pass hints unless the subclass needs them (only Google does).
- Do NOT call `await self._ensure_client()` in hot inner loops — the property
  `self.client` after the one-time top-of-method call is a valid cached lookup.
- Verify each file with `grep -n "self.client" <file>` after editing. Only
  reads against `self.client` may remain; zero assignments outside `__init__`
  should survive (and `__init__` assignments should also be gone).
- For subclasses that inherit (e.g. OpenRouterClient from OpenAIClient), the
  inherited audit often means **no change**. Record "no change — inherited"
  in the completion note when applicable.

### References in Codebase

- Base class: `parrot/clients/base.py` post-TASK-795.
- Example pattern (after): TASK-797 for Grok.

---

## Acceptance Criteria

- [ ] `grep -n "self.client\s*=" packages/ai-parrot/src/parrot/clients/claude.py` returns nothing (no assignment).
- [ ] `grep -n "self.client\s*=" packages/ai-parrot/src/parrot/clients/gpt.py` returns nothing.
- [ ] `grep -n "self.client\s*=" packages/ai-parrot/src/parrot/clients/groq.py` returns nothing.
- [ ] `grep -n "self.client\s*=" packages/ai-parrot/src/parrot/clients/openrouter.py` returns nothing.
- [ ] `grep -n "self.client\s*=" packages/ai-parrot/src/parrot/clients/localllm.py` returns nothing.
- [ ] `grep -n "self.client\s*=" packages/ai-parrot/src/parrot/clients/vllm.py` returns nothing.
- [ ] `grep -rn "Client not initialized" packages/ai-parrot/src/parrot/clients/` returns nothing in the six audited files (may still appear elsewhere, e.g. hf.py — out of scope).
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/claude.py packages/ai-parrot/src/parrot/clients/gpt.py packages/ai-parrot/src/parrot/clients/groq.py packages/ai-parrot/src/parrot/clients/openrouter.py packages/ai-parrot/src/parrot/clients/localllm.py packages/ai-parrot/src/parrot/clients/vllm.py` is clean.
- [ ] `pytest packages/ai-parrot/tests/test_anthropic_client.py --collect-only` (and the matching openai / groq / localllm / vllm test files) still collects.
- [ ] Completion note records any subclass that required "no change" because it inherited from a parent already migrated.

---

## Test Specification

> Formal tests in TASK-800. Quick import smoke here:

```python
from parrot.clients.claude import AnthropicClient, ClaudeClient
from parrot.clients.gpt import OpenAIClient
from parrot.clients.groq import GroqClient
from parrot.clients.openrouter import OpenRouterClient
from parrot.clients.localllm import LocalLLMClient
from parrot.clients.vllm import vLLMClient
assert ClaudeClient is AnthropicClient   # alias preserved
```

---

## Agent Instructions

1. Verify TASK-795 is in `sdd/tasks/completed/`.
2. For each file listed, run the greps in the Codebase Contract BEFORE editing.
3. Apply the pattern in the order listed in the Scope section.
4. Re-run the greps as acceptance checks after each file.
5. Do the import smoke test above.
6. Move this file to `sdd/tasks/completed/`; update the index.
7. Commit: `sdd: TASK-798 — audit remaining LLM subclasses for per-loop cache`.

---

## Completion Note

**Completed by**: claude-sonnet-4-6 (sdd-worker)
**Date**: 2026-04-22
**Notes**: 
- claude.py: removed self.client=None from __init__, replaced 10 RuntimeError guards
- gpt.py: replaced 1 RuntimeError guard
- groq.py: replaced 3 guards (1 if not self.client, 2 if not self.session)
- localllm.py: replaced self.client=await self.get_client() with _ensure_client()
- vllm.py: replaced self.client=await self.get_client() with _ensure_client()
- openrouter.py: no change needed (inherits from OpenAIClient — "no change: inherited")
**Deviations from spec**: None.
