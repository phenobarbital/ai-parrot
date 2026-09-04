---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Meta Model API (Muse Spark) LLM Client

**Feature ID**: FEAT-526
**Date**: 2026-09-04
**Author**: Jesus (jlara@trocglobal.com)
**Status**: approved
**Target version**: 0.29.0

**Proposal**: [`sdd/proposals/meta-llm-client.proposal.md`](../proposals/meta-llm-client.proposal.md) (status: accepted)
**Research audit**: [`sdd/state/FEAT-526/`](../state/FEAT-526/) — 17 findings, 10 live authenticated API calls

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has no client for **Meta Model API** — Meta's hosted inference service
for the **Muse Spark** model family (1,048,576-token context, agentic/coding
tuned). The service is OpenAI-wire compatible and reachable with the OpenAI SDK
pointed at `https://api.meta.ai/v1`, so a parrot client is a natural fit for the
existing `OpenAIBaseClient` layer.

The platform was verified live during research, not assumed: `GET /v1/models`
returns HTTP 200 with 7 models using the repo's own `META_API_KEY` (F013).

### Goals

- **G1** — `MetaClient` in `parrot.clients`, subclassing `OpenAIBaseClient`,
  usable as `LLMFactory.create("meta:muse-spark-1.3")`.
- **G2** — `parrot.models.meta` with a `MetaModel(str, Enum)` of the 7
  live-verified model ids plus capability frozensets, following `MoonshotModel`.
- **G3** — Chat Completions support: chat, tool calling, structured output,
  streaming, `invoke()`.
- **G4** — Responses API support (**MetaClient-local**, per D1), unlocking
  search grounding and `count_input_tokens()`.
- **G5** — Live end-to-end coverage against `muse-spark-1.3-contributor`,
  mirroring the existing live-OpenAI tests.
- **G6** — Map parrot's client-side `search_tools` onto Meta's native
  `tool_search` (per D2) — **last, and droppable**.

### Non-Goals (explicitly out of scope)

- **Muse Image** (`muse-image-1.0`) and **Muse Voice Transcribe**
  (`muse-voice-transcribe-1.0`) — reserved as enum members only; no endpoint work.
- **Muse Glimmer** — open-weight, self-hosted, not served on Model API at all.
- **The Anthropic-shaped Messages API** (`POST /v1/messages`) — a third protocol,
  deferred.
- **Prompt caching implementation** — it is automatic server-side; there is
  nothing to build. Observability only (`cached_tokens`).
- **Modifying `OpenAIBaseClient` or `OpenAIClient`** — D1 keeps Responses
  support local to `MetaClient` precisely to avoid touching the shared layer.
- **Citation/annotation extraction from search grounding** — deliberately
  excluded; see §7 Known Risks (annotations came back empty in live testing).

---

## 2. Architectural Design

### Overview

`MetaClient` subclasses `OpenAIBaseClient` — the neutral OpenAI-wire layer
introduced by FEAT-438, which owns the wire protocol and declares **zero**
OpenAI-provider model defaults. This follows the documented seven-step recipe in
`docs/clients/openai-compatible.md`.

Two request paths:

1. **Chat Completions** (inherited, near-free). `OpenAIBaseClient.ask()`,
   `ask_stream()`, `resume()` and `invoke()` all funnel through
   `_chat_completion()`. Live testing confirmed the base's existing emissions are
   already Meta-legal: it sends `tool_choice="auto"` (Meta HTTP 400s on every
   other value) and `max_tokens` (correct for Chat Completions).

2. **Responses API** (net-new, `MetaClient`-local per **D1**). `OpenAIBaseClient`
   has none — `_is_responses_model()` returns `False` there by design. `MetaClient`
   overrides `ask()`/`ask_stream()` to route to a local `_responses_completion()`,
   mirroring the *structure* `OpenAIClient` uses (`gpt.py:353-680`) without
   sharing or modifying it.

**Credential resolution** (per user decision): `api_key` kwarg → `META_API_KEY`
→ `MODEL_API_KEY`. It MUST NOT fall through to `OPENAI_API_KEY` — `AsyncOpenAI`
would otherwise silently pick it up and ship an `sk-…` key to Meta.

**Default model**: `muse-spark-1.3` (Standard tier). The `-contributor` variants
grant Meta permission to train on prompts and completions and MUST NEVER be a
library default — they are for synthetic e2e prompts only.

### Component Diagram

```
AbstractClient (clients/base.py:227)
   └── OpenAIBaseClient (clients/openai_base.py:65)   [wire protocol, no defaults]
          ├── OpenAIClient (gpt.py:86)                [untouched by this feature]
          ├── OpenRouterClient / MoonshotClient / …   [untouched]
          └── MetaClient (clients/meta.py)            ← NEW
                 ├── __init__            credential chain + base_url
                 ├── get_client()        AsyncOpenAI(base_url=…) — raised timeout
                 ├── _chat_completion()  inherited (no override needed)
                 ├── ask()/ask_stream()  override → Responses routing
                 ├── _responses_completion()   folds output[] items
                 ├── count_input_tokens()      POST /v1/responses/input_tokens
                 └── list_models()             GET /v1/models

parrot/models/meta.py                                 ← NEW
   MetaModel(str, Enum) + CONTRIBUTOR_MODELS / SPARK_MODELS / …
```

### Integration Points

| Target | Change | Evidence |
|---|---|---|
| `clients/factory.py:107` `SUPPORTED_CLIENTS` | add `"meta"`, `"muse"`, `"meta-muse"` → `MetaClient` | F008 |
| `clients/factory.py:2-13` imports | add `from .meta import MetaClient` (direct; only needs `openai`) | F008 |
| `tests/clients/test_openai_compatible_defaults.py:49` | add `MetaClient` to `WIRE_SUBCLASSES` | F012 |
| `tests/clients/test_openai_base_parity.py:341` | add `MetaClient` to `WIRE_SUBCLASSES` | F012 |
| `examples/clients/smoke/` | add `smoke_meta.py` via `main_for(...)` | F012 |
| `docs/clients/` | add `meta.md` (recipe step 7) | F006 |

### Data Models

```python
# parrot/models/meta.py — pattern: parrot/models/moonshot.py
class MetaModel(str, Enum):
    """Meta Model API identifiers — verified live via GET /v1/models (F013)."""
    MUSE_SPARK_1_3 = "muse-spark-1.3"
    MUSE_SPARK_1_3_CONTRIBUTOR = "muse-spark-1.3-contributor"
    MUSE_SPARK_1_2 = "muse-spark-1.2"
    MUSE_SPARK_1_2_CONTRIBUTOR = "muse-spark-1.2-contributor"
    MUSE_SPARK_1_1 = "muse-spark-1.1"          # NOTE: no contributor variant
    MUSE_IMAGE_1_0 = "muse-image-1.0"          # reserved — out of scope
    MUSE_VOICE_TRANSCRIBE_1_0 = "muse-voice-transcribe-1.0"  # reserved

# Tier that permits Meta to train on prompts/completions — synthetic e2e only.
CONTRIBUTOR_MODELS: frozenset[str] = frozenset({...})
SPARK_MODELS: frozenset[str] = frozenset({...})
CONTEXT_WINDOW: int = 1_048_576   # uniform across all Spark models
```

### New Public Interfaces

```python
class MetaClient(OpenAIBaseClient):
    client_type: str = "meta"
    client_name: str = "meta"
    _default_model: str = MetaModel.MUSE_SPARK_1_3.value
    _default_timeout: float = 120.0     # raised: heavy reasoning latency (F015)

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 use_responses: bool = True, **kwargs) -> None: ...

    async def count_input_tokens(self, *, model: str | None = None,
                                 input: Any, **kwargs) -> int: ...
    async def list_models(self) -> list[dict[str, Any]]: ...
```

---

## 3. Module Breakdown

### Module 1: `parrot/models/meta.py` — model catalog
The `MetaModel` enum plus capability frozensets. No Pydantic wrappers needed —
Meta's Chat Completions response shape matches OpenAI's and is already covered by
existing `AIMessage` / `CompletionUsage` models (same rationale as
`models/moonshot.py`). Pure data; no I/O.

### Module 2: `MetaClient` — Chat Completions path
`__init__` credential chain, `get_client()` returning `AsyncOpenAI`,
`_default_model`, raised `_default_timeout`, `list_models()`. Everything else is
inherited from `OpenAIBaseClient` unchanged.

### Module 3: `MetaClient` — Responses API path (D1: local)
`ask()`/`ask_stream()` overrides gated on `use_responses`; `_responses_completion()`
folding `output[]` items; search grounding via `tools=[{"type": "web_search"}]`;
`count_input_tokens()`.

### Module 4: Registration + test rosters
`factory.py` entry and both `WIRE_SUBCLASSES` rosters.

### Module 5: Live e2e + docs
`smoke_meta.py`, `docs/clients/meta.md`.

### Module 6 (LAST, droppable): `search_tools` ↔ native `tool_search`
Per **D2**: unify the surface so parrot's `search_tools` can dispatch to Meta's
native hosted `tool_search`, with **parrot's client-side path remaining the
default** — the user measured Meta's hosted variant as slower. Nothing else
depends on this module; it is the safe cut if the phase runs long.

---

## 4. Test Specification

### Unit Tests
```python
# tests/clients/test_meta_client.py
def test_meta_client_subclasses_openai_base()
def test_default_model_is_standard_tier_not_contributor()
def test_api_key_chain_prefers_META_API_KEY_over_MODEL_API_KEY()
def test_api_key_chain_never_falls_back_to_OPENAI_API_KEY()   # regression guard
def test_base_url_is_api_meta_ai_v1()
def test_metamodel_enum_matches_live_catalog()
def test_muse_spark_1_1_has_no_contributor_variant()
def test_contributor_models_frozenset_membership()
def test_responses_output_folding_concatenates_message_items()
def test_responses_output_folding_ignores_reasoning_items()
```

### Integration Tests
```python
# tests/clients/test_openai_compatible_defaults.py  (roster extension)
#   test_no_gpt_default_leak[MetaClient]
#   test_invoke_chain_never_yields_gpt[MetaClient]
#   test_ask_payload_model_never_leaks_gpt[MetaClient]
# tests/clients/test_openai_base_parity.py          (roster extension)
#   ask/ask_stream/invoke funnel parity + OPENAI tool-format parity
```

### Live E2E (credential-gated, skips cleanly without a key)
```python
# tests/e2e/test_meta_live.py — model: muse-spark-1.3-contributor
async def test_live_chat_completion_returns_nonempty_visible_text()  # ← F015 guard
async def test_live_tool_calling_roundtrip()
async def test_live_structured_output_conforms_to_schema()
async def test_live_responses_api_returns_completed()
async def test_live_search_grounding_emits_web_search_call()
async def test_live_count_input_tokens_returns_positive_int()
async def test_live_tool_choice_required_raises()                    # asserts 400
```

### Test Data / Fixtures
- All live prompts MUST be **synthetic** (no company or user data) — the
  contributor tier grants Meta training rights.
- Reuse `examples/clients/smoke/_runner.py`'s `calculator` tool (`:37`) as the
  tool-calling fixture.

---

## 5. Acceptance Criteria

- [ ] **AC1** — `LLMFactory.create("meta:muse-spark-1.3")` returns a `MetaClient`.
- [ ] **AC2** — `MetaClient` subclasses `OpenAIBaseClient`, never `OpenAIClient`.
- [ ] **AC3** — No `_default_model`/`_fallback_model`/`_lightweight_model` holds a
      `gpt-*` id; both `WIRE_SUBCLASSES` sweeps pass with `MetaClient` added.
- [ ] **AC4** — Key resolution is `api_key` → `META_API_KEY` → `MODEL_API_KEY`,
      and **never** `OPENAI_API_KEY` (explicit regression test).
- [ ] **AC5** — `MetaModel` contains exactly the 7 live-verified ids.
- [ ] **AC6** — Default model is Standard tier; no contributor id is a default
      anywhere in library code.
- [ ] **AC7** — `await client.ask("...")` returns **non-empty visible text** under
      the client's default output budget. *(Carries F015 — Muse Spark spent 199
      of 210 output tokens on reasoning to answer `pong`; a low `max_tokens`
      silently truncates visible output. This is the single most likely
      confusing failure in the feature.)*
- [ ] **AC8** — Tool calling completes a full round trip; `strict: true` schemas
      are accepted.
- [ ] **AC9** — Structured output returns schema-conformant JSON.
- [ ] **AC10** — Responses path returns `status: "completed"` and folded text.
- [ ] **AC11** — Search grounding emits a `web_search_call` output item.
- [ ] **AC12** — `count_input_tokens()` returns a positive int.
- [ ] **AC13** — `smoke_meta.py` exits 0 with `SKIPPED` when no key is set.
- [ ] **AC14** — `docs/clients/meta.md` exists and documents the contributor-tier
      training caveat and the output-budget gotcha.
- [ ] **AC15** — `pytest tests/clients/ -v` passes; `ruff` clean on changed files.
- [ ] **AC16** *(Module 6, droppable)* — `search_tools` can dispatch to native
      `tool_search`; parrot's client-side path remains the default.

---

## 6. Codebase Contract

> Every entry below was read from source during research on 2026-09-04.
> Line numbers are from that revision — re-verify before relying on them.

### Verified Imports

```python
from parrot.clients.openai_base import OpenAIBaseClient   # openai_base.py:65
from parrot.clients.base import AbstractClient            # base.py:227
from parrot.tools.manager import ToolFormat               # manager.py:51
from navconfig import config                              # used by all wire clients
```
`parrot/clients/__init__.py` exports `AbstractClient`, `OpenAIBaseClient`,
`LLM_PRESETS`, `StreamingRetryConfig`, `ZaiClient` — **`MetaClient` is not
exported there today**; follow the sibling convention (import via
`parrot.clients.meta` and register in `factory.py`).

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                                   # :65
    tool_format: ToolFormat = ToolFormat.OPENAI                          # :76
    _default_timeout: float = 60.0                                       # :87
    def __init__(self, api_key: str|None=None, base_url: str|None=None, **kwargs)  # :89
    async def get_client(self) -> Any                                    # :120
    def _normalize_model(self, model: Any) -> str                        # :146
    def _resolve_model(self, model: Any|None) -> str                     # :162
    def _is_responses_model(self, model_str: str) -> bool                # :181  (always False)
    async def _chat_completion(self, model: str, messages: Any,
        use_tools: bool=False, stream: bool=False, **kwargs) -> Any      # :216  ← THE FUNNEL
    async def _run_tool_call_loop(...)                                   # :295
    async def ask(self, prompt, model=None, max_tokens=None, temperature=None,
        files=None, system_prompt=None, history=None, structured_output=None,
        tools=None, use_tools=None, lazy_loading=False) -> AIMessage     # :523
    async def resume(self, session_id, user_input, state) -> AIMessage   # :760
    async def batch_ask(self, requests) -> list[AIMessage]               # :807
    async def ask_stream(...)                                            # :882
    async def invoke(...)                                                # :1153
    args["tool_choice"] = "auto"                                         # :639, :979
    args["max_tokens"] = ...                                             # :643, :983

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):                            # :227
    client_type: str = "generic"; client_name: str = "generic"
    tool_format: Optional[ToolFormat] = None
    _lightweight_model / _fallback_model: Optional[str] = None
    async def _ensure_client(self, **hints) -> Any                       # :828
    async def __aenter__ / __aexit__                                     # :1019 / :1031
    def _resolve_tool_format(self) -> ToolFormat                         # :1340
    def _prepare_tools(self, filter_names=None) -> List[Dict]            # :1364
    def _make_openai_strict_tool(self, schema) -> Dict                   # :1269 (sets strict=True)
    def _prepare_lazy_tools(self, tool_choice="auto") -> List[Dict]      # :1322 (search_tools)
    def _check_new_tools(self, tool_name, tool_result_content)           # :1298
    def _format_history(self, history: Sequence[HistoryMessage])         # :1571
    async def ask / ask_stream / resume / batch_ask / invoke  # :1660/:1701/:1729/:1742/:1747
    def _resolve_invoke_model(self, model=None) -> str                   # :1849

# packages/ai-parrot/src/parrot/clients/openrouter.py — THE PATTERN TO COPY
class OpenRouterClient(OpenAIBaseClient):
    client_type = client_name = "openrouter"; _default_model = ...
    # __init__: resolved_key = api_key or config.get('OPENROUTER_API_KEY')
    #           super().__init__(api_key=..., base_url=..., **kwargs)
    #           self.api_key = resolved_key   ← re-set; AbstractClient may overwrite
    async def get_client(self) -> AsyncOpenAI
    async def list_models(self) -> List[Dict[str, Any]]   # aiohttp, not httpx

# packages/ai-parrot/src/parrot/clients/gpt.py — STRUCTURAL reference only (do NOT modify)
class OpenAIClient(OpenAIBaseClient):                                    # :86
    def _is_responses_model(self, model_str) -> bool                     # :332
    def _prepare_responses_args(self, *, messages, args)                 # :353
    async def _call_responses_create(self, payloads)                     # :504
    async def _call_responses_stream(self, payloads)                     # :537
    async def _responses_completion(self, *, model, messages, **args)    # :567
    #   :597-607 — output_text fallback: getattr(resp,"output_text",None)
    #              then iterate parts for type == "output_text"
    async def ask(...)  # :688; gates on use_responses at :874

# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS: dict                                                  # :107
PROVIDER_BACKEND: Dict[str, str]                                         # :155
class LLMFactory: parse_llm_string (:171) / create (:193)

# packages/ai-parrot/src/parrot/models/moonshot.py — ENUM PATTERN
class MoonshotModel(str, Enum): ...
K_SERIES_MODELS / VISION_MODELS / … : frozenset[str]

# examples/clients/smoke/_runner.py
def calculator(expression: str) -> str        # :37   — shared tool fixture
def check_env_vars(env_vars: list[str])       # :77
async def run_smoke(...)                      # :102
def main_for(provider=..., model=..., env_vars=[...])   # :196
```

### Verified External API Contract (live, 2026-09-04)

```
Base URL : https://api.meta.ai/v1        Auth: Authorization: Bearer <key>
GET  /v1/models                  -> 200  7 models
POST /v1/chat/completions        -> 200  OpenAI-shaped `choices[]`
POST /v1/responses               -> 200  typed `output[]`, NO `choices`
POST /v1/responses/input_tokens  -> 200  {"object":"response.input_tokens","input_tokens":N}
tool_choice: "required"          -> 400  'only `"auto"` is supported for `tool_choice`'
function tool strict: true       -> 200  accepted (conformant schema)
tools:[{"type":"tool_search"}]   -> 400  'requires at least one deferred tool'
```

### Does NOT Exist (Anti-Hallucination)

- ❌ `parrot/clients/meta.py` — created by this feature.
- ❌ `parrot/models/meta.py` — created by this feature.
- ❌ `MetaClient`, `MetaModel` — do not exist anywhere yet.
- ❌ **`OpenAIBaseClient` has NO Responses-API support.** There is no
  `_responses_completion`, `_prepare_responses_args`, or `_call_responses_create`
  on it — those live only on `OpenAIClient` (`gpt.py`). `_is_responses_model()`
  on the base returns `False` unconditionally (`openai_base.py:181`).
- ❌ **`response.output_text` is NOT a wire field.** It is an OpenAI-SDK-computed
  property. Verified live: raw JSON has no such key. Using `AsyncOpenAI` gives it
  for free; a raw-HTTP implementation must fold `output[]` items itself.
- ❌ No `parrot/vectorstores/` package (long gone) — irrelevant here, listed
  because it is a recurring hallucination in this repo.
- ❌ `MODEL_API_KEY` is **not set** in this environment; only `META_API_KEY` is.
- ❌ No `httpx`/`requests` — this repo uses `aiohttp` exclusively.
- ❌ There is no `parrot/` package at the repo root; source is
  `packages/ai-parrot/src/parrot/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **`OpenRouterClient` end-to-end** for `__init__`, the `self.api_key` re-set,
  `get_client()`, and `list_models()` (aiohttp).
- **`MoonshotModel`** for the enum + capability-frozenset layout.
- **The 7-step recipe** in `docs/clients/openai-compatible.md`.
- **`OpenAIClient`'s Responses methods as a structural template only** — read
  them, mirror the shape, but do **not** import, subclass, or modify `gpt.py`
  (D1 keeps this local).
- Async-first; `self.logger`, never `print`; Google-style docstrings + type hints.

### Known Risks / Gotchas

1. **⚠️ Reasoning consumes the output budget (highest-impact).** Live: **199/210**
   completion tokens were `reasoning_tokens` for the one-word answer `pong`
   (Responses: 142/153). A conventional `max_tokens=256` will return empty or
   truncated visible text. Hence the raised `_default_timeout` and AC7.
2. **`tool_choice` must be `"auto"`** — anything else is HTTP 400. The inherited
   base already complies; do not "improve" it into forcing a tool.
3. **`logprobs` is unsupported** (HTTP 400) — Muse Spark is a reasoning model.
4. **`reasoning_content` is redacted to empty** for external keys on Chat
   Completions. Never surface it as thinking output.
5. **Search-grounding `annotations` came back empty** on a successful grounded
   answer despite docs advertising inline citations. Citation extraction is
   explicitly a Non-Goal until re-verified.
6. **Contributor tier = training consent.** Never a library default; synthetic
   prompts only; document it at every call site.
7. **Recursive/`$ref`-cycle schemas → HTTP 400** on every surface, and under
   `strict: true` also `allOf`/`oneOf` anywhere and `anyOf` at the root.
8. **Possible interaction**: `sdd/specs/openai-max-completion-tokens.spec.md`
   (another in-flight feature) concerns output-token params for reasoning models.
   Check for overlap before implementing — flagged as low-confidence C12.
9. **Worktree gotcha**: editable-install `.pth` entries point at the *main*
   checkout. Inside a worktree, prepend the worktree's `src` dirs to `PYTHONPATH`
   and ensure compiled `.so` files exist before trusting smoke results.

### External Dependencies

| Dependency | Version | Notes |
|---|---|---|
| `openai` | existing | already required by every wire client; no new dep |
| `aiohttp` | existing | for `list_models()` — never `httpx`/`requests` |
| `navconfig` | existing | credential resolution |

**No new third-party dependencies.**

---

## 8. Open Questions

### Resolved (carried forward from the proposal)

- [x] **Protocol scope: Chat Completions only, or Responses too?** — *Resolved
  (U1)*: "all on this phase" — both ship in FEAT-526.
- [x] **Is a live key available; is contributor tier acceptable for tests?** —
  *Resolved (U2)*: "there is a live key available in env/.env and reachable by
  navconfig.config"; contributor is "only for synthetic e2e prompts and e2e
  testing (like tests we currently made for live openai)". Verified: 200 OK.
- [x] **Muse Image / Voice Transcribe / Messages API in scope?** — *Resolved
  (U3)*: out of scope; enum members reserved only.
- [x] **Which env var is the default?** — *Resolved*: "MODEL_API_KEY is too
  generic, using META_API_KEY as default in client." `MODEL_API_KEY` kept as a
  secondary fallback so upstream vendor examples work unmodified.
- [x] **Where should Responses-API support live?** — *Resolved (D1)*:
  recommendation accepted → **`MetaClient`-local**. `OpenAIBaseClient` keeps its
  "wire protocol only" charter; duplication accepted as reversible.
- [x] **Native `tool_search` vs. parrot's `search_tools`?** — *Resolved (D2)*:
  "map then together, at the end, tool_search based on proof is slower than
  parrot search." → Module 6, last and droppable; parrot's path stays default.

### Unresolved

- [x] **Should `MetaClient` be exported from `parrot/clients/__init__.py`?**
  Siblings are not (only `ZaiClient` is, inconsistently). *Owner*: tbd —
  safe to decide during implementation; defaulting to "no, match the majority": No

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules 2-3 both edit `clients/meta.py`, and Module 4 edits two
  shared test rosters. Parallel agents would contend on the same files for little
  gain. Module 1 (`models/meta.py`) is independent but too small to justify a
  second worktree.
- **Cross-feature dependencies**: none blocking. Watch
  `openai-max-completion-tokens` (§7 gotcha 8) for overlap.
- **Creation** (branch from `dev`, never `main`):
  ```bash
  git worktree add -b feat-FEAT-526-meta-llm-client \
    .claude/worktrees/feat-FEAT-526-meta-llm-client origin/dev
  ```

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-09-04 | Jesus | Initial spec from accepted proposal FEAT-526 (17 findings, 10 live API calls) |
