---
type: Wiki Overview
title: FEAT-181 — Provider-agnostic prompt caching via PromptBuilder + AGENT_CONTEXT
  loader
id: doc:sdd-proposals-agnostic-prompt-caching-abstraction-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Verbatim source preserved at `sdd/state/FEAT-181/source.md`.
---

---
id: FEAT-181
title: Provider-agnostic prompt caching via PromptBuilder + AGENT_CONTEXT loader
slug: agnostic-prompt-caching-abstraction
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-18
  summary_oneline: Agnostic prompt-caching abstraction across LLM providers (Anthropic, OpenAI, Gemini)
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-181/
created: 2026-05-18
updated: 2026-05-18
---

# FEAT-181 — Provider-agnostic prompt caching via PromptBuilder + AGENT_CONTEXT loader

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: inline (design conversation while scoping `GitHubReviewer` repo context)
> **Audit**: [`sdd/state/FEAT-181/`](../state/FEAT-181/)

---

## 0. Origin

Verbatim source preserved at `sdd/state/FEAT-181/source.md`.

> Agnostic prompt caching abstraction across LLM providers. User wants a
> `prompt_caching=True` flag at the Agent level that each `AbstractClient`
> subclass (Anthropic, OpenAI, Gemini, possibly Groq/Vertex/HuggingFace)
> negotiates with its provider in its own way. Anthropic uses explicit
> `cache_control` blocks. OpenAI uses automatic prompt caching on
> prefixes ≥1024 tokens. Gemini uses an explicit `CachedContent` resource
> with high minimum token thresholds. The abstraction should live in a
> `PromptBuilder` (location TBD). The `PromptBuilder` should also load a
> repo-level context document (`AGENT_CONTEXT.md`) from a configuration
> directory, with in-memory caching invalidated by mtime. This came up
> while designing the `GitHubReviewer` agent.

**Initial signals**:
- Verbs: *implement*, *add*, *integrate*, *negotiate*, *cache* → enrichment.
- Named entities: `PromptBuilder`, `AbstractClient`, `Agent`, `Anthropic`,
  `OpenAI`, `Gemini`, `AGENT_CONTEXT.md`, `GitHubReviewer`.
- Polarity: positive (additive, not bug-shaped).
- Acceptance criteria provided: no.

---

## 1. Synthesis Summary

A fully-featured `PromptBuilder` already exists at
`parrot/bots/prompts/builder.py:20` with a two-phase render (CONFIGURE
once, REQUEST per call), and `AbstractBot` already accepts it as a kwarg.
This feature extends that machinery rather than inventing a new one: a
`prompt_caching: bool = False` flag on `PromptBuilder` + `AbstractBot`
turns on a new `build_segments()` output (cacheable vs non-cacheable
segments, derived from `RenderPhase`); each `AbstractClient` subclass
translates segments to its native primitive — Anthropic `cache_control`
blocks, OpenAI `prompt_cache_key`, Gemini `CachedContent` resource — and
degrades to a debug-level no-op when the provider can't or won't cache.
A sibling `AGENT_CONTEXT_LAYER` ships behind the same flag, lazily
loading `<AGENT_CONTEXT_DIR>/<agent_id>.md` with mtime-based invalidation
(mirroring `parrot/stores/kb/local.py`) so repeat agent runs reuse the
cached doc.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-181/findings/`.
> **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/bots/prompts/builder.py` | `PromptBuilder` | 20-241 | Existing builder with two-phase render — extended with cache flag and `build_segments()` | F001 |
| 2 | `packages/ai-parrot/src/parrot/bots/prompts/__init__.py` | re-exports | 8-49 | Public API surface for new methods/presets | F001 |
| 3 | `packages/ai-parrot/src/parrot/bots/prompts/presets.py` | `_PRESETS` registry | 15-41 | Preset wiring (no new preset needed under chosen policy U3) | F001 |
| 4 | `packages/ai-parrot/src/parrot/clients/base.py` | `AbstractClient` | 242-353, 775-830, 1432, 1470 | Receives the optional segmented system-prompt parameter | F002, F009 |
| 5 | `packages/ai-parrot/src/parrot/clients/claude.py` | `messages.create` payload sites | 188-235, 222, 231, 431, 594, 982-986, 1015, 1127, 1214, 1284, 1359, 1460, 1531, 1546 | 13+ Anthropic call sites converging on `payload["system"] = system_prompt` | F003 |
| 6 | `packages/ai-parrot/src/parrot/clients/gpt.py` | `chat.completions` / `responses` | 274, 470-495, 1444-1460, 1653, 2167, 2452 | OpenAI call sites — adds optional `prompt_cache_key` | F003 |
| 7 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `aio.models.generate_content` | 2273, 2890, 3453, 3713, 3739, 3770 | Primary Gemini call sites | F003 |
| 8 | `packages/ai-parrot/src/parrot/clients/google/analysis.py` | `generate_content` wrappers | 96, 173, 411, 580, 764, 773, 958, 1018, 1076, 1145 | Analysis-side Gemini call sites | F003 |
| 9 | `packages/ai-parrot/src/parrot/clients/google/generation.py` | `generate_content` partials | 362, 506, 1592, 1798, 2104 | Generation-side Gemini call sites | F003 |
| 10 | `packages/ai-parrot/src/parrot/clients/groq.py` | `chat.completions.create` | 399, 498, 541, 687, 804, 883, 952, 1067, 1184, 1297, 1322, 1345 | OpenAI-compatible; no documented native cache — no-op | F003 |
| 11 | `packages/ai-parrot/src/parrot/clients/grok.py` | `chat.completions.create` | 789 | OpenAI-compatible; same no-op stance | F003 |
| 12 | `packages/ai-parrot/src/parrot/bots/abstract.py` | `AbstractBot.__init__` | 155-186, 247-309, 1042-1118, 2543-2650 | Already takes `prompt_builder`; gets a new `prompt_caching` kwarg | F004 |
| 13 | `packages/ai-parrot/src/parrot/bots/agent.py` | default builder wiring | 14, 110-117, 1256 | `PromptBuilder.agent()` default — benefits with zero subclass changes | F004 |
| 14 | `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | `GitHubReviewer` | 193-215, 269, 383-387, 941-958, 1472-1511 | Canonical consumer; opts in via `prompt_caching=True` | F005 |
| 15 | `packages/ai-parrot/src/parrot/conf.py` | BASE_DIR-based dirs | 5-160 | Home for new `AGENT_CONTEXT_DIR` constant | F007 |
| 16 | `packages/ai-parrot/src/parrot/stores/kb/local.py` | mtime tracking | 180, 195, 248, 481 | Pattern to mirror for `AgentContextLoader` | F008 |
| 17 | `packages/ai-parrot/src/parrot/registry/routing/cache.py` | async-safe LRU | 3, 59 | Pattern if loader is touched from async code | F008 |

### 2.2 Constraints Discovered

- **PromptBuilder.build() returns a single string today.**
  *Implication*: Add a NEW method `build_segments() -> List[CacheableSegment]`
  instead of mutating the return type; the ~10 downstream callers
  (`agent.py`, `voice.py`, `jira_specialist.py`, `data.py`,
  `database/agent.py`, `database/prompts.py`, registry routing) must
  continue to work unchanged.
  *Evidence*: F001

- **AbstractClient API was just stabilized** via the
  `homologate-llm-clients-askstream` initiative (TASK-1173..TASK-1180)
  and `FEAT-176 lifecycle-events-system`.
  *Implication*: DO NOT change the existing
  `system_prompt: Optional[str]` signature on `complete/ask/ask_stream`;
  accept `Union[str, List[CacheableSegment]]` or add a sibling
  `system_prompt_segments` parameter. Cache plumbing must compose with
  the existing `_emit_before_call` / `_emit_after_call`.
  *Evidence*: F002, F009

- **Anthropic** requires the system field to be a list of content blocks
  (not a string) to attach `cache_control`. Hard limit of **4
  `cache_control` blocks per request**.
  *Implication*: Per-call translator must aggregate cacheable segments
  into ≤4 blocks; v1 should mark at most 1–2 blocks (AGENT_CONTEXT +
  identity-section), leaving headroom for future use.
  *Evidence*: F003

- **Gemini** uses an explicit `CachedContent` resource created via a
  separate `client.caches.create(...)` call before `generate_content`,
  with a minimum token threshold of ≥4096 tokens (≥32k for some Flash
  variants).
  *Implication*: Translation must be conditional; estimate token count
  and skip with a debug log + `PromptCacheSkippedEvent(reason="below_threshold")`
  when threshold not met. The feature must be **best-effort per provider
  and must never raise** because of provider limitations.
  *Evidence*: F003

- **GitHubReviewer's default model is `GoogleModel.GEMINI_3_FLASH_PREVIEW`**
  — the provider with the highest minimum cache threshold.
  *Implication*: The motivating consumer may not actually cache on its
  default model unless `AGENT_CONTEXT.md` + static system prompt exceed
  the threshold. Document this honestly in the spec; the canonical demo
  may need to use Anthropic or OpenAI.
  *Evidence*: F005

- **navconfig convention**: project paths are declared in `parrot/conf.py`
  via `config.get('X_DIR', fallback=BASE_DIR.joinpath('x'))`. The
  `fallback=` keyword (NOT `default=`) is mandatory per the navconfig
  Kardex contract recorded in memory.
  *Implication*: Add `AGENT_CONTEXT_DIR = config.get('AGENT_CONTEXT_DIR',
  fallback=BASE_DIR.joinpath('agent_context'))` and use it consistently
  across the loader and any documentation.
  *Evidence*: F007

- **`functools.lru_cache` silently misbehaves on async methods** (project
  has a custom async-safe LRU at `registry/routing/cache.py`).
  *Implication*: The `AgentContextLoader` read must be a sync function
  decorated with `@functools.lru_cache(maxsize=None)` keyed on
  `(path, st_mtime)`. If called from async code, wrap with
  `asyncio.to_thread(...)` — never decorate an async function with
  `lru_cache`.
  *Evidence*: F008

- **Lifecycle events from FEAT-176** are integrated into `AbstractClient`
  with `BeforeClientCallEvent` / `AfterClientCallEvent` / `ClientCallFailedEvent`
  and the privacy-safe `_system_prompt_hash`.
  *Implication*: Emit `PromptCacheAppliedEvent(provider, blocks, est_tokens)`
  and `PromptCacheSkippedEvent(provider, reason)` from the same
  emit-before/after lifecycle so cache cost/benefit is observable per
  call. Mirror the `_system_prompt_hash` pattern when surfacing segment
  identity (hash the content, never emit it raw).
  *Evidence*: F002, F009

- **Zero prior prompt-caching code in `parrot/`** (green field).
  *Implication*: No migration constraints — but no in-repo prior art to
  course-correct against either; the spec must be precise on the API
  surface.
  *Evidence*: F006

### 2.3 Recent History (Relevant)

Last 60 days on the two affected trees:

| Commit | When | Theme |
|--------|------|-------|
| `2b146f86` | recent | fix(lifecycle-events-system): address all code review issues |
| `47c68d22` | recent | feat(lifecycle-events-system): TASK-1194 — Integrate EventEmitterMixin into AbstractClient |
| `04fb6df3..d965c701` | recent | feat(homologate-llm-clients-askstream): TASK-1173..1180 (8 commits across all clients) |
| `30c92a37` | very recent | new method: build weekly summary from reviewer (FEAT-180) |
| `d65f5073..95331871` | recent | GitHubReviewer landed (renamed from GitHubPRReviewer) |
| `f72eea31` | recent | feat(github-pr-reviewer): add autonomous PR reviewer agent |

Two large initiatives just stabilized the integration surface; no
in-flight refactors compete for the seam this feature touches.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`CacheableSegment`** dataclass — `(text: str, cacheable: bool,
  ttl_hint: Optional[Literal['short','long']] = None)`. Represents one
  chunk of the system prompt with a cache-eligibility flag.
  *Location*: `packages/ai-parrot/src/parrot/bots/prompts/segments.py`
  (new) or inlined in `builder.py`.

- **`PromptBuilder.build_segments(context) -> List[CacheableSegment]`** —
  new method that derives the cache boundary from `layer.phase`
  (`RenderPhase.CONFIGURE` → cacheable, `RenderPhase.REQUEST` → not).
  *Location*: `packages/ai-parrot/src/parrot/bots/prompts/builder.py`.

- **`PromptLayer.cacheable: bool`** attribute on the existing `PromptLayer`
  with a default derived from `phase` (overridable per-layer).
  *Location*: `packages/ai-parrot/src/parrot/bots/prompts/layers.py`.

- **`prompt_caching: bool = False`** flag — on both `PromptBuilder.__init__`
  and `AbstractBot.__init__`. Boolean, not enum (per resolved U2 below):
  silent degradation is the right default; consumers wanting a `force`
  semantic can be added later.
  *Location*: `parrot/bots/prompts/builder.py` + `parrot/bots/abstract.py`.

- **Per-client cache translator** — an abstract method
  `_apply_cache_hints(payload, segments) -> payload` on `AbstractClient`,
  overridden per subclass:
  - `claude.py` — aggregate cacheable segments into ≤4 system content
    blocks with `cache_control={'type':'ephemeral'}`; v1 marks at most 1–2.
  - `gpt.py` — emit a deterministic `prompt_cache_key = sha256(cacheable_segments)`
    mirroring the `_system_prompt_hash` pattern; no shape change to the
    messages list.
  - `google/client.py` (+ `analysis.py` + `generation.py`) — estimate
    token count; if `≥ threshold`, call `client.caches.create(...)` and
    pass `cached_content=<name>` to `generate_content`; otherwise skip
    with debug log.
  - `groq.py`, `grok.py`, `hf.py`, `nvidia.py`, `localllm.py`,
    `vllm.py`, `openrouter.py` — no-op default (no documented native
    cache support).
  *Location*: `parrot/clients/base.py` (declaration) + per-subclass overrides.

- **`AGENT_CONTEXT_DIR`** in `parrot/conf.py` — new constant following
  the BASE_DIR + `fallback=` convention:
  `AGENT_CONTEXT_DIR = config.get('AGENT_CONTEXT_DIR', fallback=BASE_DIR.joinpath('agent_context'))`.
  Per-agent files at `<AGENT_CONTEXT_DIR>/<agent_id>.md` (per resolved
  U1 below).
  *Location*: `parrot/conf.py`.

- **`AgentContextLoader`** — sync file read with module-level
  `@functools.lru_cache(maxsize=None)` keyed on `(path, st_mtime)`.
  Missing file = empty string (not an error). Public surface: a single
  `load(agent_id: str) -> str` function.
  *Location*: `parrot/bots/prompts/agent_context.py` (new file).

- **`AGENT_CONTEXT_LAYER`** — a CONFIGURE-phase, `cacheable=True`
  `PromptLayer` that lazily reads the doc on `configure()`. **Auto-injected
  into the builder when `prompt_caching=True` and a builder is in use**
  (per resolved U3 below). No new preset is required.
  *Location*: `parrot/bots/prompts/layers.py` (or `domain_layers.py`).

- **Two lifecycle events**:
  - `PromptCacheAppliedEvent(provider, blocks_marked, est_tokens, segment_hashes)`
  - `PromptCacheSkippedEvent(provider, reason)` where `reason` is one of
    `"below_threshold" | "provider_unsupported" | "feature_off" | "no_segments"`.
  *Location*: alongside existing client lifecycle events (per F009).

- **Tests** — per-provider unit tests asserting (a) feature-off path
  produces identical payload to today (regression guard against
  homologation regressions), (b) feature-on path produces the correct
  native primitive, (c) Gemini below-threshold case emits a debug log
  + `PromptCacheSkippedEvent` without raising, (d) `AgentContextLoader`
  invalidates on `mtime` change and returns empty string for a missing
  file.
  *Location*: `packages/ai-parrot/tests/test_prompt_caching_{claude,openai,gemini}.py`
  + `tests/test_agent_context_loader.py`.

### What Changes

- **`parrot/bots/prompts/builder.py`** — add `prompt_caching: bool = False`
  ctor arg + `build_segments()`. Existing `build()` unchanged.
  *Evidence*: F001

- **`parrot/bots/prompts/layers.py`** — add `cacheable: bool` to
  `PromptLayer`; default derives from `phase`.
  *Evidence*: F001

- **`parrot/bots/abstract.py`** — accept `prompt_caching: bool = False`
  kwarg; auto-inject `AGENT_CONTEXT_LAYER` into the builder when both
  the flag is on AND a builder is in use; thread segments through to the
  client at call time.
  *Evidence*: F004

- **`parrot/clients/base.py`** — declare `_apply_cache_hints` (default
  no-op); accept `system_prompt: Union[str, List[CacheableSegment], None]`
  on `complete/ask/ask_stream` (default str preserves existing behavior
  exactly); call the hook from each subclass before SDK invocation.
  *Evidence*: F002, F009

- **`parrot/clients/claude.py`** — wrap the 13+ `payload['system']`
  assignments behind a private helper that conditionally produces the
  list-of-blocks form with `cache_control`. Keep the string form when
  segments are absent.
  *Evidence*: F003

- **`parrot/clients/gpt.py`** — compute and pass `prompt_cache_key` when
  segments are present; no shape change otherwise.
  *Evidence*: F003

- **`parrot/clients/google/client.py`**, **`analysis.py`**, **`generation.py`**
  — route the call sites through a shared helper that creates/reuses
  `CachedContent` when threshold met, skips silently otherwise.
  *Evidence*: F003

- **`parrot/bots/github_reviewer.py`** — opt in via
  `kwargs.setdefault("prompt_caching", True)` in `__init__`; document the
  Gemini-threshold caveat in the class docstring.
  *Evidence*: F005

- **`parrot/conf.py`** — add `AGENT_CONTEXT_DIR` constant.
  *Evidence*: F007

### What's Untouched (Non-Goals)

- Loaders, vectorstores, integrations (Telegram/Slack/MS Teams/MCP).
- Client-side caching of response bodies — only provider-side cache hints
  in v1.
- Multi-tenant per-user cache-key segmentation in v1 (single global key
  per (agent_id, model) is fine).
- Caching tool definitions in v1 — Anthropic supports `cache_control` on
  tools but v1 caches only the system block. Future work.
- Migrating `GitHubReviewer` fully off the legacy `system_prompt=` path
  to a full `PromptBuilder`; the AGENT_CONTEXT layer is added on top of
  the existing approach (the AbstractBot will compose a default
  builder when `prompt_caching=True` and none is supplied).
- Adding cache support to providers that do not document it (Groq, Grok,
  HuggingFace, NVIDIA, LocalLLM, vLLM, OpenRouter) — these degrade to
  no-op.
- Changing the `PromptBuilder.build()` contract — existing callers must
  see no behavior change.
- Changing the `system_prompt: Optional[str]` signature on
  `complete/ask/ask_stream` — only widening the type via `Union`.

### Patterns to Follow

- **PromptBuilder two-phase render** (`CONFIGURE` once / `REQUEST` per
  call) maps naturally to cacheable / non-cacheable boundaries —
  *Evidence*: F001.
- **`AbstractClient._system_prompt_hash`** privacy pattern for emitting
  events without leaking content — apply the same SHA-256 approach to
  segment hashes in `PromptCacheAppliedEvent` —
  *Evidence*: F002.
- **`navconfig` + `BASE_DIR` + `fallback=`** for `AGENT_CONTEXT_DIR` —
  *Evidence*: F007.
- **`parrot/stores/kb/local.py` mtime invalidation** for
  `AgentContextLoader` — read once, cache by `(path, st_mtime)`, re-read
  when mtime changes —
  *Evidence*: F008.
- **`parrot/registry/routing/cache.py` async-safe LRU** — if at any
  point the loader is touched from async code, use this pattern instead
  of `functools.lru_cache` —
  *Evidence*: F008.
- **`EventEmitterMixin` + lifecycle events (FEAT-176)** for cache
  telemetry — declare `PromptCache{Applied,Skipped}Event` alongside the
  existing client events —
  *Evidence*: F009.

### Integration Risks

- **Anthropic 4-block cache_control limit.** Marking too many segments
  silently caps at 4. *Mitigation*: v1 marks at most 1–2 (the
  AGENT_CONTEXT layer and the identity section). Surface a debug log if
  more cacheable segments existed than slots available.
  *Evidence*: F003.

- **Gemini threshold may make the consumer underwhelming.** The motivating
  consumer (`GitHubReviewer` on Gemini-3-Flash) may not actually cache
  unless its static system prompt + `AGENT_CONTEXT.md` together exceed
  the threshold. *Mitigation*: document honestly in the spec; emit
  `PromptCacheSkippedEvent` so cost/benefit is observable; consider
  Anthropic/OpenAI for the canonical demo.
  *Evidence*: F003, F005.

- **Recent client homologation just stabilized.** Adding a parameter to
  `ask_stream` must not regress the AIMessage final-yield contract from
  TASK-1173..1180. *Mitigation*: type-widen via `Union`; default-arg
  preserves the string path identically; add a regression test that
  feeds today's call shape and asserts identical payload bytes.
  *Evidence*: F009.

- **PromptBuilder has ~10 downstream callers** (`agent.py`, `voice.py`,
  `jira_specialist.py`, `data.py`, `database/agent.py`, `database/prompts.py`,
  `registry/registry.py`, flow types, crew re-exports). The new
  `build_segments()` must coexist with `build()` so none of them needs
  to change. *Mitigation*: additive method only; no behavior change to
  `build()`; cover with a sanity test that `build()` output is identical
  pre- and post-change for each preset.
  *Evidence*: F001.

- **Per-agent AGENT_CONTEXT files** mean an agent without a docs file
  silently gets no context layer. *Mitigation*: when
  `prompt_caching=True` is set but no `<agent_id>.md` exists, log at
  INFO level once per `configure()` so operators notice rather than
  silently lose the layer.
  *Evidence*: F005.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | A fully-featured PromptBuilder exists at `parrot/bots/prompts/builder.py` with two-phase CONFIGURE/REQUEST rendering. | F001 | high | Direct read; class definition and presets verified. |
| C2 | `AbstractClient.complete/ask/ask_stream` accept `system_prompt: Optional[str]`. | F002 | high | Direct read of `base.py:775, 1432, 1470`. |
| C3 | Anthropic's payload assigns `payload['system'] = system_prompt` as a plain string at 13+ call sites in `claude.py`. | F003 | high | Grep with explicit line numbers + payload assembly read. |
| C4 | OpenAI/Groq/Grok use `chat.completions.create` / `responses.create` with the system prompt inside `messages`. | F003 | high | Grep across `gpt.py`, `groq.py`, `grok.py`. |
| C5 | Gemini uses `self.client.aio.models.generate_content` without any caching today. | F003, F006 | high | Comprehensive grep across `google/*.py` + zero matches for caching identifiers. |
| C6 | `AbstractBot` already accepts `system_prompt` and `prompt_builder` kwargs; the builder takes precedence. | F004 | high | Direct read of `__init__` signature (lines 247-309). |
| C7 | `GitHubReviewer` uses the legacy `system_prompt=` path with a static `_SYSTEM_PROMPT` and no repo-level context document. | F005 | high | Direct read of lines 383-387 and 941-958. |
| C8 | `GitHubReviewer`'s default model is `Gemini-3-Flash-Preview`. | F005 | high | Direct read of line 269. |
| C9 | No prior prompt-caching code exists in `packages/ai-parrot/src/parrot/`. | F006 | high | Repo-wide grep returned zero matches. |
| C10 | No `AGENT_CONTEXT.md`-like loader exists today. | F006 | high | Grep for context-doc identifiers returned no relevant loader. |
| C11 | `navconfig` + `BASE_DIR` + `config.get('X_DIR', fallback=BASE_DIR.joinpath('x'))` is the established convention. | F007 | high | 8+ uses in `parrot/conf.py`. |
| C12 | Mtime-based file invalidation is a precedent in `stores/kb/local.py`. | F008 | high | Four explicit uses of `stat().st_mtime` verified. |
| C13 | `functools.lru_cache` silently misbehaves on async methods. | F008 | high | Module docstring of `registry/routing/cache.py` states this explicitly. |
| C14 | The `AbstractClient` API is in its cleanest state in months after the homologation initiative. | F009 | medium | Inferred from absence of in-flight refactors in the last 60 days. |
| C15 | Lifecycle events (FEAT-176) are the right substrate for cache telemetry. | F009 | medium | `EventEmitterMixin` is integrated; emitting new event classes should compose, but EventBus subscription semantics for new types not directly read. |
| C16 | Anthropic enables prompt caching via `system: [{type: 'text', text: '...', cache_control: {type:'ephemeral'}}]` with a 4-block limit. | — | medium | Well-documented externally; no in-repo evidence (per C9). Spec must pin exact constants in a single module. |
| C17 | Gemini's `CachedContent` has a minimum token threshold of 4096 (≥32k for some Flash variants). | — | medium | Well-documented externally; no in-repo evidence. Threshold per model is documented by Google and may shift; v1 must be resilient to a configurable constant. |

Distribution: **13** high, **4** medium, **0** low.

…(truncated)…
