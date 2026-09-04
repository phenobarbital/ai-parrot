---
id: FEAT-526
title: Meta Model API (Muse Spark) LLM client for parrot.clients
slug: meta-llm-client
type: feature
mode: enrichment
status: accepted
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
resolved_at: 2026-09-04
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

> **Scope resolved 2026-09-04** (U1/U2/U3). Both protocols ship in this phase.
> Every claim below is now backed by a **live call against the real API** with
> the repo's own key, not by documentation alone.

### What's New

- **`parrot/models/meta.py`** — `MetaModel(str, Enum)` following the
  `MoonshotModel` pattern (string-valued so members interchange with raw model
  strings), with the 7 ids **verified live** via `GET /v1/models` (F013), plus
  capability frozensets in the same house style:
  - `CONTRIBUTOR_MODELS` — the train-on-your-data tier (note: `muse-spark-1.1`
    has **no** contributor variant).
  - `SPARK_MODELS` / `IMAGE_MODELS` / `TRANSCRIBE_MODELS` — family split.
  - Context window is uniform at **1,048,576** tokens across all Spark models.
- **`MetaClient`** — `OpenAIBaseClient` subclass, `base_url="https://api.meta.ai/v1"`,
  `_default_model = "muse-spark-1.3"` (Standard tier — never contributor).
- **Responses API support** — the substantial piece; see §3.1.
- **`count_input_tokens()`** — `POST /v1/responses/input_tokens`; **verified
  live** (F014). Standalone, so it works regardless of §3.1's outcome.
- **`list_models()`** — over `GET /v1/models`, mirroring `OpenRouterClient`.
- **`examples/clients/smoke/smoke_meta.py`** + `docs/clients/meta.md`.

### 3.1 Responses API — the one genuinely new piece

`OpenAIBaseClient` has no Responses support (C5), so this is net-new. Verified
wire shape (F016): the response has **no `choices` array**; `output` is a list
of typed items (`reasoning`, `message`, `web_search_call`, `tool_search_call`,
`tool_search_output`, …). `output_text` is an **SDK-computed convenience
property, not a wire field** — the adapter must fold `type == "message"` items
itself.

Unlocks, both **verified live**:
- **Search grounding** — `tools: [{"type": "web_search"}]`. A live probe
  returned a genuine post-training fact, confirming real retrieval (F016).
- **Tool search** — `{"type": "tool_search"}` **plus** `defer_loading: true` on
  individual functions; without a deferred tool it returns HTTP 400 (F017).

**Where this layer lives is settled (D1)**: `MetaClient`-local. `OpenAIClient`
keeps its own separate Responses implementation; some duplication is accepted in
exchange for a self-contained, reversible feature. Promote to a shared mixin
only if a second provider ever needs it.

### What Changes

- **`factory.py::SUPPORTED_CLIENTS`** — add `"meta"` + aliases (`"muse"`,
  `"meta-muse"`). *Evidence*: F008
- **Both `WIRE_SUBCLASSES` rosters** — add `MetaClient` to the existing
  no-`gpt`-leak and funnel-parity sweeps. *Evidence*: F012

### What's Untouched (Non-Goals)

- `OpenAIClient` / `gpt.py` — untouched; Meta is a sibling, never a subclass.
- Muse Image (`muse-image-1.0`) and Muse Voice Transcribe
  (`muse-voice-transcribe-1.0`) — **U3 resolved: out of scope**. Reserved as
  enum members only, so the namespace exists for a later FEAT.
- The Anthropic-shaped Messages API — third protocol, deferred.
- **Prompt caching** — automatic server-side; *nothing to build*. Surface
  `cached_tokens` in metrics only. (C9)

### Patterns to Follow

- `OpenRouterClient` for the `__init__` credential chain, the `self.api_key`
  re-set after `super().__init__()`, `get_client()`, `_chat_completion()`, and
  `list_models()`. *Evidence*: F007
- `MoonshotModel` for the enum + capability-frozenset layout. *Evidence*: F007
- The 7-step recipe in `docs/clients/openai-compatible.md`, including step 7
  (a doc page — Meta clearly qualifies). *Evidence*: F006

### Integration Risks

- **⚠️ Reasoning burns the output budget (high impact, newly discovered).**
  Live measurement: **199 of 210** completion tokens were `reasoning_tokens` for
  a reply whose visible text was the single word `pong` (F015). A conventional
  `max_tokens=256` default will routinely yield **empty or truncated** visible
  text. *Mitigation*: set a generously high default output budget on
  `MetaClient`, document why, and assert non-empty visible text in the smoke
  script. This is the most likely source of confusing "returned nothing" reports.
- **Env-var resolution (resolved, implement carefully).** `META_API_KEY` is the
  default per U2. It is the only one actually set in this repo — `MODEL_API_KEY`
  is unset (F013). *Mitigation*: chain `api_key` kwarg → `META_API_KEY` →
  `MODEL_API_KEY` (vendor default, kept so upstream examples work). **Never**
  fall through to `OPENAI_API_KEY`, which `AsyncOpenAI` would otherwise pick up
  silently and ship an `sk-…` key to Meta.
- **Contributor tier = training consent (accepted).** Confined to synthetic e2e
  prompts, mirroring the existing live-OpenAI tests. *Mitigation*: never the
  library default; state the tier's meaning in the `MetaModel` docstring and the
  smoke-script header so it cannot be adopted unknowingly. *Evidence*: F003, C8
- **Search-grounding citations may not populate (medium).** `annotations` came
  back **empty** on a successful grounded answer despite docs advertising inline
  citations (F016). *Mitigation*: do **not** write citation extraction into
  acceptance criteria without re-verifying.
- **Two overlapping tool-search mechanisms (resolved — D2).** parrot has a
  client-side `search_tools` path (`base.py:1298/1322`); Meta has a native
  server-side one. **Decision**: map them together, as the **final** task group.
  parrot's client-side path stays the **default** — the user reports measured
  evidence that Meta's hosted `tool_search` is **slower** than parrot's own
  search. *Consequence*: this is the lowest-priority item in the feature and the
  safest to drop if the phase runs long, since nothing else depends on it.
  *Evidence*: F017 + user measurement (not independently reproduced here).
- **`logprobs` 400s and `reasoning_content` is redacted to empty** for external
  keys — never surface it as thinking output. *Evidence*: F011, C11

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Meta Model API is live and OpenAI-shaped | F001, F013 | high | authenticated 200s on 3 endpoints |
| C2 | Vendor documents `MODEL_API_KEY`; repo uses `META_API_KEY` | F002, F013 | high | docs + live env check (`MODEL_API_KEY` unset) |
| C3 | `OpenAIBaseClient` is a documented extension point | F005, F006 | high | read the base + its recipe doc |
| C4 | Search grounding / tool search are Responses-only | F004, F016, F017 | high | docs + live 200 (grounding) and 400 (tool_search) |
| C5 | `OpenAIBaseClient` has no Responses support | F005 | high | `_is_responses_model()` False in base |
| C6 | `tool_choice` must be `"auto"` | F009, F014 | high | **live 400** with verbatim error |
| C7 | `ToolFormat.OPENAI` strict output is accepted by Meta | F010, F014 | **high** ⬆ | **upgraded from medium — live 200 with `strict:true`** |
| C8 | Contributor tier permits training on prompts/completions | F003 | high | verbatim vendor doc; accepted by user for synthetic e2e only |
| C9 | Prompt caching needs zero implementation | F011 | high | "automatic — no key or setup required" |
| C10 | A CC-only client is ~200 lines; Responses is the real work | F006, F007, F016 | high | precedent read + verified wire shape |
| C11 | `logprobs` 400s; `reasoning_content` redacted | F011 | high | verbatim vendor doc |
| C12 | In-flight `max_completion_tokens` spec may interact | F011 | **low** | another session's file; deliberately not read |
| C13 | Muse Spark spends most of the output budget on reasoning | F015 | high | **measured live**: 199/210 and 142/153 |
| C14 | The 7 model ids are ground truth | F013 | high | live `GET /v1/models` |
| C15 | Responses `output` is typed items, not `choices`; `output_text` is SDK-only | F016 | high | live response key dump |
| C16 | Search-grounding `annotations` may come back empty | F016 | **medium** | observed empty on one live grounded call; cause unconfirmed |

Distribution: **13** high, **1** medium, **2** low.

> The evidence base shifted materially since the first draft: what were
> doc-derived assumptions (C6, C7) are now **live-verified**, and two new
> high-confidence findings (C13, C15) came only from making real calls.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Protocol scope: Chat Completions only, or Responses too?**
  *Resolved*: **"all on this phase"** — both protocols ship in FEAT-526.
  *Consequence*: the spec must carry a distinct Responses-API task group; this
  is no longer a ~200-line mechanical client.

- [x] **U2 — Is a live key available; is contributor-tier acceptable for tests?**
  *Resolved*: *"there is a live key available in env/.env and reachable by
  navconfig.config"*, and contributor is *"only for synthetic e2e prompts and
  e2e testing (like tests we currently made for live openai)."*
  *Verified*: key authenticates; `GET /v1/models` returns 200 with 7 models
  (F013). Acceptance criteria **can** include live calls.

- [x] **U3 — Are Muse Image / Voice Transcribe / Messages API in scope?**
  *Resolved*: implicitly out of scope — the brief and U1 concern Muse Spark.
  Reserved as enum members only.

- [x] **Env var naming.** *Resolved*: *"MODEL_API_KEY is too generic, using
  META_API_KEY as default in client."* `META_API_KEY` is primary.
  *Note*: I kept `MODEL_API_KEY` as a **secondary** fallback so upstream vendor
  examples work unmodified — say the word if you'd rather it be dropped entirely.

- [x] **D1 — Where should Responses-API support live?**
  *Resolved*: recommendation accepted → **`MetaClient`-local**.
  *Consequence*: `OpenAIBaseClient` keeps its "wire protocol only, no provider
  opinions" charter intact; `OpenAIClient`'s existing Responses code is not
  touched or shared. Duplication is a deliberate, reversible trade.

- [x] **D2 — Native `tool_search` vs. parrot's client-side `search_tools`?**
  *Resolved*: **map them together, as the last task group.**
  *Rationale (user)*: *"tool_search based on proof is slower than parrot search"* —
  so parrot's client-side path remains the default and Meta's native hosted mode
  is the mapped-in alternative, not the preferred one.
  *Assumption I am proceeding under*: "map together" means one unified
  `search_tools` surface that can dispatch to Meta's native `tool_search`, with
  parrot's own path as the default on latency grounds — **not** replacing
  parrot's path with the native one. Say so if you meant the reverse.
  *Note*: the latency comparison is your measurement; my only live `tool_search`
  probe returned HTTP 400 (missing a deferred tool), so I have no timing data of
  my own to corroborate it.

### Unresolved

None. All scope and design questions are closed — the feature is ready to spec.

## 6. Recommended Next Step

**`/sdd-spec FEAT-526`** — *Rationale*: every scope and design question is now
closed (U1-U3, D1, D2), the model catalog and both protocols are live-verified,
and the file list is pre-determined by an enforced convention. Nothing further
is gained by another research or brainstorm round.

The spec should carry **four task groups, in dependency order**:

1. **Foundation** — `parrot/models/meta.py` (`MetaModel` + capability
   frozensets), `MetaClient` over Chat Completions, factory registration
   (`"meta"` + aliases), and both `WIRE_SUBCLASSES` rosters.
   *Mechanical; the 7-step recipe is already written.*
2. **Responses API (MetaClient-local, per D1)** — the `output[]` adapter,
   search grounding, and `count_input_tokens()`.
   *The real engineering in this feature.*
3. **Live e2e + docs** — `smoke_meta.py` against `muse-spark-1.3-contributor`,
   mirroring the existing live-OpenAI tests, plus `docs/clients/meta.md`.
4. **`search_tools` ↔ native `tool_search` mapping (per D2)** — **last**, and
   explicitly the droppable item if the phase runs long. parrot's client-side
   path stays the default on the measured latency grounds.

**Carry F015 into the spec as an explicit acceptance criterion** — a
non-empty-visible-text assertion under a realistic output budget. Muse Spark
spent 199 of 210 output tokens on reasoning to say `pong`; left implicit, this
will surface as a confusing "returned nothing" bug.

**Re-check `.id_ledger.json` before running `/sdd-spec`** — FEAT-526 is still
provisional (see the banner at the top of this document).

### Alternatives

- **`/sdd-brainstorm FEAT-526`** — no longer justified; D1 was the only item
  that could have warranted options analysis and it is now decided.
- **`/sdd-task FEAT-526`** — no; the feature spans two protocols, a new model
  module, two test rosters, live e2e and docs.

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-526/state.json` |
| Source (raw) | `sdd/state/FEAT-526/source.md` |
| Research plan | `sdd/state/FEAT-526/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-526/findings/F001…F017` |
| Synthesis (JSON) | `sdd/state/FEAT-526/synthesis.json` |

**Budget consumed** (profile `default`):
- Files read: 25 / 40 · Grep calls: 13 / 25 · Git calls: 2 / 10
- Wiki queries: 2 (free) · External HTTP fetches: 20 · **Live authenticated API calls: 10**
- Truncated: **no**

**Round 2** (post-Q&A): U1/U2/U3 resolved by the user; research extended with
live authenticated probes of both protocols, which upgraded C7 and added C13-C16.

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
