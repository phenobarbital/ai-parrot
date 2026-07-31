---
type: Wiki Overview
title: FEAT-224 — Evolve `IntentRouterMixin` with deterministic embedding routing
id: doc:sdd-proposals-intent-router-mixin-embedding-routing-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The original request, preserved verbatim from the brainstorm:'
---

---
id: FEAT-224
title: "Evolve IntentRouterMixin — deterministic e5 embedding routing with LLM discrepancy fallback, over ask() and conversation()"
slug: intent-router-mixin-embedding-routing
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-05
  summary_oneline: "Add e5-multilingual embedding routing to the existing IntentRouterMixin; keep LLM only for discrepancies; cover ask() + conversation()"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-224/
created: 2026-06-05
updated: 2026-06-05
---

# FEAT-224 — Evolve `IntentRouterMixin` with deterministic embedding routing

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/intent-router-mixin-brainstorm.md` (+ live user direction)
> **Audit**: [`sdd/state/FEAT-224/`](../state/FEAT-224/)

---

## 0. Origin

The original request, preserved verbatim from the brainstorm:

> When a user asks a question, the *output mode* (pie chart, map, table, plain
> text, …) is frequently determined by the phrasing of the request itself. Today
> there is no deterministic mechanism to detect this intent before the expensive
> cloud LLM call. We want a **fast, local, deterministic** intent layer that runs
> *before* the LLM and sets the output mode on the request, using semantic
> similarity rather than surface patterns … without forcing the LLM to invoke a
> tool to trigger it.

**Refined by direct user direction (2026-06-05):**

> "IntentRouterMixin need to be fixed to use the embedding model e5 multilingual
> … + the current option of using LLM only when there are discrepancies about the
> decision, and involve `ask()` method as well as `conversation()`."

**Initial signals** (extracted, not interpreted):
- Verbs: route, encode, resolve, abstain → enrichment (new capability)
- Named entities: IntentRouterMixin, IntentRouter, BasicAgent, RequestContext, RenderPhase, SentenceTransformer, output_mode
- Components / labels: `packages/ai-parrot`
- Acceptance criteria provided: yes (brainstorm §9, 8 items)

---

## 1. Synthesis Summary

The brainstorm proposes a *new* `IntentRouterMixin` for deterministic
embedding-based output-mode routing — but an `IntentRouterMixin` **already
exists** (`parrot/bots/mixins/intent_router.py`) doing a different job: pre-RAG
*retrieval-strategy* routing over `conversation()` via a keyword fast-path plus
an LLM `invoke()` decision (the very keyword+LLM approach the brainstorm wanted
to avoid). Per user direction, the work is therefore to **evolve the existing
mixin**, not create a colliding one: add an **e5-multilingual** SentenceTransformer
embedding router as the primary *deterministic* decision path, **demote the LLM
call to a tie-breaker** invoked only on a *discrepancy*, and extend the routing
hook to cover **`ask()` in addition to `conversation()`**. The `OutputMode`
contract (`models/outputs.py`) already exists and is consumed downstream, and
`sentence-transformers` is already vendored, so this adds **no new hard
dependency** and only fills `output_mode` when the caller left it unset.

---

## 2. Codebase Findings

> All entries are grounded in the research findings persisted at
> `sdd/state/FEAT-224/findings/`. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `parrot/bots/mixins/intent_router.py` | `IntentRouterMixin` | 118-1039 | **Existing mixin to evolve** — keyword+LLM retrieval-strategy routing over `conversation()` | F006, F003 |
| 2 | `parrot/bots/mixins/intent_router.py` | `IntentRouterMixin.conversation` | 166-196 | Current single hook point; must also be reached from `ask()` | F006, F010 |
| 3 | `parrot/bots/mixins/intent_router.py` | `_fast_path` / `_KEYWORD_STRATEGY_MAP` | 52-105, 332-369 | Keyword fast path to be supplemented by embedding routing | F006 |
| 4 | `parrot/bots/mixins/intent_router.py` | `_llm_route` / `_parse_invoke_response` | 373-485 | LLM decision path → demote to discrepancy tie-breaker | F006 |
| 5 | `parrot/registry/capabilities/models.py` | `IntentRouterConfig` | 149-150 | Config to extend (embedding model, per-route threshold, route utterances) | F008 |
| 6 | `parrot/bots/agent.py` | `BasicAgent` | 37 | Agent base the mixin composes in front of | F001 |
| 7 | `parrot/bots/abstract.py` | `ask` / `conversation` | 3107, 3660 | Distinct REQUEST entrypoints, both accept `ctx: RequestContext`; hook target for both | F010, F001 |
| 8 | `parrot/models/outputs.py` | `OutputMode` | 37-72 | Existing output-mode contract the router sets (MAP/TABLE/CHART/INFOGRAPHIC/STRUCTURED_*) | F007 |
| 9 | `parrot/utils/helpers.py` | `RequestContext` / `current_context` | 7-59 | Named per-request carrier (contextvar-bound); lacks `output_mode`/`intent_score` | F004 |
| 10 | `parrot/bots/data.py` | `DataAgent.ask` | 1294-1306 | Subclass that overrides `ask()` with its own `output_mode` kwarg, bypassing `conversation()` | F010, F007 |
| 11 | `parrot/embeddings/base.py` | `EmbeddingModel` | 15-188 | Optional encoder abstraction; sentence-transformers already vendored | F005 |

### 2.2 Constraints Discovered

- **Name + concept collision (load-bearing).** `IntentRouterMixin` already
  exists and routes *retrieval strategy* (dataset/vector/graph/tool/free-LLM),
  not *output mode*. Evolving it means the existing `conversation()`-based
  retrieval routing **must keep working**.
  *Implication*: backwards compatibility is mandatory; output-mode routing is an
  added concern, not a replacement. *Evidence*: F006

- **The `output_mode` contract lives on the response + ask() kwarg, not on the
  carrier.** `OutputMode` is a complete enum; `output_mode` is an explicit
  `ask()` kwarg and is assigned as `response.output_mode = …`. `RequestContext`
  has no such field today.
  *Implication*: the router fills `output_mode` only when the caller left it
  `None` (precedence **explicit kwarg > router > default**); adding
  `ctx.output_mode`/`intent_score` is optional plumbing. *Evidence*: F007, F004

- **`ask()` and `conversation()` are distinct.** Subclasses (e.g. `DataAgent`)
  override `ask()` independently and do **not** funnel it through
  `conversation()`.
  *Implication*: routing wired only into `conversation()` misses `ask()`; a
  shared private hook must be called from both. *Evidence*: F010

- **Encoder already vendored; must stay off the event loop.**
  `sentence-transformers` is instantiated lazily in three existing modules.
  *Implication*: e5-multilingual adds zero new hard dependency; load once in
  `configure()`, run `encode()` via `asyncio.to_thread`. *Evidence*: F005, F002

- **Active churn on the base + mixin.** `bots/abstract.py` and the mixin are
  frequently modified.
  *Implication*: prefer a narrow named hook (template-method, brainstorm A3)
  over a full `ask()` override to minimize merge risk. *Evidence*: F003

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `21039d51` | 2026-05-12 | Jesus Lara | fix(concept-document-authority): address 5 code-review issues | `bots/mixins/intent_router.py` |
| `20783618` | 2026-05-12 | Jesus Lara | feat TASK-1091 — IntentRouterMixin branch logic for ContextEnvelope | `bots/mixins/intent_router.py` |
| `24334a8a` | 2026-05-11 | Jesus Lara | feat TASK-1077 — wire `_run_graph_pageindex` user_context/tenant_id | `bots/mixins/intent_router.py` |

> The mixin is actively maintained (last touched May 2026). `bots/basic.py` has
> only the 2026-03-23 monorepo-scaffolding commit; `bots/abstract.py` churns
> with the late-May visualization work. *Evidence*: F003

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`IntentRouter` embedding engine** — encode route utterances once (e5
  default `intfloat/multilingual-e5-small`), score a query by **max cosine
  similarity per route**, abstain below a per-route threshold. *Evidence*: F005
- **Output-mode phrase bank** — `OUTPUT_MODE_ROUTES: dict[OutputMode, list[str]]`,
  a bank of reference utterances per output mode. When a query like
  `"create a pie chart of Q1 sales"` / `"hazme una gráfica de pastel"` matches
  the chart bank above threshold, the router sets `output_mode =
  OutputMode.STRUCTURED_CHART`. **Mode-only granularity** (resolved): the router
  resolves the *OutputMode*; the chart **subtype** (pie/bar/line) is left to the
  downstream LLM / chart builder. *Evidence*: F007
- **Discrepancy / tie-break policy** — invoke the existing LLM route **only**
  when the embedding decision is ambiguous (see U2). The LLM stops being the
  default decision-maker and becomes a disambiguator. *Evidence*: F006
- **Shared private routing hook** (e.g. `_resolve_output_mode(query, ctx)`)
  invoked from **both** `ask()` and `conversation()`. *Evidence*: F010
- **`IntentRouterConfig` extension** — `embedding_model`, per-route `threshold`,
  discrepancy `margin`, and output-mode route utterances. *Evidence*: F008

### What Changes

- **`parrot/bots/mixins/intent_router.py`::`IntentRouterMixin`** — add the
  embedding router; demote `_llm_route` to a tie-breaker; generalize the hook so
  both `ask()` and `conversation()` route. *Evidence*: F006, F010
- **`parrot/registry/capabilities/models.py`::`IntentRouterConfig`** — add
  embedding/threshold/route fields. *Evidence*: F008
- **`parrot/bots/abstract.py`** — add a minimal **named no-op hook** called from
  `ask()` and `conversation()` (template-method A3). *Evidence*: F010, F003
- **(optional) `parrot/utils/helpers.py`::`RequestContext`** — add
  `output_mode`/`intent_score` fields if the contract should also live on the
  carrier (see U3). *Evidence*: F004

### What's Untouched (Non-Goals)

- `OutputMode` enum — already complete; only consumed. *Evidence*: F007
- Existing retrieval-strategy routing (dataset/vector/graph/tool/free-llm) —
  preserved. *Evidence*: F006
- Downstream output-mode rendering in `data.py` / visualizations. *Evidence*: F007
- LLM-based fallback for below-threshold *output-mode* abstention beyond the
  discrepancy tie-breaker; multi-intent decomposition (brainstorm Non-Goals).

### Patterns to Follow

- Lazy `import sentence_transformers as _st` + **load-once in `configure()`**.
  *Evidence*: F005, F002
- Cooperative `super().__init__()` / `super().configure()` chaining already used
  by the mixin. *Evidence*: F006, F001
- `asyncio.to_thread` around the blocking `encode()`. *Evidence*: F005

### Integration Risks

- **Conceptual overload of one mixin doing two routing jobs** (retrieval +
  output mode). *Mitigation*: clearly separated config sections and methods, or
  compose a dedicated `OutputModeRouter` engine *inside* the existing mixin.
  *Evidence*: F006
- **Touching `abstract.ask()/conversation()` during visualization churn.**
  *Mitigation*: keep the hook to a few lines + a no-op default. *Evidence*: F003
- **e5 prefix convention** (`query:` / `passage:`). Wrong prefixing silently
  degrades similarity and invalidates tuned thresholds. *Evidence*: F005
- **Clause dilution.** Output-mode intent is often a *small clause* inside a
  larger data question ("…**and show it as a pie chart**"). Encoding the whole
  long query can dilute the chart signal below threshold. *Mitigation*: phrase
  the bank as realistic full requests and/or segment the query; the LLM
  discrepancy fallback covers the ambiguous tail. *Evidence*: F005, F006

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | An `IntentRouterMixin` already exists routing *retrieval strategy* (not output mode) over `conversation()` | F006 | high | full file read |
| C2 | The existing mixin uses keyword fast-path + LLM `invoke()` — the approach the brainstorm wanted to avoid | F006 | high | direct read of `_fast_path`/`_llm_route` |
| C3 | `OutputMode` + `response.output_mode` + `ask(output_mode=)` already form the output-mode contract | F007 | high | enum source + assignment sites |
| C4 | `RequestContext` exists (contextvar-bound) but lacks `output_mode`/`intent_score` | F004 | high | full class read |
| C5 | `ask()` and `conversation()` are distinct; `ask()` is overridden independently and not funneled through `conversation()` | F010 | high | both signatures + `DataAgent.ask` |
| C6 | `sentence-transformers` already vendored; e5 adds no new hard dependency | F005 | high | three instantiation sites |
| C7 | A prior intent-router spec exists and the subsystem is actively maintained | F008, F003 | high | files on disk + git history |
| C8 | `RenderPhase` exists but is scoped to prompt-layer caching, not general lifecycle dispatch | F002 | medium | enum read; usage inferred |
| C9 | Best design = evolve existing mixin (embedding primary, LLM tie-breaker, hook `ask()`+`conversation()`) | F006, F010, F005 | high | confirmed by user direction |

Distribution: **8** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Create a new mixin, or evolve the existing one?** — *Resolved*: "fix the
  existing `IntentRouterMixin` to use the e5 multilingual embedding model; keep
  the LLM option only for resolving discrepancies; involve `ask()` as well as
  `conversation()`." *Resolves claims*: C1, C9
- [x] **Does a `RequestContext` carrier exist (the brainstorm's blocking
  question)?** — *Resolved by research*: yes, `utils/helpers.py:7`,
  contextvar-bound via `current_context()`, but without `output_mode`/`intent_score`.
  *Resolves claims*: C4
- [x] **U4 — Phrase bank: OutputMode only, or also chart subtype (pie/bar/line)?**
  — *Resolved*: **mode only**. The router sets the `OutputMode` (e.g.
  `STRUCTURED_CHART`); chart subtype is decided downstream by the LLM/chart
  builder. Avoids route/threshold explosion. *Resolves claims*: C3

### Unresolved (defer to spec / implementation)

- [ ] **U2 — What constitutes a "discrepancy" that triggers the LLM
  tie-breaker?** — *Owner*: tbd. *Blocks claims*: C9.
  *Plausible answers*: a) embedding top score below threshold · b) top-2 routes
  within a small cosine margin (ambiguous) · c) both conditions combined.
- [ ] **U3 — Should `output_mode`/`intent_score` also be added to
  `RequestContext`, or remain on the response + `ask()` kwarg only?** —
  *Owner*: tbd. *Blocks claims*: C4.
  *Plausible answers*: a) add to `RequestContext` for uniform access ·
  b) keep response/kwarg only and have the hook set the kwarg path.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-224`** — *Rationale*: localization is high-confidence and the
work is a **bounded evolution** of an existing, specced subsystem whose
architecture the user has already chosen (e5 embedding primary + LLM discrepancy
fallback + `ask()`/`conversation()` hook). The two remaining unknowns (U2, U3)
are spec-time decisions, not design blockers.

### Alternatives

- **`/sdd-brainstorm FEAT-224`** — only if you want to revisit whether
  output-mode routing should live *inside* `IntentRouterMixin` vs. as a separate
  composed `OutputModeRouter` (the C1/F006 conceptual-overload risk).
- **`/sdd-task FEAT-224`** — not recommended; the change spans the mixin, the
  config model, and the abstract base, so it is more than a single trivial task.
- **Manual review** — not warranted; research is complete and not truncated.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-224/state.json` |
| Source (raw) | `sdd/state/FEAT-224/source.md` |
| Research plan | `sdd/state/FEAT-224/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-224/findings/F001…F010-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-224/synthesis.json` |

**Budget consumed**:
- Files read: 8 / 40
- Grep calls: 11 / 25
- Git calls: 3 / 10
- Wall time: ~270s / 300s
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (forward-looking new
capability over existing code; no negation/bug signal in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (with Claude Code) |
