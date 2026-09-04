# F005 — `OpenAIBaseClient` is the purpose-built extension point (FEAT-438)

**Path**: `packages/ai-parrot/src/parrot/clients/openai_base.py` (52.6 KB)
**Doc**: `docs/clients/openai-compatible.md`
**Spec**: `sdd/specs/openai-compatible-clients.spec.md`

Hierarchy:
```
AbstractClient (base.py)
   └── OpenAIBaseClient (openai_base.py)   [wire protocol, ZERO OpenAI defaults]
          ├── OpenAIClient (gpt.py)        [privileged: gpt-*, Responses API, Sora]
          ├── OpenRouterClient / MoonshotClient / NvidiaClient
          ├── LocalLLMClient ── vLLMClient / BedrockMantleClient
          └── GroqClient / ZaiClient       [native SDKs, override _chat_completion]
```

- `tool_format = ToolFormat.OPENAI`.
- **Declares no `_default_model` / `_fallback_model` / `_lightweight_model`** —
  the "no-`gpt-*`-defaults rule", enforced by
  `tests/clients/test_openai_compatible_defaults.py`.
- `_chat_completion(model, messages, use_tools=False, stream=False, **kwargs)`
  is **the single funnel**: `ask()`, `ask_stream()`, `resume()`, `invoke()` all
  route through it.
- `_is_responses_model()` returns **`False` in the base** — *"only `OpenAIClient`
  has a Responses API to route to."*

**Implication**: a Chat-Completions MetaClient is a near-mechanical subclass.
Responses-API support is genuinely absent from this layer and is net-new work.
