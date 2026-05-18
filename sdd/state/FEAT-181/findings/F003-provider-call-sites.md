---
id: F003
query_id: Q006
type: grep
intent: Per-provider SDK call sites where the cache-marker injection must happen.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — Per-provider call sites: messages.create / chat.completions / generate_content

## Summary

Each `AbstractClient` subclass calls a different provider SDK shape:
**Anthropic** uses `self.client.messages.create(**payload)` and
`.stream(**payload)` with `payload["system"] = system_prompt` as a plain
string (≥13 call sites in `claude.py`). **OpenAI/Groq/Grok/OpenRouter**
use `self.client.chat.completions.create(**kwargs)` or
`responses.create(**payload)` — the system message is part of the
`messages=[...]` list. **Google/Gemini** uses
`self.client.aio.models.generate_content(...)` (async path at
`google/client.py:2273, 2890, 3453, 3713, 3739, 3770`; sync wrappers in
`google/analysis.py` and `google/generation.py`) with system instructions
passed through the `config` parameter. The clients list is comprehensive:
`base.py`, `claude.py`, `claude_agent.py`, `gpt.py`, `gemma4.py`,
`google/`, `grok.py`, `groq.py`, `hf.py`, `live.py`, `localllm.py`,
`nvidia.py`, `openrouter.py`, `vllm.py`, plus `factory.py`.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/`
  lines: directory listing
  symbol: provider modules
  excerpt: |
    base.py  claude.py  claude_agent.py  factory.py  gemma4.py
    google/  gpt.py  grok.py  groq.py  hf.py  live.py
    localllm.py  models.py  nvidia.py  openrouter.py  vllm.py

- path: `packages/ai-parrot/src/parrot/clients/claude.py`
  lines: 188-235
  symbol: `payload["system"] = system_prompt` (representative)
  excerpt: |
    payload = {
        "model": model,
        "max_tokens": _max_tokens,
        "temperature": temperature or self.temperature,
        "messages": messages
    }
    if system_prompt:
        payload["system"] = system_prompt
    ...
    response = await self.client.messages.create(**payload)

- path: `packages/ai-parrot/src/parrot/clients/claude.py`
  lines: 222, 231, 431, 594, 982-986, 1015, 1127, 1134, 1214, 1221, 1284, 1290, 1359, 1365, 1460, 1463, 1531, 1546
  symbol: messages.create / stream call sites + system assignments
  excerpt: |
    response = await self.client.messages.create(**payload)
    async with self.client.messages.stream(**payload) as stream:
    payload["system"] = ...   # multiple sites
    "system": system_prompt   # in literal payloads at 1127, 1214, 1284, 1359, 1460

- path: `packages/ai-parrot/src/parrot/clients/gpt.py`
  lines: 274, 276, 470-495, 1444-1460, 1653, 2167, 2452
  symbol: chat.completions.create / responses.create
  excerpt: |
    method = self.client.chat.completions.create
    method = getattr(self.client.chat.completions, 'parse', self.client.chat.completions.create)
    return await self.client.responses.create(**payload)
    response = await self.client.chat.completions.create(...)

- path: `packages/ai-parrot/src/parrot/clients/groq.py`
  lines: 399, 498, 541, 687, 804, 883, 952, 1067, 1184, 1297, 1322, 1345
  symbol: chat.completions.create (12 call sites)
  excerpt: |
    response = await self.client.chat.completions.create(**request_args)

- path: `packages/ai-parrot/src/parrot/clients/grok.py`
  lines: 789
  symbol: chat.completions.create
  excerpt: |
    response = await self.client.chat.completions.create(**kwargs)

- path: `packages/ai-parrot/src/parrot/clients/google/client.py`
  lines: 2273, 2890, 3453, 3713, 3739, 3770
  symbol: `self.client.aio.models.generate_content`
  excerpt: |
    structured_response = await self.client.aio.models.generate_content(...)
    first_response = await self.client.aio.models.generate_content(...)

- path: `packages/ai-parrot/src/parrot/clients/google/analysis.py`
  lines: 96, 173, 411, 580, 764, 773, 958, 1018, 1076, 1145
  symbol: generate_content (sync + aio)
  excerpt: |
    response = self.client.models.generate_content(...)
    response = await self.client.aio.models.generate_content(...)

- path: `packages/ai-parrot/src/parrot/clients/google/generation.py`
  lines: 362, 506, 1592, 1798, 2104
  symbol: generate_content via partial / aio
  excerpt: |
    sync_generate_content = partial(self.client.models.generate_content, ...)
    response = await self.client.aio.models.generate_content(...)

## Notes

For Anthropic, enabling `cache_control` requires changing
`payload["system"] = "<str>"` → `payload["system"] = [{"type": "text",
"text": "<str>", "cache_control": {"type": "ephemeral"}}]`. The 13+ call
sites in `claude.py` all build the payload via the same pattern, so a
single helper (`_apply_system_prompt(payload, system_prompt, cache=True)`)
will cover them. OpenAI requires no payload change for default caching
(automatic on ≥1024-token prefixes) but accepts an optional
`prompt_cache_key` field. Gemini's `CachedContent` requires a separate
`client.caches.create(...)` call BEFORE `generate_content` — fundamentally
asymmetric with Anthropic's inline approach. This is the largest tradeoff
the design must reconcile.
