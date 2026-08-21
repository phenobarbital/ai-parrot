# OpenAI-Compatible Client Base (`OpenAIBaseClient`)

**Audience**: Engineers adding a new OpenAI-wire-compatible LLM provider, or
debugging why one leaked an OpenAI `gpt-*` default.

**Related files**:

- `packages/ai-parrot/src/parrot/clients/openai_base.py` — `OpenAIBaseClient`
- `packages/ai-parrot/src/parrot/clients/gpt.py` — `OpenAIClient` (OpenAI-only)
- `packages/ai-parrot/src/parrot/clients/{openrouter,moonshot,nvidia,localllm,groq,zai}.py`,
  `packages/ai-parrot/src/parrot/clients/nova/mantle.py` — the 8 wire subclasses
- `packages/ai-parrot/src/parrot/clients/base.py` — `AbstractClient` (shared machinery)
- `sdd/specs/openai-compatible-clients.spec.md` — full design (FEAT-438)
- `tests/clients/test_openai_base.py`, `test_openai_base_parity.py`,
  `test_openai_compatible_defaults.py`, `test_fallback_model_shadowing.py`
- `examples/clients/smoke/` — live, credential-gated smoke scripts (this doc's
  companion — see "Live Smoke Testing" below)
- `docs/clients/bedrock-mantle.md` — a worked example of one subclass

---

## Why This Exists

Before FEAT-438, every OpenAI-wire-compatible provider (OpenRouter, Moonshot,
Nvidia, LocalLLM/vLLM, Bedrock Mantle) subclassed `OpenAIClient` directly —
inheriting not just the shared wire protocol but also OpenAI-the-provider's
own defaults: `_default_model`, `_fallback_model`, `_lightweight_model` all
pointed at `gpt-*` ids. A non-OpenAI subclass that didn't override every one
of those attributes could silently call `invoke()` (or hit a capacity
fallback) against a `gpt-*` model id on a provider that has no such model —
the production incident that motivated this feature (a DeepSeek V3.2 request
on OpenRouter 404'ing against a `gpt-4.1` fallback).

FEAT-438 fixes this by inserting a **neutral** layer — `OpenAIBaseClient` —
between `AbstractClient` and every wire-compatible client. It owns the wire
protocol (message shaping, the tool-calling loop, streaming, `invoke()`,
`batch_ask()`, …) but declares **zero** OpenAI-provider defaults.

---

## Hierarchy

```
AbstractClient (base.py)                     [+ FEAT-438 G5 shadowing fix]
   ├── OpenAIBaseClient (openai_base.py)     [NEW — wire protocol, no OpenAI defaults]
   │      ├── OpenAIClient (gpt.py)          [OpenAI-only: gpt-*, Responses API, Sora…]
   │      ├── OpenRouterClient
   │      ├── MoonshotClient                 [drops ask_stream/invoke bypass overrides]
   │      ├── NvidiaClient
   │      ├── LocalLLMClient ── vLLMClient   [drops _is_responses_model override]
   │      ├── BedrockMantleClient            [drops fallback_model workaround]
   │      ├── GroqClient   (Phase 2, keeps native AsyncGroq SDK)
   │      └── ZaiClient    (Phase 2, keeps native zai SDK)
   ├── GrokClient                            [UNCHANGED — xai_sdk, not OpenAI wire]
   └── AnthropicClient / BedrockConverseClient / GoogleGenAIClient / …  [unchanged]
```

`OpenAIClient` is the one privileged subclass: it's the only place `gpt-*`
model ids, `OpenAIModel` alias/deprecation normalization, the Responses API,
Sora video generation, and `openai.RateLimitError`-typed capacity detection
belong. Every other provider subclasses `OpenAIBaseClient` directly, never
`OpenAIClient`.

---

## What Belongs Where

### `AbstractClient` (base.py) — provider-agnostic

Shared across *every* client, OpenAI-wire or not: the tool-calling contract
(`_prepare_tools`/`_resolve_tool_format`/`ToolFormat`), `_resolve_invoke_model`
(already `None`-safe — the no-defaults decision rides on this), the shared
message-context builder (`_prepare_conversation_context`), structured-output
schema helpers (`_build_response_format_from`/`_oai_normalize_schema`/
`_make_openai_strict_tool`), the async-context-manager protocol
(`__aenter__`/`__aexit__`/`_ensure_client()`), and the per-loop SDK client
cache (`self.client` — a loop-local property; see
`sdd/tasks/completed/TASK-795-abstract-client-per-loop-cache.md`).

### `OpenAIBaseClient` (openai_base.py) — the wire protocol, no defaults

Owns the OpenAI *wire format* — request/response shaping, streaming
accumulation, tool-loop mechanics — with **no model-id opinions**:

- `tool_format = ToolFormat.OPENAI` (the one opinion every wire-compatible
  provider genuinely shares: OpenAI-shaped tool schemas).
- **Declares no model attributes.** `_default_model` / `_fallback_model` /
  `_lightweight_model` are left unset, so they inherit `AbstractClient`'s
  `None` — meaning `invoke()`'s resolution chain (explicit `model` kwarg →
  `_lightweight_model` → `self.model`) falls through to `self.model` instead
  of silently defaulting to a `gpt-*` id.
- `get_client()` — builds an `AsyncOpenAI`-shaped client from the subclass's
  `base_url`/`api_key`/timeout. Provider subclasses override this only when
  they need a different SDK (Groq → `AsyncGroq`, Zai → the native `zai` SDK)
  or extra client kwargs (OpenRouter's custom headers).
- `_chat_completion(self, model, messages, use_tools=False, stream=False,
  **kwargs)` — **the single funnel**. Every wire call — `ask()`,
  `ask_stream()`, `resume()`, `invoke()` — routes through this one method.
  See "The Funnel Contract" below.
- The extracted tool-calling loop (`_run_tool_call_loop`) — one
  implementation shared by `ask()` and `resume()`, replacing what used to be
  duplicated logic in `gpt.py`.
- Neutral hooks a subclass may override: `_normalize_model()` (identity in
  the base — `OpenAIClient` overrides it for `OpenAIModel` alias handling),
  `_is_responses_model()` (always `False` in the base — only `OpenAIClient`
  has a Responses API to route to).
- `_resolve_model()`, `_with_extra_body()`, `_encode_image_for_openai()`,
  `_upload_file()`, `batch_ask()`.

### A provider subclass (e.g. `OpenRouterClient`, `NvidiaClient`, …)

Owns exactly three things:

1. **Endpoint + credential resolution** in `__init__` — `base_url`, `api_key`
   (with the provider's own env-var fallback chain), forwarded to
   `super().__init__(api_key=..., base_url=..., **kwargs)`.
2. **Real provider-specific behavior**, kept as an override *only* when it
   encodes something genuinely different about that provider's wire
   contract — e.g. Nvidia's rate limiter + create-not-parse pattern,
   Moonshot's thinking-param/K-series-model guards, OpenRouter's
   `extra_body` provider-routing injection, vLLM's guided-output kwargs.
3. **Model-id defaults, if any** — a subclass MAY set `_default_model`/
   `_fallback_model`/`_lightweight_model` to its own real model ids (e.g.
   Groq sets `_lightweight_model = "kimi-k2-instruct"`). It must never leave
   an *OpenAI* id in one of these attributes.

Overrides that existed only to dodge `OpenAIClient`'s OpenAI-specific
behavior (LocalLLM's `_is_responses_model` override, Moonshot's
`ask_stream`/`invoke` bypass workarounds) were **deleted** during the
FEAT-438 rebase — once the base class carries no such behavior, there is
nothing left to dodge.

### Phase-2 native-SDK subclasses (`GroqClient`, `ZaiClient`)

Groq and Zai speak an OpenAI-*shaped* API but through their own SDKs
(`AsyncGroq`, the official synchronous `zai` client) rather than `AsyncOpenAI`
directly. They still subclass `OpenAIBaseClient` — they override
`get_client()` to return their native SDK client, and override
`_chat_completion()` as the adaptation seam:

```python
# groq.py — AsyncGroq mirrors AsyncOpenAI's chat.completions.create surface,
# so the funnel override is a straight pass-through.
async def _chat_completion(self, model, messages, use_tools=False, stream=False, **kwargs):
    return await self.client.chat.completions.create(
        model=model, messages=messages, stream=stream, **kwargs
    )

# zai.py — the zai SDK is synchronous, so the funnel wraps it in a thread.
async def _chat_completion(self, model, messages, use_tools=False, stream=False, **kwargs):
    request_args = {"model": model, "messages": messages, "stream": stream, **kwargs}
    if stream:
        return self._stream_completion(**request_args)
    return await self._create_completion(**request_args)  # internally asyncio.to_thread()
```

Their bespoke business logic that genuinely differs from the shared
implementation — Groq's explicit `tool_format = ToolFormat.GROQ` (Groq
rejects `"strict": true`, so it cannot inherit `ToolFormat.OPENAI`'s
strict-schema behavior), Zai's "thinking" payload shape, both clients'
structured-output-vs-tools precedence rules — is **kept, unchanged**, gated
by dedicated payload-parity tests (`tests/clients/test_openai_base_parity.py`).
Per the spec: *any parity divergence blocks that client's migration — never
silently normalize a payload to make it "fit" the shared path.*

---

## The Funnel Contract

`_chat_completion(self, model: str, messages: Any, use_tools: bool = False,
stream: bool = False, **kwargs) -> Any` is the **only** place a wire call
leaves the process. `ask()`, `ask_stream()`, `resume()`, and `invoke()` all
route through it (directly, or via the shared `_run_tool_call_loop`) instead
of each calling `self.client.chat.completions.create(...)` independently.

Why this matters: a subclass override of `_chat_completion` applies
**universally** — rate limiting, payload injection (OpenRouter's provider
`extra_body`), or SDK adaptation (Groq/Zai) is written once and every entry
point (`ask`, streaming, resuming a tool loop, `invoke`) picks it up
automatically. Before FEAT-438, `gpt.py` had near-duplicate wire-call sites
across these four entry points that could (and did) drift out of sync.

When adding a new override, always call `super()._chat_completion(...)` (or
otherwise preserve its `model`/`messages`/`use_tools`/`stream`/`**kwargs`
contract) unless you are fully replacing the wire call, as Groq/Zai do for
their native SDKs.

---

## The No-`gpt-*`-Defaults Rule

**`OpenAIBaseClient` and every direct subclass of it (i.e. everything except
`OpenAIClient` itself) MUST NOT set `_default_model`, `_fallback_model`, or
`_lightweight_model` to an OpenAI `gpt-*` id.** Leaving them unset (`None`)
is always safe — the resolution chains in `AbstractClient` fall through to
`self.model` (the model the caller actually configured) rather than
defaulting to OpenAI.

This is enforced by `tests/clients/test_openai_compatible_defaults.py`:
`test_openai_base_client_declares_no_model_defaults` asserts the base has
none of the three attributes set on the class itself, and a parametrized
`test_no_gpt_default_leak` / `test_invoke_chain_never_yields_gpt` /
`test_ask_payload_model_never_leaks_gpt` sweep runs the same assertion across
every wire subclass (`WIRE_SUBCLASSES` in that file).

---

## Adding a New OpenAI-Compatible Provider

1. **Subclass `OpenAIBaseClient`**, not `OpenAIClient`:

   ```python
   from .openai_base import OpenAIBaseClient

   class MyProviderClient(OpenAIBaseClient):
       client_type: str = "myprovider"
       client_name: str = "myprovider"
       # Only set these if MyProvider actually has a sensible one —
       # never an OpenAI gpt-* id:
       # _default_model: str = "myprovider/some-model"
       # _lightweight_model: str = "myprovider/small-model"

       def __init__(self, api_key: str | None = None, base_url: str | None = None, **kwargs):
           resolved_key = api_key or config.get("MYPROVIDER_API_KEY")
           super().__init__(
               api_key=resolved_key,
               base_url=base_url or "https://api.myprovider.com/v1",
               **kwargs,
           )
           # AbstractClient.__init__ only assigns self.api_key from kwargs
           # when 'api_key' is present — re-set explicitly if your class
           # needs to guarantee it (see the pattern in nvidia.py/openrouter.py).
           self.api_key = resolved_key
   ```

2. **Register it** in `LLMFactory.SUPPORTED_CLIENTS` (`factory.py`).

3. **Only override `get_client()`** if you need a non-`AsyncOpenAI` SDK
   (native Groq/Zai pattern) or extra client kwargs (OpenRouter's custom
   headers pattern).

4. **Only override `_chat_completion()`** if you need to inject payload
   data on every call (OpenRouter's `extra_body`) or adapt a native SDK
   (Groq/Zai). Always preserve or explicitly replace the
   `model`/`messages`/`use_tools`/`stream`/`**kwargs` contract.

5. **Only re-add a business-logic override** (`ask`, `ask_stream`, `invoke`,
   tool preparation, structured-output shaping, …) when it encodes real,
   provider-specific behavior — not to dodge OpenAI-specific behavior, since
   the base class has none. If you do add one, write a payload-parity test
   first (see `test_openai_base_parity.py`'s `WIRE_SUBCLASSES` roster) —
   parity divergence should be a deliberate, tested decision, never silent.

6. **Never set `_default_model`/`_fallback_model`/`_lightweight_model` to a
   `gpt-*` id.** Leave them unset unless you have a real model id for that
   provider.

7. **Add a smoke script** in `examples/clients/smoke/` (see below) and a doc
   page if the provider has enough provider-specific surface to warrant one
   (follow `docs/clients/bedrock-mantle.md`'s structure).

---

## Live Smoke Testing

`examples/clients/smoke/` holds one credential-gated script per endpoint
(`smoke_openai.py` is the positive control against `OpenAIClient` itself;
the rest cover the Phase-1/Phase-2 subclasses). Each script:

1. Skips cleanly (`SKIPPED (no <ENV_VAR>)`, exit 0) if its provider's
   credentials aren't set — safe on keyless machines and never wired into CI.
2. Otherwise constructs the client via `LLMFactory.create("provider:model")`
   inside `async with client:` (required — `AbstractClient` does not
   auto-enter its async context for `ask()`/`invoke()`, only `complete()`
   does) and runs three legs: plain `ask()`, `ask()` with one `@tool`
   registered, and `invoke()` — the last being the original 404 repro path
   this feature exists to prevent.
3. Prints a compact `PASS`/`FAIL`/`SKIPPED` summary per leg.

These are plain scripts, not pytest — run them manually:

```bash
python examples/clients/smoke/smoke_nvidia.py
```

**Worktree note**: if you run a smoke script directly (not via `pytest`)
from inside a `.claude/worktrees/<feature>/` checkout, `cd`-ing there is not
enough — this repo's editable install `.pth` entries point at the *main*
checkout's `packages/*/src`, so a bare `python script.py` will silently
import the main checkout's code. Prepend the worktree's own `src` dirs via
`PYTHONPATH`, and make sure the compiled Cython extensions
(`parrot/utils/types*.so`, etc.) exist under the worktree (copy them from the
main checkout if missing) before trusting smoke results as evidence about
worktree code.
