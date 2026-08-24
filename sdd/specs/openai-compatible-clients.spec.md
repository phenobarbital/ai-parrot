---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: OpenAI-Compatible Client Base (OpenAIBaseClient)

**Feature ID**: FEAT-438
**Date**: 2026-08-21
**Author**: Jesus
**Status**: approved
**Target version**: next minor
**Brainstorm**: `sdd/proposals/openai-compatible-clients.brainstorm.md` (Option B accepted)

---

## 1. Motivation & Business Requirements

### Problem Statement

Every OpenAI-compatible provider client in `parrot/clients` — `OpenRouterClient`,
`MoonshotClient`, `NvidiaClient`, `LocalLLMClient` (→ `vLLMClient`), and
`BedrockMantleClient` — extends `OpenAIClient` (gpt.py:84) directly.
`OpenAIClient` is simultaneously the **OpenAI wire protocol** implementation
(chat-completions call, tool-calling loop, message shaping, streaming,
structured output) that subclasses want, and the **OpenAI-the-provider** client
(hardcoded `gpt-*` defaults, deprecation registry, Responses-API/deep-research
routing, Sora, strict tools, prompt-cache heuristics) that they inherit whether
they want it or not.

Observed production failure — Bedrock Mantle hosting DeepSeek V3.2 receives the
inherited `_lightweight_model="gpt-4.1"` through the `invoke()` fallback chain
(base.py:1832):

```
[ERROR] 2026-08-21 13:12:05,446 DeepseekV32Agent.Agent(base.py:790) :: Error in
conversation: Error code: 404 - {'error': {'code': 'not_found_error', 'message':
"The model 'gpt-4.1' does not exist", 'param': None, 'type': 'invalid_request_error'}}
```

Two sibling symptoms (Anthropic-shaped tool schemas on relabeled `client_type`s;
`OpenAIModel.*` signature defaults overriding the configured model) were fixed
tactically and are already on `dev` (commit `ab84ffff0`: `tool_format` +
`_resolve_tool_format()` + `_resolve_model()` + regression suite
`tests/clients/test_openai_compatible_defaults.py`). The structural problem —
no way to inherit "OpenAI-compatible" without inheriting "OpenAI" — remains,
and it also forces duplication: `GroqClient` (1,424 lines) and `ZaiClient`
(1,024 lines) reimplement the same wire logic on `AbstractClient` because
extending `OpenAIClient` was never safe.

### Goals

- G1: Introduce `OpenAIBaseClient(AbstractClient)` in a new module
  `parrot/clients/openai_base.py` holding the OpenAI wire protocol with
  **zero** OpenAI-provider defaults (no `gpt-*` anywhere; no
  `_default_model`/`_fallback_model`/`_lightweight_model` values — `None`
  falls through to `self.model` via the existing chain, base.py:1832–1847).
- G2: Rebase `OpenAIClient` and its six wire subclasses onto the new base with
  **strict behavior parity** (request payloads, tool formats, params
  unchanged), keeping every existing import path working
  (`from parrot.clients.gpt import OpenAIClient`, factory keys untouched).
- G3: Make `_chat_completion()` the **single completion funnel**: `ask()`,
  `ask_stream()`, `resume()`, and `invoke()` all route through it, eliminating
  the documented bypass wart (moonshot.py:326/397 docstrings) so subclass
  overrides (Moonshot thinking params, Nvidia rate limiting) apply everywhere.
- G4: Phase 2 — rebase `GroqClient` and `ZaiClient` onto `OpenAIBaseClient`,
  deleting their duplicated message shaping / tool loop / structured-output
  code, **keeping their native SDKs** (`groq.AsyncGroq`, official `zai` SDK)
  behind the `get_client()` / completion-funnel hooks. Groq keeps
  `ToolFormat.GROQ` and never receives strict tools.
- G5: Fix the `_fallback_model` constructor-shadowing gotcha in
  `AbstractClient.__init__` (base.py:350 overwrites the class attribute with
  `None`); remove the per-subclass workaround (mantle.py:104).
- G6: Enforce the contract with tests: per-client request-payload parity tests
  (no network), a parametric "no `gpt-*` leak" test over every non-OpenAI
  subclass, and credential-gated live smoke scripts under `examples/`.

### Non-Goals (explicitly out of scope)

- **`GrokClient` migration** — it is NOT an OpenAI-wire client (xai_sdk
  stateful `chat.sample()`/`chat.parse()`, grok.py:53/90). It stays on
  `AbstractClient` unchanged. (Resolved at spec time; a future rewrite against
  xAI's OpenAI-compatible REST endpoint would be its own feature.)
- Replacing Groq/Zai native SDKs with `AsyncOpenAI` — explicitly rejected at
  spec time in favor of keeping native SDKs behind hooks.
- A composition/codec architecture (brainstorm Option C rejected — see
  `sdd/proposals/openai-compatible-clients.brainstorm.md`).
- Symptom-only default neutralization without a base class (brainstorm
  Option A rejected).
- Any change to `AnthropicClient`, `BedrockConverseClient`, `GoogleGenAIClient`,
  `Gemma4Client`, `NovaClient`, `ClaudeAgentClient`, `OpenAICodexClient`.
- New `ToolFormat` members or factory keys.
- An `embed()` surface (none exists on `OpenAIClient` today; not added here).

---

## 2. Architectural Design

### Overview

Insert one abstract layer between `AbstractClient` and every OpenAI-wire
client:

- **`OpenAIBaseClient(AbstractClient)`** (`parrot/clients/openai_base.py`, new)
  owns: SDK-client construction hook (`get_client()` returning an
  `AsyncOpenAI`-shaped client built from subclass-supplied
  `base_url`/`api_key`/timeout), the tenacity-wrapped `_chat_completion()`
  funnel, the extracted tool-calling loop (single implementation shared by
  `ask()` and `resume()`, replacing today's duplicate at gpt.py:947–1143 and
  1190–1257), chat-completions message shaping, stream accumulation (final
  `AIMessage` yield preserved — TASK-1175 contract), `invoke()`, `batch_ask()`,
  `_encode_image_for_openai()`, `_upload_file()`, `_with_extra_body()`,
  `_resolve_model()`, and `tool_format = ToolFormat.OPENAI`.
  It declares **no model attributes** — `_default_model`/`_fallback_model`/
  `_lightweight_model` stay `None` (inherited from `AbstractClient`) so the
  invoke chain resolves to `self.model`. Hooks with neutral base behavior:
  `_normalize_model()` = identity; `_is_responses_model()` = `False`.
- **`OpenAIClient(OpenAIBaseClient)`** (gpt.py, same import path) retains
  everything OpenAI-only: `gpt-*` defaults (`gpt-5-mini`/`gpt-5-nano`/
  `gpt-4.1`), `OpenAIModel` deprecation/alias normalization, Responses-API
  routing (`RESPONSES_ONLY_MODELS`, `_prepare_responses_args`,
  `_call_responses_*`, `_responses_completion`), deep-research routing,
  `generate_video` (Sora), OpenAI Files download, `_min_cache_tokens = 1024`
  cache hints, `openai.RateLimitError`-typed capacity detection, and the
  `OpenAIModel`-defaulted text/media convenience helpers.
- **Phase-1 rebase**: `OpenRouterClient`, `MoonshotClient`, `NvidiaClient`,
  `LocalLLMClient` (→ `vLLMClient`), `BedrockMantleClient` change their base
  class to `OpenAIBaseClient`. Overrides that existed only to dodge OpenAI
  behavior are deleted (LocalLLM's `_is_responses_model`; Moonshot's
  `ask_stream`/`invoke` bypass workarounds); overrides encoding real provider
  behavior remain (Nvidia rate limiter + create-not-parse, Moonshot thinking
  params + K-series guards, OpenRouter extra_body, vLLM guided outputs).
- **Phase-2 rebase**: `GroqClient` and `ZaiClient` become `OpenAIBaseClient`
  subclasses. Their native SDKs stay: `get_client()` returns `AsyncGroq` /
  official `zai` client; the completion funnel is the adaptation seam
  (`AsyncGroq` already mirrors the OpenAI SDK's `chat.completions.create`
  surface; Zai overrides the funnel/stream seam to adapt its SDK). Their
  bespoke shaping/tool-loop/structured-output code
  (`_prepare_groq_tools`, `_prepare_structured_output_format`,
  `_normalize_messages`, `_run_tool_loop`, `_accumulate_stream_tool_calls`,
  etc.) is deleted in favor of the shared implementations, gated by
  payload-parity tests. Any parity divergence blocks that client's migration
  task — never silently normalized.
- **Shadowing fix (Phase 1)**: `AbstractClient.__init__` only assigns
  `self._fallback_model` when `fallback_model` is explicitly passed, so class
  attributes survive; mantle.py:104's `kwargs.setdefault` workaround is
  removed.

Decisions carried from the brainstorm (do not re-open): the tactical WIP landed
first as its own commit (`ab84ffff0` on `dev`); Groq/Zai migrate in Phase 2
under strict parity; unset model attributes mean `None` → `self.model`.

### Component Diagram

```
AbstractClient (base.py)                     [+ shadowing fix G5]
   ├── OpenAIBaseClient (openai_base.py)     [NEW — wire protocol, no OpenAI defaults]
   │      ├── OpenAIClient (gpt.py)          [OpenAI-only: gpt-*, Responses, Sora…]
   │      ├── OpenRouterClient
   │      ├── MoonshotClient                 [drops ask_stream/invoke bypass overrides]
   │      ├── NvidiaClient
   │      ├── LocalLLMClient ── vLLMClient   [drops _is_responses_model override]
   │      ├── BedrockMantleClient            [drops fallback_model workaround]
   │      ├── GroqClient   (Phase 2, keeps AsyncGroq SDK)
   │      └── ZaiClient    (Phase 2, keeps zai SDK)
   ├── GrokClient                            [UNCHANGED — xai_sdk, not OpenAI wire]
   ├── AnthropicClient / BedrockConverseClient / GoogleGenAIClient / …  [unchanged]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractClient` (base.py:250) | extends | new base subclasses it; G5 touches its `__init__` (:350) |
| `AbstractClient._prepare_tools` / `_resolve_tool_format` (base.py:1388/1364) | uses | unchanged; base declares `tool_format = ToolFormat.OPENAI` |
| `AbstractClient._resolve_invoke_model` (base.py:1832) | uses | already `None`-safe; the no-defaults decision rides on it |
| `AbstractClient._prepare_conversation_context` (base.py:1976) | uses | shared message-context builder, unchanged |
| `AbstractClient._build_response_format_from` / `_oai_normalize_schema` / `_make_openai_strict_tool` (base.py:2604/2557/1294) | uses | stay on `AbstractClient` (default adopted; see §8) |
| `parrot.tools.manager.ToolFormat` (manager.py:47) | uses | no new members |
| `LLMFactory` / `SUPPORTED_CLIENTS` (factory.py:107–149) | none | class names and keys unchanged |
| `parrot/clients/__init__.py` | extends | export `OpenAIBaseClient` |
| FEAT-437 sample agents (`examples/agents/aws/`) | depends on | exercise `BedrockMantleClient`; merge-order coordination |

### Data Models

No new Pydantic models. Existing `AIMessage`, `CompletionUsage`,
`StructuredOutputConfig`, `InvokeResult` are consumed unchanged.

### New Public Interfaces

```python
# parrot/clients/openai_base.py  (NEW — signatures indicative, not implementation)
class OpenAIBaseClient(AbstractClient):
    """OpenAI-compatible wire protocol; carries NO OpenAI-provider defaults."""
    tool_format: ToolFormat = ToolFormat.OPENAI
    # NO _default_model / _fallback_model / _lightweight_model values here.

    async def get_client(self) -> Any: ...            # AsyncOpenAI(api_key, base_url, timeout) by default; hook for native SDKs (Groq/Zai)
    def _resolve_model(self, model) -> str: ...       # explicit > self.model > class default; calls _normalize_model
    def _normalize_model(self, model) -> str: ...     # identity in the base (OpenAIClient overrides with deprecation/alias logic)
    def _is_responses_model(self, model_str: str) -> bool: ...  # False in the base
    async def _chat_completion(self, model, messages, use_tools=False, **kwargs): ...  # THE single funnel
    async def ask(...) -> AIMessage: ...
    async def ask_stream(...) -> AsyncIterator[Union[str, AIMessage]]: ...  # routes via _chat_completion
    async def resume(...) -> AIMessage: ...           # shares the extracted tool loop with ask()
    async def invoke(...) -> InvokeResult: ...        # routes via _chat_completion
    async def batch_ask(self, requests) -> List[AIMessage]: ...
```

---

## 3. Module Breakdown

### Module 1: OpenAIBaseClient skeleton
- **Path**: `parrot/clients/openai_base.py` (new), `parrot/clients/__init__.py`
- **Responsibility**: Class shell: attrs (`tool_format=OPENAI`, no model
  defaults), `get_client()` default (`AsyncOpenAI` from subclass-supplied
  config), neutral hooks (`_normalize_model` identity, `_is_responses_model`
  False), `_resolve_model`, `_with_extra_body`. Fail-fast `ValueError` when a
  call resolves no model at all.
- **Depends on**: existing `AbstractClient`.

### Module 2: Wire-protocol extraction + single funnel
- **Path**: `parrot/clients/openai_base.py`, `parrot/clients/gpt.py`
- **Responsibility**: Move the chat-completions paths of
  `ask`/`ask_stream`/`resume`/`invoke`/`batch_ask`, `_chat_completion`,
  `_encode_image_for_openai`, `_upload_file` into the base. Extract the
  tool-calling loop into ONE shared implementation (replacing gpt.py:947–1143
  and its resume duplicate :1190–1257), preserving lazy-tool re-preparation,
  fallback metadata flags, and usage accumulation. Rework `ask_stream` and
  `invoke` to route through `_chat_completion` (G3).
- **Depends on**: Module 1.

### Module 3: OpenAIClient rebase (OpenAI-only residue)
- **Path**: `parrot/clients/gpt.py`
- **Responsibility**: `class OpenAIClient(OpenAIBaseClient)` keeping `gpt-*`
  defaults, `_normalize_model` deprecation/alias override, Responses-API +
  deep-research routing, Sora, Files download, cache hints, capacity-error
  typing, `OpenAIModel`-defaulted helpers. Import path preserved.
- **Depends on**: Module 2.

### Module 4: `_fallback_model` shadowing fix
- **Path**: `parrot/clients/base.py` (:350), `parrot/clients/nova/mantle.py` (:104)
- **Responsibility**: Assign `self._fallback_model` only when `fallback_model`
  is explicitly passed; delete the Mantle `kwargs.setdefault` workaround; unit
  test covering the chain for a subclass with a class-level `_fallback_model`.
- **Depends on**: none (parallel-safe with Modules 1–3, but sequenced in the
  same worktree).

### Module 5: Phase-1 subclass rebase
- **Path**: `parrot/clients/{openrouter,moonshot,nvidia,localllm,vllm}.py`,
  `parrot/clients/nova/mantle.py`
- **Responsibility**: Base-class swap to `OpenAIBaseClient`; delete
  now-redundant overrides (LocalLLM `_is_responses_model`; Moonshot
  `ask_stream`/`invoke` bypass workarounds); keep provider-real overrides.
  Existing per-client suites must pass unmodified except where they asserted
  the bypass wart itself.
- **Depends on**: Modules 2, 3, 4.

### Module 6: Phase-1 verification suite
- **Path**: `tests/clients/test_openai_compatible_defaults.py` (extend),
  new `tests/clients/test_openai_base_parity.py`
- **Responsibility**: Parametric no-`gpt-*`-leak test over every
  `OpenAIBaseClient` subclass except `OpenAIClient` (defaults, invoke chain,
  request payloads); payload-shape parity tests per client (mocked SDK, assert
  request JSON: model, tools, params); funnel-routing test (Moonshot/Nvidia
  `_chat_completion` override observed from `ask_stream` and `invoke`).
- **Depends on**: Module 5.

### Module 7: isinstance/issubclass audit
- **Path**: repo-wide (grep-driven), fixes wherever found
- **Responsibility**: Find `isinstance`/`issubclass` checks against
  `OpenAIClient`; decide per site whether it means "OpenAI the provider"
  (keep) or "OpenAI-compatible wire" (switch to `OpenAIBaseClient`).
- **Depends on**: Module 5.

### Module 8: Phase 2 — GroqClient rebase
- **Path**: `parrot/clients/groq.py`
- **Responsibility**: `GroqClient(OpenAIBaseClient)` keeping `AsyncGroq` via
  `get_client()`; delete `_prepare_groq_tools`,
  `_prepare_structured_output_format`, and the reimplemented
  `ask`/`ask_stream`/`resume` bodies in favor of shared wire logic;
  `ToolFormat.GROQ` retained, strict tools never applied (base.py:1420 already
  guarantees this). Payload-parity tests gate the swap.
- **Depends on**: Modules 5, 6.

### Module 9: Phase 2 — ZaiClient rebase
- **Path**: `parrot/clients/zai.py`
- **Responsibility**: `ZaiClient(OpenAIBaseClient)` keeping the official `zai`
  SDK via `get_client()` and adapting the completion/stream seam; delete
  duplicated shaping/tool-loop/stream-accumulation code; keep thinking-payload
  and usage-extraction behavior as subclass hooks. Payload-parity tests gate
  the swap.
- **Depends on**: Modules 5, 6 (independent of Module 8).

### Module 10: Live smoke scripts + docs
- **Path**: `examples/clients/` (or `examples/agents/` convention),
  `docs/clients/openai-compatible.md`
- **Responsibility**: Credential-gated (skip-if-no-key) smoke scripts against
  real endpoints (candidate set: Mantle, NIM, Moonshot, OpenRouter, Groq,
  local vLLM — final list per §8); short doc explaining the hierarchy and how
  to add a new OpenAI-compatible provider.
- **Depends on**: Modules 5, 8, 9.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_base_declares_no_model_defaults` | 1 | `OpenAIBaseClient` has `None` `_default_model`/`_fallback_model`/`_lightweight_model`; `tool_format is ToolFormat.OPENAI` |
| `test_base_normalize_model_is_identity` | 1 | base `_normalize_model` returns input untouched; no deprecation warning |
| `test_base_fails_fast_without_model` | 1 | no model configured anywhere → `ValueError`, nothing sent on the wire |
| `test_tool_loop_single_implementation_parity` | 2 | extracted loop reproduces gpt.py:947–1143 semantics: lazy re-prepare, fallback flags, usage accumulation, `tool_calls` on final `AIMessage` |
| `test_ask_stream_routes_via_chat_completion` | 2/6 | Moonshot/Nvidia `_chat_completion` override is hit from `ask_stream` |
| `test_invoke_routes_via_chat_completion` | 2/6 | same for `invoke` |
| `test_stream_yields_final_aimessage` | 2 | TASK-1175 contract preserved |
| `test_openai_client_keeps_gpt_defaults` | 3 | `OpenAIClient` still `gpt-5-mini`/`gpt-5-nano`/`gpt-4.1`; deprecation warnings intact |
| `test_responses_routing_only_on_openai` | 3 | `_is_responses_model` True only on `OpenAIClient` for o3/o3-pro |
| `test_fallback_model_not_shadowed` | 4 | subclass class-attr `_fallback_model` survives `__init__` without explicit kwarg; Mantle workaround removed |
| `test_no_gpt_leak_parametrized` | 6 | every non-OpenAI subclass: no `gpt-*` in defaults, invoke-model chain, or built payloads |
| `test_payload_parity_<client>` | 6/8/9 | per client, mocked SDK: request JSON (model, tools shape, params) identical pre/post rebase |
| `test_groq_tools_never_strict` | 8 | Groq payloads carry no `"strict": true` |
| `test_groq_keeps_native_sdk` / `test_zai_keeps_native_sdk` | 8/9 | `get_client()` returns `AsyncGroq` / `zai` client, not `AsyncOpenAI` |

### Integration Tests
| Test | Description |
|---|---|
| existing suites green | `test_nvidia_client.py`, `test_vllm_client.py`, `test_moonshot_client.py`, `test_bedrock_mantle.py`, `test_openrouter_client.py`, `test_localllm_client.py`, `test_groq_client.py`, `test_zai_client.py`, `tests/unit/test_*_invoke.py` pass without weakening assertions |
| `examples/` smoke scripts | manual, credential-gated live checks per endpoint (skip-if-no-key) |

### Test Data / Fixtures
```python
# Parametric client roster for leak/parity tests (Phase 1 set; Phase 2 adds Groq/Zai)
WIRE_SUBCLASSES = [OpenRouterClient, MoonshotClient, NvidiaClient,
                   LocalLLMClient, vLLMClient, BedrockMantleClient]

@pytest.fixture
def mock_openai_sdk(monkeypatch):
    """Capture chat.completions.create payloads without network."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot/clients/openai_base.py` exists; `OpenAIBaseClient` exported from
  `parrot.clients`; it declares **no** `gpt-*` string and no model-default
  values (checked by test).
- [ ] `from parrot.clients.gpt import OpenAIClient` and every pre-existing
  client import path and `LLMFactory` key work unchanged.
- [ ] All six wire subclasses inherit from `OpenAIBaseClient`;
  `GrokClient` is untouched (still `AbstractClient`, xai_sdk).
- [ ] Parametric no-leak test passes: no non-OpenAI subclass can emit a
  `gpt-*` model id unless explicitly configured (kills the DeepSeek-404 class
  of bug).
- [ ] `ask`, `ask_stream`, `resume`, `invoke` all route through
  `_chat_completion` (funnel tests pass); Moonshot's bypass-workaround
  overrides are deleted.
- [ ] `_fallback_model` shadowing fixed in `AbstractClient`; mantle.py
  workaround removed; regression test in place.
- [ ] Phase 2: `GroqClient`/`ZaiClient` rebased with native SDKs retained via
  hooks; duplicated wire code deleted; payload-parity tests prove identical
  request shapes; Groq payloads never contain strict-tools.
- [ ] Every pre-existing client test suite passes without weakened assertions
  (`pytest` full run green).
- [ ] Live smoke scripts exist and are credential-gated (skip-if-no-key).
- [ ] `docs/clients/openai-compatible.md` documents the hierarchy and the
  "add a provider" recipe.
- [ ] No breaking changes to the public API (MRO change audited — Module 7).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against `dev` @ `ab84ffff0` (2026-08-21), which already contains
> the tactical WIP (tool_format / _resolve_model / regression suite).
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying via `grep`/`read`.

### Verified Imports
```python
from parrot.clients.gpt import OpenAIClient            # clients/gpt.py:84
from parrot.clients.base import AbstractClient         # clients/base.py:250
from parrot.clients.nova.mantle import BedrockMantleClient  # clients/nova/mantle.py:29 (lazy: factory.py:64)
from parrot.tools.manager import ToolFormat            # tools/manager.py:47
from parrot.models.openai import OpenAIModel, is_deprecated, get_shutoff_date, resolve_alias
    # models/openai.py:17,171,193,215
```

### Existing Class Signatures

```python
# clients/gpt.py:84  (2579 lines)
class OpenAIClient(AbstractClient):
    client_type: str = "openai"                              # :87
    tool_format: ToolFormat = ToolFormat.OPENAI              # :91
    model: str = OpenAIModel.GPT5_MINI.value                 # :92
    _default_model: str = "gpt-5-mini"                       # :94
    _fallback_model: str = "gpt-5-nano"                      # :95
    _lightweight_model: str = "gpt-4.1"                      # :96  ← the 404 culprit
    _min_cache_tokens: int = 1024                            # :98

    def __init__(self, api_key: str = None, base_url: str = "https://api.openai.com/v1", **kwargs)  # :100
    def _resolve_model(self, model: Union[str, OpenAIModel, None]) -> str      # :108
    def _normalize_model(self, model: Union[str, OpenAIModel]) -> str          # :126 (deprecation/alias — OpenAI-only)
    async def get_client(self) -> "AsyncOpenAI"                                # :230 (AsyncOpenAI(api_key, base_url, timeout=config OPENAI_TIMEOUT))
    async def _chat_completion(self, model, messages, use_tools=False, **kw)   # :327 (tenacity; .create/.parse)
    def _is_responses_model(self, model_str: str) -> bool                      # :344 (o3/o3-pro)
    async def ask(self, prompt, model=None, ...) -> AIMessage                  # :693
    async def resume(self, session_id, user_input, state) -> AIMessage         # :1161
    async def ask_stream(self, prompt, model=None, ...) -> AsyncIterator       # :1283
    async def batch_ask(self, requests) -> List[AIMessage]                     # :1642
    def _encode_image_for_openai(self, image, low_quality=False) -> Dict       # :1652
    async def invoke(self, prompt, *, model=None, ...) -> InvokeResult         # :2494
# Tool loop INLINED: ask() :947–1143; duplicated in resume() :1190–1257
# Responses API (OpenAI-only): _prepare_responses_args :365, _call_responses_create :522,
#   _call_responses_stream :555, _responses_completion :585; RESPONSES_ONLY_MODELS :50
# Deep research :351; Sora generate_video :2349; Files _download_openai_file :244
# OpenAIModel-defaulted helpers: summarize_text :1819, translate_text :1869,
#   extract_key_points :1928, analyze_sentiment :1973, analyze_product_review :2019,
#   ask_to_image :1690, image_identification :2086
# STRUCTURED_OUTPUT_COMPATIBLE_MODELS :55–80 (OpenAI-only gate)
```

```python
# clients/base.py:250  (2645 lines)
class AbstractClient(EventEmitterMixin, ABC):
    client_type: str = "generic"                     # :256
    tool_format: Optional[ToolFormat] = None         # :268
    _lightweight_model: Optional[str] = None         # :272
    _min_cache_tokens: int = 0                       # :278
    # __init__:  self._fallback_model = kwargs.get('fallback_model', None)  # :350  ← G5 target (shadows class attr)

    def _make_openai_strict_tool(self, schema) -> Dict[str, Any]      # :1294 (on AbstractClient, NOT OpenAIClient)
    def _resolve_tool_format(self) -> ToolFormat                      # :1364 (explicit tool_format wins; else client_type map; else ANTHROPIC)
    def _prepare_tools(self, filter_names=None) -> List[Dict]         # :1388
    #   :1411 OPENAI|GROQ → function wrapper; :1420 strict ONLY for OPENAI (Groq rejects)
    def _resolve_invoke_model(self, model=None) -> str                # :1832 (explicit > _lightweight_model > self.model; :1841/:1845/:1847)
    async def _prepare_conversation_context(self, prompt, files, user_id,
        session_id, system_prompt, stateless=False)                   # :1976
    def _oai_normalize_schema(self, schema, *, force_required_all=True) -> dict  # :2557
    def _build_response_format_from(self, output_config)              # :2604
    @property
    def default_model(self) -> str                                    # :906 → getattr(self, '_default_model', None)
    def _should_use_fallback(self, model, error) -> bool              # :926
    # Abstract: get_client :946, ask :1644, ask_stream :1682, resume :1711, invoke :1733
```

```python
# Phase-1 subclass override inventory (verified):
# clients/openrouter.py:26   OpenRouterClient(OpenAIClient), 200 L
#   _default_model = OpenRouterModel.DEEPSEEK_R1.value :54; __init__ :56 (base_url openrouter.ai/api/v1,
#   OPENROUTER_API_KEY), get_client :80, _chat_completion :116 (super + extra_body)
# clients/moonshot.py:88     MoonshotClient(OpenAIClient), 440 L
#   _default_model KIMI_K2_6 :131, _fallback_model MOONSHOT_V1_128K :132
#   _chat_completion :201, ask :282, ask_stream :326, invoke :397
#   ask_stream/invoke overrides exist ONLY because of the funnel bypass (their docstrings say so) → delete in Module 5
# clients/nvidia.py:207      NvidiaClient(OpenAIClient), 602 L
#   _default_model MINIMAX_M3 :269; __init__ :271 (NIM base_url, NVIDIA_API_KEY, SlidingWindowRateLimiter :92)
#   _chat_completion :407 ("NIM rejects .parse()"), ask :473, ask_stream :527
# clients/localllm.py:25     LocalLLMClient(OpenAIClient), 381 L
#   _lightweight_model = None :64 (manual leak fix — superseded by this feature), _default_model "llama3.1:8b" :65
#   get_client :96, _is_responses_model :118 (always False → delete in Module 5), ask :132, ask_stream :157, invoke :211
# clients/vllm.py:35         vLLMClient(LocalLLMClient), 461 L — guided_json/regex/choice; os.getenv (not navconfig)
# clients/nova/mantle.py:29  BedrockMantleClient(OpenAIClient), 128 L
#   _default_model "openai.gpt-oss-120b" :81, _fallback_model "google.gemma-4-26b-a4b" :82
#   ONLY __init__ :84; kwargs.setdefault("fallback_model", …) :104 ← delete with G5
```

```python
# Phase-2 targets (verified):
# clients/groq.py:49  GroqClient(AbstractClient), 1424 L — SDK groq.AsyncGroq (:81; base_url stored :72 but NOT passed to SDK :88)
#   _lightweight_model "kimi-k2-instruct" :63; _prepare_groq_tools :195 (callers 317,743,851),
#   _prepare_structured_output_format :227; reimplemented ask :270 / ask_stream :678 / resume :819 / invoke :1293
#   client_type "groq" → ToolFormat.GROQ via base map (base.py:1385)
# clients/zai.py:22   ZaiClient(AbstractClient), 1024 L — SDK official `zai` (:56)
#   _lightweight_model GLM_4_5_FLASH_FREE :29; message shaping :73–131; _prepare_zai_tools :132;
#   response→AIMessage :204–283; tool loop :288–349; _accumulate_stream_tool_calls :511;
#   _create_completion :284 / _stream_completion :536 (SDK seams); embed :1022 raises NotImplementedError
# clients/grok.py:53  GrokClient(AbstractClient), 774 L — SDK xai_sdk.AsyncClient (:93); stateful chat.sample()/chat.parse()
#   → OUT OF SCOPE (Non-Goal)
```

```python
# tools/manager.py:47
class ToolFormat(Enum):
    OPENAI="openai"; ANTHROPIC="anthropic"; GOOGLE="google"; GROQ="groq"
    VERTEX="vertex"; GENERIC="generic"; BEDROCK="bedrock"

# clients/factory.py — SUPPORTED_CLIENTS :107–149 (keys unchanged); lazy-loader resolution :242-243;
#   LLMFactory.parse_llm_string :171; LLMFactory.create :193 (init_params['model'] = model :250)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OpenAIBaseClient` | `AbstractClient.__init__` / lifecycle | inheritance (`super().__init__`) | base.py:250 |
| `OpenAIBaseClient._prepare_tools` usage | `AbstractClient._prepare_tools()` | inherited call | base.py:1388 |
| `OpenAIBaseClient.tool_format` | `AbstractClient._resolve_tool_format()` | attribute read | base.py:1378 |
| `OpenAIBaseClient.invoke` | `AbstractClient._resolve_invoke_model()` | inherited call | base.py:1832 |
| `OpenAIBaseClient` message context | `AbstractClient._prepare_conversation_context()` | inherited call | base.py:1976 |
| rebased subclasses | `OpenAIBaseClient._chat_completion()` | override + super() | gpt.py:327 (current funnel) |
| `LLMFactory.create` | unchanged client classes | `SUPPORTED_CLIENTS` map | factory.py:107–149 |

### Does NOT Exist (Anti-Hallucination)
- ~~`OpenAIBaseClient` / `OpenAICompatibleClient`~~ — do not exist yet (grep:
  zero matches); Module 1 creates the former. Do NOT invent the latter.
- ~~`parrot/clients/openai_base.py`~~ — does not exist yet.
- ~~`OpenAIClient.embed()`~~ — no embedding method in gpt.py; `AbstractClient`
  has no `embed` abstract method (`ZaiClient.embed` only raises
  `NotImplementedError`, zai.py:1022).
- ~~a dedicated message-shaping method on `OpenAIClient`~~
  (`_build_messages` / `_to_openai_messages`) — message construction is inline
  in `ask()`/`ask_stream()`; only `_prepare_conversation_context`
  (base.py:1976) is shared. (`ZaiClient._build_messages` exists but is Zai's
  own, zai.py:106.)
- ~~`OpenAIClient._make_openai_strict_tool`~~ — lives on `AbstractClient`
  (base.py:1294).
- ~~`ToolFormat.OPENAI_COMPATIBLE` / `.XAI` / `.ZAI` / `.MOONSHOT` / `.NVIDIA`~~ —
  only the 7 members listed above.
- ~~`client_type == "openai-compatible"` factory key~~ — not in
  `SUPPORTED_CLIENTS`.
- ~~`tool_format` declarations on subclasses~~ — only gpt.py:91 declares it;
  Groq/Grok/Zai declare none.
- ~~`test_gpt.py`~~ — per-client suites live in `packages/ai-parrot/tests/`
  and repo-root `tests/` (see §4), not `packages/ai-parrot/tests/clients/`.
- ~~`GrokClient` speaking OpenAI wire~~ — xai_sdk stateful API; treating it as
  OpenAI-compatible is wrong.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first throughout; `aiohttp` (never `requests`/`httpx`) — though this
  feature only touches SDK-mediated calls.
- Google-style docstrings + strict type hints on every moved/new method.
- `self.logger` for logging; no prints.
- Config via `navconfig.config.get` for env vars (note vllm.py currently uses
  `os.getenv` — leave as-is unless a task says otherwise).
- Extraction discipline: Modules 2–5 move code with surgical fidelity; every
  intentional behavior change (the funnel rework, deleted overrides) must be
  named in the task and covered by a test. Anything else is a regression.
- Commit convention `sdd: <action> for openai-compatible-clients`; one task =
  one commit, in the feature worktree.

### Known Risks / Gotchas
- **Tool-loop extraction** (gpt.py:947–1143 + :1190–1257) is the highest-risk
  move: preserve lazy-tool re-preparation (`_prepare_tools(filter_names=…)`
  :1050), fallback metadata (:1144–1147), usage accumulation, and final
  `tool_calls` assignment (:1143/:1280). Parity test before rebase.
- **Funnel rework changes real behavior** for `ask_stream`/`invoke` on
  subclasses that override `_chat_completion` (Moonshot, Nvidia, OpenRouter):
  that is the *point* (G3), but existing tests asserting the bypass (e.g.
  Moonshot "create-not-parse"/invoke-guard tests) must be updated deliberately,
  not weakened silently.
- **`_fallback_model` shadowing fix (G5)** alters `__init__` semantics for ALL
  clients, including Anthropic/Google/Bedrock — verify no client relied on the
  implicit reset-to-None (grep constructors + run full suite).
- **MRO visibility**: after rebase, non-OpenAI clients stop being
  `isinstance(x, OpenAIClient)` — Module 7 audits every check site.
- **No model configured**: base must raise a clear `ValueError` at call time,
  never send `model=None` (today `OpenAIClient`'s defaults masked this path).
- **Streaming contract**: `ask_stream` must keep yielding the final
  `AIMessage` (TASK-1175).
- **Zai SDK seam**: the official `zai` SDK is not the OpenAI SDK; its
  completion/stream calls stay behind subclass overrides of the funnel — do
  not assume `chat.completions.create` exists on it.
- **Groq SDK base_url quirk**: `GroqClient` stores `base_url` but never passes
  it to `AsyncGroq` (groq.py:72/:88) — preserve current behavior; do not
  "fix" silently.
- **Shared-checkout hazard**: all implementation happens in the feature
  worktree (`.claude/worktrees/feat-438-openai-compatible-clients`), never in
  the main checkout.
- **FEAT-437 overlap**: `examples/agents/aws/` sample agents (TASK-2293–2295
  active) exercise `BedrockMantleClient`; coordinate merge order with that
  feature.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `openai` | existing dep | `AsyncOpenAI` for all wire clients (unchanged) |
| `tenacity` | existing dep | retry in `_chat_completion` (moves with it) |
| `groq` | existing dep | retained — `AsyncGroq` behind `get_client()` (spec decision) |
| `zai` | existing dep | retained — official SDK behind `get_client()` (spec decision) |
| `pytest` / `pytest-asyncio` | existing dep | parity + leak suites |

No new dependencies.

---

## 8. Open Questions

> Decision trail: `[x]` items are settled (brainstorm or spec-time) and are
> reflected in the spec body; do not re-open during implementation.

- [x] Should the tactical WIP land before this feature? — *Resolved in
  brainstorm*: Yes — landed on `dev` as commit `ab84ffff0` (tool_format,
  `_resolve_model`, regression suite); this spec builds on it.
- [x] Do Groq/Zai migrate onto the new base? — *Resolved in brainstorm*: Yes,
  Phase 2, under strict payload-parity tests; Groq keeps `ToolFormat.GROQ`
  and never strict tools.
- [x] Model defaults on the base when a subclass declares none? — *Resolved in
  brainstorm*: `None` → existing chain falls back to `self.model`
  (base.py:1832).
- [x] `GrokClient` disposition — *Resolved at spec time*: excluded (Non-Goal);
  stays on `AbstractClient` with xai_sdk.
- [x] Phase-2 SDK swap — *Resolved at spec time*: keep native SDKs
  (`AsyncGroq`, `zai`) behind `get_client()`/funnel hooks; only shaping/loop
  code is shared. `AsyncOpenAI` swap explicitly rejected.
- [x] `_fallback_model` shadowing fix in Phase 1 — *Resolved at spec time*:
  yes (G5 / Module 4); mantle.py workaround removed.
- [ ] OpenAI-shaped helpers on `AbstractClient` (`_make_openai_strict_tool`
  :1294, `_oai_normalize_schema` :2557, `_build_response_format_from` :2604):
  default adopted = **stay on `AbstractClient`** (called from generic paths);
  revisit only if Module 2 finds a hard reason to move them — *Owner: Jesus*
- [ ] Smoke-script endpoint list + credential gating convention (candidates:
  Mantle, NIM, Moonshot, OpenRouter, Groq, local vLLM; skip-if-no-key) —
  *Owner: Jesus, decide at Module 10 task*
- [ ] isinstance-audit outcome (Module 7): which check sites, if any, must
  switch to `OpenAIBaseClient` — *Owner: implementer*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  (`.claude/worktrees/feat-438-openai-compatible-clients`), all tasks
  sequential.
- **Rationale**: Modules 1–5 form a serialized chain over the same hot files
  (`openai_base.py`, `gpt.py`); strict-parity verification requires each
  rebase to land on the previous one's green suite. Modules 8 and 9 are
  mutually independent but both small enough that parallel worktrees would add
  ceremony without payoff.
- **Cross-feature dependencies**: FEAT-437 (claude-bedrock-sample-agents,
  TASK-2293–2295 active) exercises `BedrockMantleClient` from
  `examples/agents/aws/` — coordinate merge order; no other in-flight spec
  touches `parrot/clients/`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-21 | Jesus | Initial draft from brainstorm (Option B) + spec-time decisions (Grok excluded; native SDKs retained; G5 shadowing fix in Phase 1) |
