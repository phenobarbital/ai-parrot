---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: OpenAI-Compatible Client Base (OpenAIBaseClient)

**Date**: 2026-08-21
**Author**: Jesus
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

Every OpenAI-compatible provider client in `parrot/clients` — `OpenRouterClient`,
`MoonshotClient`, `NvidiaClient`, `LocalLLMClient` (→ `vLLMClient`), and
`BedrockMantleClient` — extends `OpenAIClient` (gpt.py:84) directly. `OpenAIClient`
is simultaneously two things:

1. The **OpenAI-compatible wire protocol** implementation (chat-completions call,
   tool-calling loop, message shaping, streaming, structured output, image
   encoding) — which subclasses want.
2. The **OpenAI-the-provider** client — hardcoded `gpt-*` model defaults
   (`_default_model="gpt-5-mini"`, `_fallback_model="gpt-5-nano"`,
   `_lightweight_model="gpt-4.1"`), the model deprecation registry, Responses-API
   routing (`o3`/`o3-pro`), deep-research routing, Sora video, strict-tools,
   implicit prompt caching — which subclasses inherit whether they want it or not.

The inherited OpenAI defaults leak into requests against non-OpenAI endpoints.
Observed failure (Bedrock Mantle hosting DeepSeek V3.2, via the inherited
`_lightweight_model="gpt-4.1"` on the `invoke()` fallback chain, base.py:1832):

```
[ERROR] 2026-08-21 13:12:05,446 DeepseekV32Agent.Agent(base.py:790) :: Error in
conversation: Error code: 404 - {'error': {'code': 'not_found_error', 'message':
"The model 'gpt-4.1' does not exist", 'param': None, 'type': 'invalid_request_error'}}
```

Two sibling symptoms were already patched as WIP (to be committed separately,
before this feature): tool schemas silently falling back to the Anthropic shape
for relabeled `client_type`s (fixed by an explicit `tool_format` attribute +
`_resolve_tool_format()`), and hardcoded `OpenAIModel.*` signature defaults in
`ask()`/`ask_stream()` overriding the configured model (fixed by `_resolve_model()`).
Those are tactical fixes; the structural problem — no clean place to inherit
"OpenAI-compatible" without inheriting "OpenAI" — remains, and it also causes
**duplication**: `GroqClient` (1424 lines) and `ZaiClient` (1024 lines) reimplement
the same wire protocol on `AbstractClient` because extending `OpenAIClient` was
never safe.

**Affected**: developers adding OpenAI-compatible providers, and end users of any
agent bound to Bedrock Mantle / Nvidia NIM / Moonshot / OpenRouter / local
endpoints who hit phantom `gpt-*` requests.

## Constraints & Requirements

- **No import breakage**: `from parrot.clients.gpt import OpenAIClient` and every
  existing subclass import path must keep working unchanged. New base lives in a
  new module.
- **No OpenAI defaults in the base**: `OpenAIBaseClient` must not declare
  `_default_model` / `_fallback_model` / `_lightweight_model` values. `None`
  means "fall back to `self.model`" via the existing chain (base.py:1832–1847).
- **Strict behavior parity per client**: every migrated client keeps its
  observable behavior (request payloads, tool format, params). Groq keeps
  `ToolFormat.GROQ` and never gets strict-tools.
- **The WIP (tool_format + _resolve_model + its regression tests) commits to
  `dev` first, as its own change** — this feature builds on top of it.
- Redesigned hooks are in scope (chosen over a purely mechanical extraction):
  the extraction should also fix known warts, chiefly that
  `OpenAIClient.ask_stream()` and `invoke()` call
  `client.chat.completions.create()` directly and bypass the overridden
  `_chat_completion()` (documented pain in moonshot.py:326/397 docstrings).
- Validation: per-client request-payload assertion tests (no network),
  a parametric "no `gpt-*` leak" test over every non-OpenAI subclass, and live
  smoke scripts under `examples/` (manual, credential-gated).
- Async-first, `uv`-managed environment, Google-style docstrings, type hints.

---

## Options Explored

### Option A: Neutralize defaults only (no new class)

Keep the current hierarchy. On top of the committed WIP, remove the model-default
leakage case by case: each subclass explicitly declares its own
`_default_model` / `_fallback_model` / `_lightweight_model` (or `None`), the text
helpers (`summarize_text`, `analyze_sentiment`, …) and media helpers switch their
`OpenAIModel.*` signature defaults to `None` + `_resolve_model()`, and a parametric
regression test enforces "no `gpt-*` in any non-OpenAI subclass".

✅ **Pros:**
- Smallest diff; nearly zero regression risk beyond the WIP itself.
- Fixes every *known* leak (the 404 class of bugs) quickly.

❌ **Cons:**
- The structural problem persists: the next OpenAI-only feature added to
  `OpenAIClient` (another Responses-API branch, another Sora helper) leaks to six
  subclasses by default. This is whack-a-mole.
- Does nothing about the ~2,400 duplicated wire-protocol lines in
  `GroqClient`/`ZaiClient`.
- "Is this method safe to inherit?" stays unanswerable without reading gpt.py
  (2,579 lines).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `openai` (SDK, already a dep) | wire calls | unchanged |
| `pytest` / `pytest-asyncio` | regression tests | already in use |

🔗 **Existing Code to Reuse:**
- `tests/clients/test_openai_compatible_defaults.py` — the WIP regression suite to extend.
- `packages/ai-parrot/src/parrot/clients/base.py:1832` — `_resolve_invoke_model` chain (already handles `None`).

---

### Option B: Extract `OpenAIBaseClient` with redesigned hooks (two-phase)

New module `packages/ai-parrot/src/parrot/clients/openai_base.py` with
`class OpenAIBaseClient(AbstractClient)` holding everything that means
"speaks the OpenAI wire protocol" and **nothing** that means "is OpenAI":

- **Moves in (generic wire)**: `get_client()` building `AsyncOpenAI(api_key,
  base_url, timeout)` with subclass-supplied config; `_chat_completion()` (the
  tenacity-wrapped `chat.completions.create/.parse` funnel, gpt.py:327);
  `ask()`/`ask_stream()`/`resume()`/`invoke()`/`batch_ask()` chat-completions
  paths, including the tool-calling loop currently inlined at gpt.py:947–1143 and
  duplicated at 1190–1257; `_encode_image_for_openai()`; `_upload_file()`;
  `_with_extra_body()`; `_resolve_model()`; `tool_format = ToolFormat.OPENAI`.
- **Stays in `OpenAIClient(OpenAIBaseClient)`** (gpt.py, same import path):
  `gpt-*` model defaults, `OpenAIModel` normalization/deprecation
  (`_normalize_model`), Responses-API routing (`_is_responses_model`,
  `_prepare_responses_args`, `_call_responses_*`, `_responses_completion`),
  deep-research routing, `generate_video` (Sora), Files download,
  `_apply_cache_hints` 1024-token threshold, `_is_capacity_error`'s
  `openai.RateLimitError` mapping, text/media helper model defaults.
- **Redesigned hooks** (the "with hooks" decision) on `OpenAIBaseClient`:
  - `_resolve_model(model) -> str` — explicit > configured > class default; calls
    `self._normalize_model()`, which is **identity in the base** and only does
    deprecation/alias work in `OpenAIClient`.
  - `_is_responses_model(model) -> bool` — returns `False` in the base (what
    localllm.py:118 already overrides to say); only `OpenAIClient` routes to the
    Responses API.
  - **Single completion funnel**: `ask_stream()` and `invoke()` are reworked to
    route through `_chat_completion()` so subclass overrides (Moonshot thinking
    params, Nvidia rate limiting/create-not-parse) apply everywhere, killing the
    documented bypass wart.
  - `supports_strict_tools: bool` / equivalent via `tool_format` — strict-tool
    wrapping applies only for `ToolFormat.OPENAI` (already in the WIP,
    base.py:1420).
  - No model attributes declared → `_default_model`/`_fallback_model`/
    `_lightweight_model` inherit `AbstractClient`'s `None` and the chain falls to
    `self.model`.
- **Phase 1**: create the base; rebase `OpenAIClient`, `OpenRouterClient`,
  `MoonshotClient`, `NvidiaClient`, `LocalLLMClient`/`vLLMClient`,
  `BedrockMantleClient` onto it. Several subclass overrides shrink or disappear
  (e.g. Moonshot's `ask_stream`/`invoke` overrides exist *only* because of the
  funnel bypass).
- **Phase 2 (same spec, later tasks)**: migrate `GroqClient` and `ZaiClient` onto
  `OpenAIBaseClient`, deleting their duplicated message shaping, tool loop, and
  structured-output builders under strict payload-parity tests. `GrokClient` is
  **excluded** — it is not an OpenAI-wire client (xai_sdk stateful
  `chat.sample()`/`chat.parse()`, no chat-completions payloads); see Open
  Questions.

✅ **Pros:**
- Solves the class-conflict problem at the root: "OpenAI-compatible" becomes an
  inheritable contract with zero OpenAI residue; new providers subclass the base
  and declare `base_url` + env vars + defaults, nothing else.
- Fixes the `_chat_completion` bypass wart for every subclass at once.
- Phase 2 deletes ~2,000+ lines of duplicated wire logic in Groq/Zai.
- Import paths untouched; `factory.py` untouched (classes keep their names).
- Existing per-client test suites (nvidia 769 L, vllm 748 L, moonshot 13 classes,
  openrouter 257 L, mantle 241 L, groq, zai) act as the parity harness.

❌ **Cons:**
- Large, delicate refactor of a 2,579-line hot module; the tool-calling loop
  extraction (947–1143 + 1190–1257) must preserve exact semantics (lazy tools,
  fallback flags, usage accumulation).
- Groq/Zai migration changes their SDK usage (`AsyncGroq` / official `zai` SDK →
  `AsyncOpenAI` with `base_url`) — parity must be proven, and SDK-specific
  behaviors (Groq SDK retry semantics, Zai thinking payloads) re-expressed as
  hooks.
- Two-phase scope means a longer-lived feature branch.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `openai` ≥1.x (already a dep) | `AsyncOpenAI(base_url=…)` for all wire clients | already how Mantle/NIM/Moonshot/OpenRouter/LocalLLM run |
| `tenacity` (already a dep) | retry in `_chat_completion` | moves with the method |
| `pytest` / `pytest-asyncio` | parity + leak tests | already in use |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/clients/gpt.py` — source of every extracted method (see Code Context).
- `packages/ai-parrot/src/parrot/clients/base.py:1364,1388,1294,2557,2604` — `_resolve_tool_format`, `_prepare_tools`, `_make_openai_strict_tool`, `_oai_normalize_schema`, `_build_response_format_from` (stay on `AbstractClient`; already generic entry points).
- `tests/clients/test_openai_compatible_defaults.py` — seed of the no-leak parametric suite.
- `packages/ai-parrot/tests/test_nvidia_client.py`, `test_vllm_client.py`, `tests/clients/test_moonshot_client.py`, `packages/ai-parrot/tests/clients/test_bedrock_mantle.py`, etc. — parity harness.

---

### Option C: Composition — extract an `OpenAIWireCodec` strategy object (unconventional)

Instead of an inheritance layer, extract the wire protocol into a standalone,
stateless codec/strategy class (`OpenAIWireCodec`: build request payload, shape
tools, parse response → `AIMessage`, accumulate stream deltas, drive the
tool-call loop as a pure async function over an injected transport). Clients keep
extending `AbstractClient` and *compose* the codec; `OpenAIClient` becomes a thin
provider shell around it, and Groq/Zai adopt the codec without changing their
class ancestry or SDKs (the codec is SDK-agnostic — it produces/consumes dicts).

✅ **Pros:**
- The codec is unit-testable in isolation (pure payload in/out — the strongest
  possible payload-parity story).
- Groq/Zai could keep their native SDKs and still delete duplicated shaping code.
- No deep inheritance; provider quirks become codec parameters, not overrides.

❌ **Cons:**
- Foreign to the codebase idiom — every client today is inheritance-based
  (`AbstractClient` → provider), and `AbstractClient` itself owns conversation
  memory, tool manager, fallback logic that the codec would need injected back.
- Highest effort and the largest conceptual diff for reviewers; touches
  `AbstractClient` significantly.
- Doesn't by itself remove the `gpt-*` defaults problem — subclasses would still
  inherit `OpenAIClient`'s attributes unless the hierarchy *also* changes, at
  which point you've done Option B too.

📊 **Effort:** High (higher than B)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | pure refactor |

🔗 **Existing Code to Reuse:**
- Same inventory as Option B, plus `parrot/tools/manager.py:47` `ToolFormat` / `ToolSchemaAdapter` as the model for a format-parameterized codec.

---

## Recommendation

**Option B** is recommended.

Option A treats symptoms and guarantees this class of bug recurs — the user has
already been bitten three separate ways (lightweight-model 404, Anthropic-shaped
tools, signature-default model override) in one week. Option C offers the purest
testing story but fights the framework's inheritance idiom, requires invasive
`AbstractClient` surgery, and still needs B's hierarchy change to kill the
defaults leak — it is B plus extra risk. Option B matches the user's own design
instinct (an abstract "OpenAI-compatible" layer with wire protocol + tool/message
shaping only), keeps every import path stable, converts the documented
`_chat_completion` bypass wart into a designed-in funnel, and opens the door to
deleting the Groq/Zai duplication. What we trade off: a longer-lived branch and
careful parity work on the extracted tool loop — mitigated by phasing (hierarchy
first, Groq/Zai second) and by the strict per-client payload-parity test gate.

---

## Feature Description

### User-Facing Behavior

- Agents bound to Bedrock Mantle, Nvidia NIM, Moonshot, OpenRouter, LocalLLM/vLLM
  never emit `gpt-*` model ids unless explicitly configured to: the DeepSeek V3.2
  404 class of failure becomes impossible by construction.
- `from parrot.clients.gpt import OpenAIClient` and all subclass imports, plus
  every `LLMFactory` provider key (`"bedrock-mantle:…"`, `"nvidia:…"`, …), work
  exactly as before. Zero config or call-site changes for downstream users.
- New provider integrations become declarative: subclass `OpenAIBaseClient`,
  set `client_type`, `base_url`, env-var lookups, and model defaults — done.

### Internal Behavior

- `parrot/clients/openai_base.py` hosts `OpenAIBaseClient(AbstractClient)`:
  SDK construction (`AsyncOpenAI` with injected `base_url`/`api_key`/timeout),
  the single `_chat_completion()` funnel (every completion path — `ask`,
  `ask_stream`, `resume`, `invoke` — routes through it), the extracted
  tool-calling loop (shared by `ask` and `resume` instead of today's duplicate),
  message shaping, streaming accumulation, structured-output wiring,
  `_encode_image_for_openai`, `_upload_file`, `batch_ask`, `_with_extra_body`,
  `_resolve_model`, and `tool_format = ToolFormat.OPENAI`. It declares **no**
  model defaults and an identity `_normalize_model`.
- `OpenAIClient(OpenAIBaseClient)` retains: `gpt-*` defaults, deprecation/alias
  normalization, Responses-API + deep-research routing (via the
  `_is_responses_model` hook, `False` in the base), Sora video, OpenAI Files
  download, prompt-cache hints, OpenAI-typed capacity-error detection, and the
  `OpenAIModel`-defaulted convenience helpers.
- Phase-1 rebase: the six existing subclasses change their base class to
  `OpenAIBaseClient` and *lose* overrides that existed only to dodge OpenAI
  behavior (LocalLLM's `_is_responses_model`, Moonshot's `ask_stream`/`invoke`
  bypass workarounds); overrides that encode real provider behavior (Nvidia rate
  limiter, Moonshot thinking params, OpenRouter extra_body) remain.
- Phase-2 migration: `GroqClient` and `ZaiClient` become `OpenAIBaseClient`
  subclasses, dropping bespoke shaping/tool-loop/structured-output code; Groq
  keeps `ToolFormat.GROQ` (no strict tools), Zai's thinking payload and usage
  extraction become subclass hooks. `GrokClient` stays on `AbstractClient`.

### Edge Cases & Error Handling

- **No model anywhere**: base with `model=None` and no defaults must fail fast
  with a clear `ValueError` at call time ("no model configured"), not send
  `model=None` over the wire.
- **`_lightweight_model` unset** (all non-OpenAI subclasses): `invoke()` uses
  `self.model` (existing chain base.py:1832) — verified by the leak test.
- **Fallback model**: `_should_use_fallback` only fires when the subclass
  declares `_fallback_model` (Mantle: `google.gemma-4-26b-a4b`; the
  base.py:350 `__init__` shadowing gotcha that mantle.py:104 guards against must
  be resolved in the base, not per-subclass).
- **Capacity errors**: the base detects generic HTTP 429/5xx via the `openai` SDK
  exception types (all wire subclasses use that SDK); provider-specific extras
  (Nvidia's `NvidiaRateLimitError`) stay in subclasses via the existing
  `_is_capacity_error` hook.
- **Streaming tool calls**: stream accumulation must keep yielding the final
  `AIMessage` (TASK-1175 contract).
- **Parity breaks in Phase 2**: any Groq/Zai payload divergence found by the
  parity tests blocks the migration task — the client stays on its native SDK
  until resolved (never silently normalized).

---

## Capabilities

### New Capabilities
- `openai-compatible-clients`: an `OpenAIBaseClient` abstract layer providing the
  OpenAI wire protocol (chat completions, tool-calling loop, streaming, message/
  tool shaping, structured output) with zero OpenAI-provider defaults, plus the
  migration of all OpenAI-compatible clients onto it.

### Modified Capabilities
- `bedrock-mantle-client` — `BedrockMantleClient` rebases onto `OpenAIBaseClient`.
- `nvidia-client` — same rebase; `_chat_completion` funnel now covers streams/invoke.
- `moonshot-client-llm` — same rebase; bypass-workaround overrides removed.
- `openrouter-client` — same rebase.
- `localllm-client` — same rebase (drops `_is_responses_model` override).
- (Phase 2) Groq / Zai client behavior contracts re-anchored on the base.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/clients/openai_base.py` | **new** | `OpenAIBaseClient(AbstractClient)` |
| `parrot/clients/gpt.py` | modifies | `OpenAIClient(OpenAIBaseClient)`; shrinks to OpenAI-only concerns; import path preserved |
| `parrot/clients/{openrouter,moonshot,nvidia,localllm,vllm}.py`, `nova/mantle.py` | modifies | base-class swap + override cleanup |
| `parrot/clients/{groq,zai}.py` | modifies (Phase 2) | rebase onto `OpenAIBaseClient`, delete duplicated wire code |
| `parrot/clients/grok.py` | none | stays on `AbstractClient` (xai_sdk, not OpenAI wire) |
| `parrot/clients/base.py` | minor | `tool_format`/`_resolve_tool_format` (from WIP) unchanged; possibly move the `_fallback_model` `__init__` shadowing fix (line 350) here |
| `parrot/clients/factory.py` | none | class names/keys unchanged |
| `parrot/clients/__init__.py` | extends | export `OpenAIBaseClient` |
| tests (`packages/ai-parrot/tests/`, `tests/clients/`, `tests/unit/`) | extends | parity suites + parametric no-leak test |
| `examples/` | extends | live smoke scripts per endpoint (credential-gated) |
| Breaking changes | none intended | MRO changes visible only to code doing `isinstance(x, OpenAIClient)` on non-OpenAI clients — audit needed (Open Question) |

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (runtime error log, 2026-08-21 — DeepSeek V3.2 agent on Bedrock Mantle)
# [ERROR] 2026-08-21 13:12:05,446 DeepseekV32Agent.Agent(base.py:790) :: Error in
# conversation: Error code: 404 - {'error': {'code': 'not_found_error', 'message':
# "The model 'gpt-4.1' does not exist", 'param': None, 'type': 'invalid_request_error'}}
```

### Verified Codebase References

All verified against the working tree on 2026-08-21 (branch `dev`, including the
uncommitted WIP in `base.py`/`gpt.py` that will be committed before this feature).
Paths relative to `packages/ai-parrot/src/parrot/` unless noted.

#### Classes & Signatures

```python
# From clients/gpt.py:84 (2579 lines total)
class OpenAIClient(AbstractClient):
    client_type: str = "openai"                              # :87
    tool_format: ToolFormat = ToolFormat.OPENAI              # :91 (WIP)
    model: str = OpenAIModel.GPT5_MINI.value                 # :92
    client_name: str = "openai"                              # :93
    _default_model: str = "gpt-5-mini"                       # :94
    _fallback_model: str = "gpt-5-nano"                      # :95
    _lightweight_model: str = "gpt-4.1"                      # :96  ← the 404 culprit
    _min_cache_tokens: int = 1024                            # :98

    def __init__(self, api_key: str = None, base_url: str = "https://api.openai.com/v1", **kwargs):  # :100
    def _resolve_model(self, model: Union[str, OpenAIModel, None]) -> str:  # :108 (WIP)
    def _normalize_model(self, model: Union[str, OpenAIModel]) -> str:      # :126 (deprecation/alias — OpenAI-only)
    async def get_client(self) -> "AsyncOpenAI":                            # :230 (AsyncOpenAI(api_key, base_url, timeout=OPENAI_TIMEOUT))
    async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, **kwargs):  # :327 (tenacity retry; create/.parse)
    def _is_responses_model(self, model_str: str) -> bool:                   # :344 (o3/o3-pro — OpenAI-only)
    async def ask(self, prompt, model: Union[str, OpenAIModel, None] = None, ...) -> AIMessage:  # :693
    async def resume(self, session_id, user_input, state) -> AIMessage:      # :1161
    async def ask_stream(self, prompt, model=None, ...) -> AsyncIterator[Union[str, AIMessage]]:  # :1283
    async def batch_ask(self, requests) -> List[AIMessage]:                  # :1642
    def _encode_image_for_openai(self, image, low_quality=False) -> Dict[str, Any]:  # :1652
    async def invoke(self, prompt, *, model=None, ...) -> InvokeResult:      # :2494
    # Tool loop INLINED: ask() :947–1143; duplicated in resume() :1190–1257
    # Responses API: _prepare_responses_args :365, _call_responses_create :522,
    #   _call_responses_stream :555, _responses_completion :585 — OpenAI-only
    # Deep research: _resolve_deep_research_model :351 — OpenAI-only
    # Sora: generate_video :2349 — OpenAI-only
    # Text helpers with OpenAIModel.GPT5_MINI signature defaults:
    #   summarize_text :1819, translate_text :1869, extract_key_points :1928,
    #   analyze_sentiment :1973, analyze_product_review :2019
    # ask_to_image :1690 (default GPT5_MINI), image_identification :2086 (default GPT4_1_MINI)
```

```python
# From clients/base.py:250 (2645 lines total)
class AbstractClient(EventEmitterMixin, ABC):
    client_type: str = "generic"                     # :256
    tool_format: Optional[ToolFormat] = None         # :268 (WIP)
    _lightweight_model: Optional[str] = None         # :272 (None → falls to self.model)
    _min_cache_tokens: int = 0                       # :278
    # __init__: self._fallback_model = kwargs.get('fallback_model', None)  # :350 ← SHADOWS class attr (mantle.py:104 guards)

    def _make_openai_strict_tool(self, schema: Dict[str, Any]) -> Dict[str, Any]:  # :1294 (on AbstractClient, NOT OpenAIClient)
    def _resolve_tool_format(self) -> ToolFormat:    # :1364 (WIP; explicit tool_format wins, else client_type map, else ANTHROPIC)
    def _prepare_tools(self, filter_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:  # :1388
    #   :1411 `if provider_format in (ToolFormat.OPENAI, ToolFormat.GROQ):` → function wrapper
    #   :1420 strict-tools applied ONLY for ToolFormat.OPENAI (Groq rejects it)
    def _resolve_invoke_model(self, model: Optional[str] = None) -> str:  # :1832
    #   chain: explicit model > _lightweight_model > self.model  (:1841/:1845/:1847)
    async def _prepare_conversation_context(self, prompt, files, user_id, session_id,
        system_prompt, stateless: bool = False): # :1976 (shared message-context builder)
    def _oai_normalize_schema(self, schema: dict, *, force_required_all: bool = True) -> dict:  # :2557
    def _build_response_format_from(self, output_config):  # :2604 (OpenAI response_format builder — already on the generic base)
    # Abstract: get_client :946, ask :1644, ask_stream :1682, resume :1711, invoke :1733
    @property
    def default_model(self) -> str:  # :906 → getattr(self, '_default_model', None)
```

```python
# Subclass override inventory (working tree):
# clients/openrouter.py:26  class OpenRouterClient(OpenAIClient)  (200 L)
#   client_type/client_name "openrouter" :52-53; _default_model = OpenRouterModel.DEEPSEEK_R1.value :54
#   overrides __init__ :56 (base_url https://openrouter.ai/api/v1, OPENROUTER_API_KEY),
#   get_client :80, _chat_completion :116 (delegates super + extra_body)
# clients/moonshot.py:88  class MoonshotClient(OpenAIClient)  (440 L)
#   _default_model KIMI_K2_6 :131, _fallback_model MOONSHOT_V1_128K :132, _min_cache_tokens 0 :133
#   overrides _chat_completion :201, ask :282, ask_stream :326, invoke :397
#   ask_stream/invoke overrides exist ONLY because OpenAIClient bypasses _chat_completion there (docstrings say so)
# clients/nvidia.py:207  class NvidiaClient(OpenAIClient)  (602 L)
#   _default_model MINIMAX_M3 :269; overrides __init__ :271 (NIM base_url, NVIDIA_API_KEY, rate limiter),
#   _chat_completion :407 ("NIM rejects .parse()"), ask :473, ask_stream :527
# clients/localllm.py:25  class LocalLLMClient(OpenAIClient)  (381 L)
#   _lightweight_model = None :64 (manual leak fix), _default_model "llama3.1:8b" :65
#   overrides get_client :96, _is_responses_model :118 (always False), ask :132, ask_stream :157, invoke :211
# clients/vllm.py:35  class vLLMClient(LocalLLMClient)  (461 L) — guided_json/regex/choice params; os.getenv (not navconfig)
# clients/nova/mantle.py:29  class BedrockMantleClient(OpenAIClient)  (128 L)
#   _default_model "openai.gpt-oss-120b" :81, _fallback_model "google.gemma-4-26b-a4b" :82
#   overrides ONLY __init__ :84; kwargs.setdefault("fallback_model", ...) :104 guards base.py:350 shadowing
```

```python
# Standalone OpenAI-compatible clients (Phase 2 targets):
# clients/groq.py:49  class GroqClient(AbstractClient)  (1424 L) — SDK: groq.AsyncGroq (:81; base_url stored but NOT passed to SDK :88)
#   _lightweight_model "kimi-k2-instruct" :63; bespoke _prepare_groq_tools :195, _prepare_structured_output_format :227,
#   full reimplemented ask :270 / ask_stream :678 / resume :819 / invoke :1293
# clients/zai.py:22  class ZaiClient(AbstractClient)  (1024 L) — SDK: official `zai` SDK (:56)
#   _lightweight_model GLM_4_5_FLASH_FREE :29; reimplements message shaping :73–131, tools :132,
#   response→AIMessage :204–283, tool loop :288–349, stream accumulation :511
# clients/grok.py:53  class GrokClient(AbstractClient)  (774 L) — SDK: xai_sdk.AsyncClient (:93)
#   NOT OpenAI wire: stateful chat.sample()/chat.parse(); EXCLUDED from migration
```

```python
# From tools/manager.py:47
class ToolFormat(Enum):
    OPENAI = "openai"; ANTHROPIC = "anthropic"; GOOGLE = "google"
    GROQ = "groq"; VERTEX = "vertex"; GENERIC = "generic"; BEDROCK = "bedrock"
```

```python
# From clients/factory.py — SUPPORTED_CLIENTS :107–149 (keys unchanged by this feature);
# lazy-loader resolution :242-243; LLMFactory.parse_llm_string :171 ("provider:model" split :187);
# LLMFactory.create :193 (init_params['model'] = model :250)
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.clients.gpt import OpenAIClient           # clients/gpt.py:84
from parrot.clients.base import AbstractClient        # clients/base.py:250
from parrot.clients.nova.mantle import BedrockMantleClient  # clients/nova/mantle.py:29 (lazy in factory.py:64)
from parrot.tools.manager import ToolFormat           # tools/manager.py:47
from parrot.models.openai import OpenAIModel, is_deprecated, get_shutoff_date, resolve_alias  # models/openai.py:17,171,193,215
```

#### Key Attributes & Constants
- `OpenAIClient._lightweight_model` → `"gpt-4.1"` (clients/gpt.py:96) — the leak this feature eliminates.
- `AbstractClient._resolve_invoke_model` chain (clients/base.py:1832–1847) — already `None`-safe; no change needed for the "None → self.model" decision.
- `RESPONSES_ONLY_MODELS = {"o3", "o3-pro"}` (clients/gpt.py:50) — stays OpenAI-only.
- `STRUCTURED_OUTPUT_COMPATIBLE_MODELS` (clients/gpt.py:55–80) — OpenAI-only model gate; base must not consult it.
- Existing test harness: `packages/ai-parrot/tests/test_{nvidia,vllm,localllm,openrouter,groq,grok,zai,openai}_client.py`, `tests/clients/test_moonshot_client.py`, `packages/ai-parrot/tests/clients/test_bedrock_mantle.py`, `tests/unit/test_*_invoke.py`, and the untracked WIP suite `tests/clients/test_openai_compatible_defaults.py` (118 L).

### Does NOT Exist (Anti-Hallucination)
- ~~`OpenAIBaseClient` / `OpenAICompatibleClient`~~ — no such class anywhere yet (grep: zero matches); this feature creates it.
- ~~`parrot/clients/openai_base.py` / `openai_compatible.py`~~ — module does not exist yet.
- ~~`OpenAIClient.embed()`~~ — no embedding method anywhere in gpt.py; `AbstractClient` has no `embed` abstract method (`ZaiClient.embed` exists but only raises `NotImplementedError`, zai.py:1022).
- ~~a dedicated message-shaping method on `OpenAIClient`~~ (`_build_messages`, `_to_openai_messages`…) — message construction is **inline** in `ask()`/`ask_stream()`; only `AbstractClient._prepare_conversation_context()` (base.py:1976) is shared.
- ~~`OpenAIClient._make_openai_strict_tool`~~ — lives on `AbstractClient` (base.py:1294), not on `OpenAIClient`.
- ~~`ToolFormat.OPENAI_COMPATIBLE` / `.XAI` / `.ZAI` / `.MOONSHOT` / `.NVIDIA`~~ — only the 7 members listed above.
- ~~`client_type == "openai-compatible"` factory key~~ — not in `SUPPORTED_CLIENTS`.
- ~~`tool_format` declarations on the subclasses~~ — only gpt.py:91 declares it; all six wire subclasses inherit it (Groq/Grok/Zai declare none).
- ~~`test_gpt.py` / package-level per-client tests for groq/zai in `packages/ai-parrot/tests/clients/`~~ — per-client suites live in `packages/ai-parrot/tests/` and repo-root `tests/` instead (paths above).
- ~~`GrokClient` speaking OpenAI wire~~ — it uses `xai_sdk.AsyncClient` stateful `chat.sample()`/`chat.parse()`; treating it as OpenAI-compatible would be wrong.

---

## Parallelism Assessment

- **Internal parallelism**: Low. Phase 1 is a serialized chain (create base →
  rebase `OpenAIClient` → rebase subclasses → parity/leak tests); every task
  touches `openai_base.py`/`gpt.py`. Phase-2 tasks (Groq, Zai) are independent of
  each other but both depend on the finished Phase-1 base.
- **Cross-feature independence**: One overlap — FEAT-437
  (claude-bedrock-sample-agents, TASK-2293–2295 still in `sdd/tasks/active/`)
  exercises `BedrockMantleClient` from `examples/agents/aws/` and is the feature
  that surfaced the 404; the pre-committed WIP also touches
  `examples/agents/aws/agent_claude_haiku45.py`. Coordinate merge order. No other
  in-flight spec touches `parrot/clients/`.
- **Recommended isolation**: `per-spec` — one worktree, sequential tasks.
- **Rationale**: shared hot files (`gpt.py`, new `openai_base.py`) make parallel
  worktrees conflict-prone; strict-parity verification is easier when each rebase
  lands on the previous one's green test suite.

---

## Open Questions

- [x] Should the WIP (tool_format + _resolve_model + regression tests) land before this feature? — *Owner: Jesus*: Yes — commit to `dev` as its own change first; this feature builds on top of it.
- [x] Do Groq/Zai migrate onto the new base? — *Owner: Jesus*: Yes (Phase 2), under strict payload-parity tests; Groq keeps `ToolFormat.GROQ` and no strict tools.
- [x] Model defaults on the base when a subclass declares none? — *Owner: Jesus*: `None` → existing chain falls back to `self.model` (base.py:1832).
- [ ] `GrokClient` disposition: it is NOT an OpenAI-wire client (xai_sdk stateful API). Confirm it is excluded from the migration, or decide to rewrite it against xAI's OpenAI-compatible REST endpoint (a behavior change: loses `chat.parse()` SDK-native structured output) — *Owner: Jesus*
- [ ] Phase-2 SDK swap: migrating Groq (`AsyncGroq`) and Zai (official `zai` SDK) onto `AsyncOpenAI(base_url=…)` drops those SDK dependencies for these clients. Acceptable, or must native SDKs be retained behind the base's `get_client()` hook? — *Owner: Jesus*
- [ ] `isinstance(x, OpenAIClient)` audit: after the rebase, non-OpenAI clients will no longer be instances of `OpenAIClient`. Grep the repo (and known downstream consumers) for isinstance/issubclass checks against `OpenAIClient` and decide whether any must switch to `OpenAIBaseClient` — *Owner: implementer (spec task)*
- [ ] Do the OpenAI-shaped helpers already on `AbstractClient` (`_make_openai_strict_tool` :1294, `_oai_normalize_schema` :2557, `_build_response_format_from` :2604) stay there (they're called from generic paths like `_prepare_tools`/`invoke` on all providers) or move down to `OpenAIBaseClient`? Default: stay, to keep the diff mechanical — *Owner: Jesus*
- [ ] Fix the `_fallback_model` constructor-shadowing gotcha (base.py:350 overwrites class attrs with `None`; mantle.py:104 works around it) in `AbstractClient` itself as part of Phase 1? — *Owner: Jesus*
- [ ] Live smoke scripts: which endpoints get one under `examples/` (Mantle, NIM, Groq, Moonshot, OpenRouter, local vLLM?) and what credentials/env gating convention (skip-if-no-key)? — *Owner: Jesus*
