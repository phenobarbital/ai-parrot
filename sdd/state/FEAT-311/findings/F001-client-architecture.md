---
id: F001
query_type: read
intent: Understand AbstractClient interface and OpenAI-compatible client patterns
files_read:
  - parrot/clients/base.py
  - parrot/clients/gpt.py
  - parrot/clients/nvidia.py
  - parrot/clients/openrouter.py
  - parrot/clients/localllm.py
  - parrot/clients/factory.py
  - parrot/models/ (multiple enums)
---

## Client Inheritance Hierarchy

```
AbstractClient (ABC, EventEmitterMixin) — base.py
├── OpenAIClient (gpt.py) — THE pattern for OpenAI-compatible providers
│   ├── NvidiaClient (nvidia.py) — NIM gateway + thinking mode
│   ├── OpenRouterClient (openrouter.py) — multi-model gateway
│   └── LocalLLMClient (localllm.py) — Ollama/vLLM/llama.cpp
│       └── vLLMClient (vllm.py) — vLLM-specific features
├── AnthropicClient, GroqClient, GrokClient, ZaiClient, etc. (direct AbstractClient)
```

## OpenAI-Compatible Subclass Pattern (NvidiaClient as closest analog)

1. **Extend `OpenAIClient`** (NOT `AbstractClient` directly)
2. Set `client_type`, `client_name`, default model, fallback model
3. Override `get_client()` to set `base_url` for provider's API endpoint
4. API key from env var via `navconfig.config.get()`
5. Override `_chat_completion()` if provider has quirks (e.g., Nvidia can't use `parse()`)
6. Add thinking mode via `contextvars.ContextVar` + `extra_body` injection

## Factory Registration

In `factory.py` → `SUPPORTED_CLIENTS` dict, add provider string → class mapping.
Example: `"moonshot": MoonshotClient, "kimi": MoonshotClient`

## Model Enum

Each provider has a dedicated enum in `parrot/models/`. Pattern: `class XxxModel(str, Enum)`.

## Key Methods to Inherit/Override

- `get_client()` → creates `openai.AsyncOpenAI(api_key=..., base_url=...)`
- `_chat_completion()` → if provider rejects `parse()` or needs `extra_body`
- `ask()` / `ask_stream()` → only if thinking mode needs custom handling
- `_apply_cache_hints()` → if context caching differs from OpenAI auto-cache

## Thinking Mode Pattern (NvidiaClient)

Uses `contextvars.ContextVar` to propagate `enable_thinking` from `ask()`/`ask_stream()` down to `_chat_completion()` without altering parent signatures. Injects into `extra_body`.

## Context Caching

Base class has `_min_cache_tokens: int`. OpenAI auto-caches prefixes ≥ 1024 tokens.
Provider can override `_apply_cache_hints()` for custom caching.

## Vision

OpenAI pattern: `_encode_image_for_openai()` encodes images as base64 `image_url` content blocks. Vision models specified in model enum.
