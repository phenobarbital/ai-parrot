---
id: FEAT-526
title: Meta Model API (Muse Spark) LLM client for parrot.clients
slug: meta-llm-client
type: feature
mode: enrichment
status: discussion
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-04
  summary_oneline: New parrot LLM client for Meta Model API (Muse Spark), OpenAI-wire compatible
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-526/
created: 2026-09-04
updated: 2026-09-04
---

# FEAT-526 — Meta Model API (Muse Spark) LLM client

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user brief, 2026-09-04
> **Audit**: [`sdd/state/FEAT-526/`](../state/FEAT-526/)

> ⚠️ **Provisional FEAT-ID.** `scripts/sdd/reserve_ids.py` refused to run because
> the shared main checkout carries uncommitted changes belonging to another
> session. `FEAT-526` matches `.id_ledger.json`'s `next_feature_id` as of
> writing, but **`/sdd-spec` must perform the authoritative reservation** — and
> may land on a different number if another session reserves first.

---

## 0. Origin

Add a first-class parrot client for **Meta Model API** — Meta's hosted
inference service for the **Muse Spark** model family — reachable with the
OpenAI SDK pointed at `https://api.meta.ai/v1`.

The brief asks for coverage of seven capabilities (tool calling, tool search,
search grounding, structured output, prompt caching, token counting, chat
completion), a `META_API_KEY` env default, and `muse-spark-1.3-contributor`
for end-to-end tests.

Verbatim source: [`sdd/state/FEAT-526/source.md`](../state/FEAT-526/source.md).

---

## 1. Synthesis Summary

The platform is **real and externally verified**, not taken on faith from the
brief: `GET https://api.meta.ai/v1/models` returns HTTP 401 with a verbatim
OpenAI error envelope, and the full documentation set is machine-readable at
`https://dev.meta.ai/docs/llms.txt` (every page also serves as Markdown by
appending `.md`). Fifteen protocol/capability pages were fetched and read
(F001).

The repo turns out to have a **purpose-built landing zone**. FEAT-438
introduced `OpenAIBaseClient` — a neutral OpenAI-wire layer carrying zero
OpenAI-provider defaults — with eight existing subclasses and a documented,
test-enforced seven-step recipe for adding a ninth (F005, F006). A
Chat-Completions `MetaClient` is therefore a near-mechanical ~200-line subclass
modelled on `OpenRouterClient` (F007, C10).

**The one real fork is protocol scope.** Meta exposes three wire formats, and
capability access is *not* uniform across them (F004):

| Requested capability | Chat Completions | Status |
|---|---|---|
| Chat completion | ✅ | reachable today |
| Tool calling | ✅ | reachable today |
| Structured output | ✅ `response_format` | reachable today |
| Prompt caching | ✅ automatic | **nothing to implement** (C9) |
| **Search grounding** | ❌ | **Responses API only** |
| **Tool search** | ❌ | **Responses API only** |
| **Token counting** | ❌ | separate endpoint `/v1/responses/input_tokens` |

`OpenAIBaseClient` has **no Responses API support** — `_is_responses_model()`
returns `False` in the base, and the docs are explicit that *"only
`OpenAIClient` has a Responses API to route to"* (C5). So three of the seven
requested capabilities are net-new architectural work, not configuration, and
a fourth (token counting) needs a bespoke endpoint call.

Two compatibility checks came back **clean**, which meaningfully de-risks the
Chat Completions path: parrot's shared funnel already emits `tool_choice="auto"`
(Meta rejects every other value with HTTP 400 — C6), and already sends
`max_tokens` rather than `max_completion_tokens` (C11).

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Role | Evidence |
|---|------|--------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/clients/meta.py` | `MetaClient` | **NEW** — provider subclass of `OpenAIBaseClient` | F005, F006, F007 |
| 2 | `packages/ai-parrot/src/parrot/models/meta.py` | `MetaModel` | **NEW** — model-id enum + tier metadata | F003, F007 |
| 3 | `packages/ai-parrot/src/parrot/clients/factory.py` | `SUPPORTED_CLIENTS` | register `"meta"` + aliases | F008 |
| 4 | `packages/ai-parrot/src/parrot/clients/openai_base.py` | `_chat_completion` (:639, :643, :979, :983) | shared funnel — already Meta-legal | F005, F009, F011 |
| 5 | `packages/ai-parrot/src/parrot/clients/base.py` | `_make_openai_strict_tool` (:1269-1293, :1399) | strict-schema normalizer | F010 |
| 6 | `tests/clients/test_openai_compatible_defaults.py` | `WIRE_SUBCLASSES` | roster to extend | F012 |
| 7 | `tests/clients/test_openai_base_parity.py` | `WIRE_SUBCLASSES` | roster to extend | F012 |
| 8 | `examples/clients/smoke/smoke_meta.py` | — | **NEW** — credential-gated smoke script | F012 |

### 2.2 Constraints Discovered

- **The no-`gpt-*`-defaults rule.** `OpenAIBaseClient` and every subclass except
  `OpenAIClient` MUST NOT set `_default_model` / `_fallback_model` /
  `_lightweight_model` to an OpenAI id. Enforced by
  `test_openai_compatible_defaults.py`. *Implication*: `MetaClient` sets
  `_default_model = "muse-spark-1.3"` and leaves the rest unset.
  *Evidence*: F005, F006

- **The single-funnel contract.** Every wire call (`ask`, `ask_stream`,
  `resume`, `invoke`) must route through `_chat_completion(...)`.
  *Implication*: any Meta-specific payload shaping goes in one override, not
  four. *Evidence*: F005

- **`tool_choice` must be `"auto"`.** `"none"`, `"required"` and named choices
  return HTTP 400. parrot's funnel already complies — this is a confirmation,
  but it constrains any future caller trying to force a tool.
  *Evidence*: F009

- **Strict-schema subset.** parrot always sends `strict: true` for
  `ToolFormat.OPENAI`. Meta accepts it (unlike Groq, which forced a separate
  `ToolFormat.GROQ`), but then enforces its subset: no `allOf`/`oneOf`
  anywhere, `anyOf` below root only, `additionalProperties: false`, full
  `required`. `$ref`-cycles are rejected on every surface regardless.
  *Implication*: inherit `ToolFormat.OPENAI`, but test with a real
  toolkit schema. *Evidence*: F010

- **Credentials via `navconfig`.** Sibling clients resolve keys through
  `config.get(...)`, not `os.environ`, and re-assign `self.api_key` after
  `super().__init__()` because `AbstractClient` may overwrite it.
  *Evidence*: F007

- **`logprobs` is unsupported** (HTTP 400) and **`reasoning_content` is
  redacted to empty** for external keys on Chat Completions — it must not be
  surfaced as thinking output. *Evidence*: F011

### 2.3 Recent History (Relevant)

No `git log` was run against the target paths — the files at #1, #2 and #8 do
not exist yet, and #4/#5 are FEAT-438 infrastructure whose current state was
read directly rather than inferred from history. Absence of history research is
noted rather than papered over.

One live signal from the working tree: `sdd/specs/openai-max-completion-tokens.spec.md`
is **currently modified by another session** and concerns output-token
parameters for reasoning models — plausibly interacting with this work (C12,
low confidence: the file was not read, as it is another session's in-flight
work).

---

## 3. Probable Scope

### What's New

- **`MetaClient`** — `OpenAIBaseClient` subclass; `base_url="https://api.meta.ai/v1"`,
  `client_type = client_name = "meta"`, `_default_model = "muse-spark-1.3"`.
- **`MetaModel` enum** — the five Muse Spark ids plus tier metadata, mirroring
  `parrot/models/openrouter.py`.
- **`list_models()`** — over `GET /v1/models` (Meta returns newest-first with a
  `created` timestamp), following `OpenRouterClient.list_models()`.
- **`smoke_meta.py`** — credential-gated, three legs (`ask`, `ask` + `@tool`,
  `invoke`).

### What Changes

- **`factory.py::SUPPORTED_CLIENTS`** — add `"meta"` and aliases (`"muse"`,
  `"meta-muse"`). Direct import is fine; the client needs only the `openai`
  SDK already used by sibling wire clients. *Evidence*: F008
- **Both `WIRE_SUBCLASSES` rosters** — add `MetaClient` so the existing
  no-`gpt`-leak and funnel-parity sweeps cover it. *Evidence*: F012

### What's Untouched (Non-Goals)

- `OpenAIClient` / `gpt.py` — untouched; Meta is a sibling, never a subclass.
- `AbstractClient` — no changes needed for the Chat Completions path.
- Muse Image, Muse Voice Transcribe, Muse Glimmer — separate model families
  with separate endpoints (F003); out of scope unless U3 says otherwise.
- The Anthropic-shaped Messages API — a third protocol, deliberately deferred.
- **Prompt caching** — automatic server-side; *nothing to build*. At most,
  surface `usage.prompt_tokens_details.cached_tokens` in metrics. (C9)

### Patterns to Follow

- `OpenRouterClient` end-to-end — `__init__` credential chain, the
  `self.api_key` re-set, `get_client()`, `_chat_completion()` override,
  `list_models()`. *Evidence*: F007
- The seven-step recipe in `docs/clients/openai-compatible.md`, including its
  step 7 (add a doc page for providers with real provider-specific surface —
  Meta qualifies). *Evidence*: F006

### Integration Risks

- **Env-var divergence (certain).** The brief asks for `META_API_KEY`; Meta
  documents `MODEL_API_KEY`. *Mitigation*: resolve a chain —
  `api_key` kwarg → `META_API_KEY` → `MODEL_API_KEY`. Never fall through to
  `OPENAI_API_KEY`, which the OpenAI SDK would otherwise pick up silently and
  send a `sk-…` key to Meta. *Evidence*: F002
- **Contributor-tier data governance (high impact).** `muse-spark-1.3-contributor`
  buys a discount with *permission for Meta to train on your prompts and
  completions*. *Mitigation*: fine for synthetic e2e prompts; must never be the
  library default, and the tier's meaning belongs in the `MetaModel` enum
  docstring and the smoke script header, not buried in a spec. *Evidence*: F003, C8
- **Strict-schema 400s (medium).** A tool whose schema uses `allOf`/`oneOf` or a
  `$ref` cycle will 400 under `strict: true` where omitting `strict` would pass.
  *Mitigation*: parity test with a real toolkit schema; if it bites, the escape
  hatch is a Meta-specific tool format, as Groq needed. *Evidence*: F010, C7
- **Capability shortfall vs. the brief (certain).** Shipping Chat Completions
  only delivers 4 of the 7 requested capabilities. *Mitigation*: U1 — decide
  scope explicitly rather than discovering it at review.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Meta Model API is live and OpenAI-shaped | F001 | high | direct HTTP probe; verbatim OpenAI error envelope |
| C2 | Documented env var is `MODEL_API_KEY`, not `META_API_KEY` | F002 | high | stated twice in vendor docs |
| C3 | `OpenAIBaseClient` is a documented extension point | F005, F006 | high | read the base + its recipe doc |
| C4 | Search grounding / tool search / custom tools are Responses-only | F004 | high | explicit vendor statements, quoted |
| C5 | `OpenAIBaseClient` has no Responses support | F005 | high | `_is_responses_model()` False in base, per doc |
| C6 | parrot's `tool_choice="auto"` is already Meta-legal | F009 | high | grep confirmed at openai_base.py:639/979 |
| C7 | `ToolFormat.OPENAI` strict output conforms to Meta's subset | F010 | **medium** | subsets align by vendor's own statement, but not verified against a real tool schema |
| C8 | Contributor tier permits training on prompts/completions | F003 | high | verbatim vendor doc |
| C9 | Prompt caching needs zero implementation | F011 | high | "automatic — no key or setup required" |
| C10 | CC-only `MetaClient` is ~200 lines, mechanical | F006, F007 | high | direct analogy to a read precedent |
| C11 | `logprobs` 400s; `reasoning_content` redacted | F011 | high | verbatim vendor doc |
| C12 | In-flight `max_completion_tokens` spec may interact | F011 | **low** | file modified by another session; not read |

Distribution: **9** high, **1** medium, **2** low.

> The two sub-high claims (C7, C12) are *risk* claims, not load-bearing ones —
> the recommendation holds whichever way they resolve.

---

## 5. Open Questions

### Unresolved (need a decision before `/sdd-spec`)

- [ ] **U1 — Protocol scope: Chat Completions only, or Responses API too?**
  *Blocks*: the whole shape of the feature. *Owner*: tbd
  *Plausible answers*:
  a) **CC only** — ships fast (~200 lines, mechanical), delivers chat, tools,
     structured output, caching. Defers search grounding + tool search to a
     follow-up FEAT.
  b) **CC + Responses** — delivers all seven, but means building Responses
     support at the `OpenAIBaseClient` layer (or in `MetaClient`), which is
     genuinely new architecture and much larger.
  c) **CC now, Responses as a second phase in the same spec** — one spec, two
     task groups, reviewable independently.

- [ ] **U2 — Is a live API key available, and is contributor-tier acceptable for tests?**
  *Blocks*: the "real test usage" part of the brief. *Owner*: tbd
  *Context*: neither `META_API_KEY` nor `MODEL_API_KEY` is set in this
  environment (checked). Keys look like `LLM|<id>|<secret>`.
  *Plausible answers*: a) key exists, contributor tier fine for synthetic
  prompts · b) key exists, use Standard `muse-spark-1.3` instead ·
  c) no key yet — ship mocked tests + a skipping smoke script (the established
  pattern for all 8 existing wire clients).

- [ ] **U3 — Are Muse Image / Muse Voice Transcribe / Messages API in scope?**
  *Owner*: tbd
  *Plausible answers*: a) out of scope, text only · b) reserve namespace in the
  model enum now, implement later · c) in scope.

> No questions were put to the user during the research phase — the pipeline's
> Q&A gate is where these belong, and all three are genuine scope decisions
> that the codebase cannot answer.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-526`** — *Rationale*: localization is high-confidence, the
extension point is documented and test-enforced, and the file list is
effectively pre-determined by existing convention. There is no architectural
fork worth a brainstorm — U1 is a **scoping** decision (how much to build), not
an **architecture** decision (how to build it).

**Answer U1 and U2 first**; they change the spec's task count substantially,
and U2 determines whether acceptance criteria can include live calls.

### Alternatives

- **`/sdd-brainstorm FEAT-526`** — justified *only* if U1 resolves to (b) and
  you want to explore how Responses-API support should be layered
  (`OpenAIBaseClient` vs. `MetaClient`-local vs. a new `ResponsesMixin`) — that
  genuinely is an architectural fork worth options analysis.
- **`/sdd-task FEAT-526`** — not recommended; even the CC-only path spans a new
  client, a new model module, factory registration, two test rosters and a
  smoke script.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-526/state.json` |
| Source (raw) | `sdd/state/FEAT-526/source.md` |
| Research plan | `sdd/state/FEAT-526/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-526/findings/F001…F012` |
| Synthesis (JSON) | `sdd/state/FEAT-526/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 21 / 40 · Grep calls: 9 / 25 · Git calls: 2 / 10
- Wiki queries: 2 (free) · External HTTP fetches: 20
- Truncated: **no**

**Mode determination**: `auto` → **enrichment** (net-new capability, no failure
symptom in the source).

**Tooling note**: `WebFetch`/`WebSearch` were unavailable this session (their
summarizer model returned "may not exist or you may not have access"); external
research was done with `curl` against the vendor's `.md` documentation endpoints
instead. This is *better* evidence, not worse — raw source text rather than a
model's summary of it.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` |
| Operator | Claude Opus 5 (1M context), session 2026-09-04 |
| Branch | `dev` |
| ID status | **provisional** — ledger reservation deferred to `/sdd-spec` |
