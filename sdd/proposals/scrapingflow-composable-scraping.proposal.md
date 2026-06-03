---
id: FEAT-221
title: "ScrapingFlow: composable long-horizon scraping via TemplatePlan, ScrapingFlow DAG, and FlowExecutor"
slug: scrapingflow-composable-scraping
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-04
  summary_oneline: "ScrapingFlow: composable long-horizon scraping via TemplatePlan, ScrapingFlow DAG, and FlowExecutor"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-221/
created: 2026-06-04
updated: 2026-06-04
---

# FEAT-221 — ScrapingFlow: Composable Long-Horizon Scraping

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `file: sdd/proposals/scrapingflow.proposal.md` (brainstorm document, Option A recommended)
> **Audit**: [`sdd/state/FEAT-221/`](../state/FEAT-221/)

---

## 0. Origin

The source is a brainstorm document that explored three approaches for extending the
`WebScrapingToolkit` to support parameterized plans, composable multi-step flows, and
multi-window sessions. Option A (declarative layered model: TemplatePlan → ScrapingFlow
→ FlowExecutor) was recommended. This research-grounded proposal validates Option A's
claims against the actual codebase and surfaces critical discrepancies and constraints.

> Three needs outside current capability: (1) reutilización parametrizada — un plan
> está atado a una URL concreta vía fingerprint, (2) composición de flujos largos —
> no hay DAG de etapas con paso de datos, (3) sesión multi-ventana — no hay modelo
> de BrowserContext compartido entre etapas.

**Initial signals**:
- Verbs: "implement", "compose", "parametrize" → feature-shaped
- Named entities: TemplatePlan, ScrapingFlow, FlowExecutor, ParamSpec, FlowNode
- Components: `parrot_tools.scraping` (executor, models, plan, registry, crawler, drivers)
- Acceptance criteria provided: yes (implicit via capabilities section in brainstorm)

---

## 1. Synthesis Summary

The brainstorm's Option A is architecturally sound: three layered capabilities
(TemplatePlan, ScrapingFlow, FlowExecutor) built on top of the existing immutable
`ScrapingPlan` and `execute_plan_steps` engine. Research confirms that all referenced
existing code paths are accurate — `execute_plan_steps`, `BasePlanRegistry[T]`, and
`ExtractionPlan.to_scraping_plan()` — and the extension patterns are proven. However,
two significant gaps were discovered: (1) the brainstorm's claim about a "double-brace
`{{index}}` convention" in Loop is **factually incorrect** — Loop uses single braces
`{index}` via regex, so TemplatePlan needs its own placeholder convention; (2) `PlaywrightDriver`
supports only a single `BrowserContext`, meaning the FlowExecutor cannot use the existing
driver abstraction for multi-session flows and must work directly with Playwright's Browser
object via a new `PageDriver` adapter and `SessionManager` component.

---

## 2. Codebase Findings

> All entries grounded in findings at `sdd/state/FEAT-221/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | `execute_plan_steps` | 41-186 | Stateless step runner; accepts pre-initialized driver, returns ScrapingResult | F001 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py` | `ScrapingPlan` | 59-110 | Immutable plan model; fingerprint from URL only | F002 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py` | `_compute_fingerprint` | 31-44 | 16-char SHA-256 of normalized URL | F002 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py` | `ACTION_MAP` | 726-755 | 29 registered action types | F003 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py` | `Loop` | 679-707 | Template vars via single braces `{index}`, `do_replace` flag | F003 |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/scraping/base_registry.py` | `BasePlanRegistry` | 93-149 | Generic registry base; 3-tier lookup; proven extension pattern | F005 |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_registry.py` | `ExtractionPlanRegistry` | 1-251 | Extension pattern: separate index, failure tracking, file storage | F005 |
| 8 | `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py` | `ExtractionPlan.to_scraping_plan` | 127-168 | Translation pattern for TemplatePlan.bind() | F007 |
| 9 | `packages/ai-parrot-tools/src/parrot_tools/scraping/crawler.py` | `CrawlEngine` | 46-195 | Semaphore concurrency pattern (reusable); URL-centric class (not reusable) | F004 |
| 10 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | `PlaywrightDriver` | 15-395 | Single BrowserContext; `new_page()` shares context | F006 |
| 11 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | `AbstractDriver` | 11-352 | 19 abstract methods; no context/page management | F006 |
| 12 | `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py` | `__all__` | 1-69 | 29 exports; new types need addition | F008 |

### 2.2 Constraints Discovered

- **ScrapingPlan is immutable with URL-only fingerprint.** `model_post_init` auto-computes
  fingerprint from normalized URL. Two `TemplatePlan.bind()` calls with different params on
  the same URL template would produce ScrapingPlans with identical fingerprints, causing
  registry collisions.
  *Implication*: `bind()` must override the auto-computed fingerprint with `template_name + param_hash`.
  *Evidence*: F002

- **execute_plan_steps is a stateless step runner.** It receives a fully initialized
  `AbstractDriver` and does NOT manage driver lifecycle (no page creation, no context management).
  *Implication*: FlowExecutor must create and manage Page-wrapping drivers itself.
  *Evidence*: F001

- **Loop and 7 other advanced actions are SKIPPED in standalone executor.** The executor
  logs a warning and returns `True` (no error) for `loop`, `conditional`, `authenticate`,
  `await_human`, `await_keypress`, `await_browser_event`, `upload_file`, `wait_for_download`.
  The full implementations live in `WebScrapingTool` (tool.py:2590+).
  *Implication*: Flow nodes with loop/conditional steps will silently produce incomplete
  results unless routed through WebScrapingTool or a custom dispatch.
  *Evidence*: F001, F003

- **PlaywrightDriver supports only ONE BrowserContext.** `start()` creates exactly one
  context and one page. `new_page()` creates additional pages in the same context but no
  API exists for additional contexts. `AbstractDriver` has no context/page management in
  its interface.
  *Implication*: FlowExecutor must bypass PlaywrightDriver and work directly with Playwright's
  Browser API, using a lightweight PageDriver adapter per Page.
  *Evidence*: F006

- **Loop uses SINGLE braces `{index}`, not double `{{index}}`.** The brainstorm document
  states "reutilizando la convención de doble llave del Loop" but the actual regex is
  `r'\{([^}]*(?:i|index|iteration)[^}]*)\}'` — single braces throughout.
  *Implication*: TemplatePlan should use double braces `{{param}}` to avoid collision with
  Loop's single-brace vars and with CSS/JSON syntax containing literal `{`.
  *Evidence*: F003

- **CrawlEngine has no checkpoint mechanism.** Graph state is in-memory only; progress
  lost on interruption.
  *Implication*: FlowExecutor checkpoints must be built from scratch.
  *Evidence*: F004

- **BasePlanRegistry[T] is generic.** `ExtractionPlanRegistry(BasePlanRegistry[ExtractionPlan])`
  proves the extension pattern: separate index file, per-fingerprint storage, custom methods.
  *Implication*: `TemplatePlanRegistry(BasePlanRegistry[TemplatePlan])` follows naturally.
  *Evidence*: F005

- **CrawlEngine's scrape_fn interface is `(url, plan)`.** Too URL-centric for FlowExecutor
  fan-out which needs input resolution, template binding, session context.
  *Implication*: Reuse the `asyncio.Semaphore` + `gather` concurrency pattern, not the
  CrawlEngine class.
  *Evidence*: F004

### 2.3 Recent History (Relevant)

| Period | Commits | Theme | Files |
|--------|---------|-------|-------|
| May 2026 | 3 | JSON-LD extraction (FEAT-154) | executor.py, models.py |
| Apr 2026 | ~10 | Playwright driver, AbstractDriver parity, executor fixes | drivers/, executor.py |
| Mar 2026 | ~7 | ExtractionPlanRegistry, BasePlanRegistry generics, RecallProcessor, pre-built plans | extraction_registry.py, base_registry.py |

20 commits in 60 days. Active development on the extraction/registry layer (March) and
driver abstraction (April) — both directly relevant to FEAT-221's design. No conflicts
with recent work; the module is stable. *Evidence*: F009

---

## 3. Probable Scope

### What's New

- **`TemplatePlan`** — Pydantic model with `ParamSpec` list, `url_template`, `objective_template`,
  `steps_template`. `bind(**kwargs)` validates params, renders `{{param}}` placeholders, and
  produces a concrete `ScrapingPlan` with fingerprint `= hash(template_name + sorted(params))`.

- **`ParamSpec`** — Pydantic model: `name`, `type` (string|int|date|enum|url), `required`,
  `default`, `choices`, `description`. Validates values in `TemplatePlan.bind()`.

- **`ScrapingFlow`** — Pydantic model: `name`, `nodes: List[FlowNode]`. DAG defined by
  `FlowNode.inputs` references. Validates refs and detects cycles on construction.

- **`FlowNode`** — Pydantic model: `id`, `plan_ref`, `inputs: Dict[str, str]`, `session: str`,
  `on_error: Literal["abort", "skip", "retry"]`.

- **`FlowExecutor`** — Orchestration engine: computes topological order from `inputs` graph,
  manages `SessionManager` for BrowserContext lifecycle, creates `PageDriver` per node,
  executes via `execute_plan_steps`, persists per-node checkpoints.

- **`FlowResult`** — Aggregated result: per-node results (keyed by node id), flow-level
  success flag, timing, checkpoint state.

- **`PageDriver`** — Lightweight `AbstractDriver` implementation wrapping a Playwright
  `Page` object. Delegates all 19 abstract methods to Page equivalents. `start()` is
  no-op (page already exists); `quit()` closes the page only.

- **`SessionManager`** — Owns the Playwright `Browser` instance. Creates/caches/closes
  `BrowserContext`s by session label. Deterministic lifecycle: precomputes `last_use[session]`
  from topological order, closes context after its last node completes.

### What Changes

- **`__init__.py`** — Add exports: `TemplatePlan`, `ParamSpec`, `ScrapingFlow`, `FlowNode`,
  `FlowExecutor`, `FlowResult`. *Evidence*: F008

### What's Untouched (Non-Goals)

- `ScrapingPlan` — no modification; `TemplatePlan.bind()` produces it
- `execute_plan_steps` — used as-is; invoked per node
- `ACTION_MAP` / `ScrapingStep` — no changes to action registry
- `CrawlEngine` — pattern borrowed, class untouched
- `AbstractDriver` — interface unchanged; `PageDriver` implements it
- `PlaywrightDriver` — unchanged; `FlowExecutor` works below it
- `ExtractionPlan` / `ExtractionResult` — independent subsystem
- `WebScrapingToolkit` — higher-level interface, no changes
- Playwright code generation / MCP server — deferred to future spec

### Patterns to Follow

- `ExtractionPlan.to_scraping_plan()` translation pattern → `TemplatePlan.bind()` *Evidence*: F007
- `ExtractionPlanRegistry(BasePlanRegistry[T])` extension → `TemplatePlanRegistry` *Evidence*: F005
- `asyncio.Semaphore + gather` bounded concurrency (from `CrawlEngine._run_concurrent`) *Evidence*: F004
- Pydantic `BaseModel` for all data models (consistent with ScrapingPlan, ExtractionPlan) *Evidence*: F002, F007

### Integration Risks

- **PageDriver adapter surface area.** Must implement all 19 `AbstractDriver` abstract methods.
  Most map directly to Playwright Page equivalents, but `start()`/`quit()` semantics differ
  (PageDriver doesn't own the browser). *Mitigation*: `start()` → no-op; `quit()` → `page.close()`.
  *Evidence*: F006

- **Silent skip of Loop/conditional in flow nodes.** `execute_plan_steps` returns `True` for
  Loop actions without executing them. Flow nodes with loops will produce results missing the
  looped data, with no error raised. *Mitigation*: Either route nodes with advanced actions
  through `WebScrapingTool`, extract the `_exec_loop` logic into a reusable function, or
  document as limitation. *Evidence*: F001, F003

- **Concurrent fan-out on shared authenticated session.** Multiple Pages in one BrowserContext
  reading/writing cookies simultaneously may race. *Mitigation*: Enforce sequential execution
  within a session; document as known deferred debt. *Evidence*: F004, F006

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | execute_plan_steps can be invoked per-node with any AbstractDriver-conformant adapter | F001 | high | Function signature confirmed; accepts any AbstractDriver |
| C2 | ScrapingPlan fingerprint is URL-only; templates need param_hash | F002 | high | `_compute_fingerprint` reads normalized_url only |
| C3 | Loop uses single braces `{index}`, contradicting brainstorm's double-brace claim | F003 | high | Regex pattern `r'\{([^}]*(?:i|index|iteration)[^}]*)\}'` confirmed |
| C4 | CrawlEngine's Semaphore pattern is reusable for fan-out | F004 | high | Standard asyncio.Semaphore + gather |
| C5 | BasePlanRegistry is generic and supports new plan types | F005 | high | ExtractionPlanRegistry proves it |
| C6 | PlaywrightDriver cannot manage multiple BrowserContexts | F006 | high | start() creates exactly one context |
| C7 | PageDriver adapter wrapping Playwright Page is feasible | F006 | medium | 19 methods need implementation; start/quit semantics differ |
| C8 | Flow checkpoint persistence must be built from scratch | F004, F005 | high | No existing checkpoint mechanism anywhere |
| C9 | Loop/conditional silently skipped in flow nodes via execute_plan_steps | F001, F003 | high | Executor logs warning and returns True |
| C10 | ExtractionPlan.to_scraping_plan() is the pattern for bind() | F007 | high | Both transform rich model → executable ScrapingPlan |
| C11 | No existing template/flow/parameterized patterns in scraping module | F009 | high | grep returned no matches; all net-new |

Distribution: **9** high, **1** medium, **0** low.

> The medium-confidence item (C7) is a design feasibility assessment, not a codebase
> uncertainty — all relevant code was directly read and verified.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Does execute_plan_steps support being called per-node with an arbitrary driver?** — *Resolved*: Yes. It accepts any `AbstractDriver` and has no lifecycle coupling. *Resolves claims*: C1

- [x] **Is BasePlanRegistry generic enough for a new TemplatePlanRegistry?** — *Resolved*: Yes. `ExtractionPlanRegistry` already demonstrates the extension pattern. *Resolves claims*: C5

- [x] **Does the brainstorm's "double-brace convention" match the codebase?** — *Resolved*: No. Loop uses single braces. TemplatePlan should use double braces `{{param}}` to avoid collision. *Resolves claims*: C3

- [x] **Can PlaywrightDriver manage multiple BrowserContexts?** — *Resolved*: No. Only one context created in `start()`. FlowExecutor must work with Playwright Browser directly. *Resolves claims*: C6

### Unresolved (defer to spec / implementation)

- [ ] **What is the exact mini-grammar for the `inputs` resolver (`"node_id.path.field"`)?** — *Owner*: spec author
  *Blocks claims*: (implementation detail)
  *Plausible answers*: a) flat: `node_id.field_name` · b) dot-path with optional `[N]` list index · c) JSONPath-lite subset

- [ ] **How should flow nodes with Loop/conditional steps be executed?** — *Owner*: spec author
  *Blocks claims*: C9
  *Plausible answers*: a) route through WebScrapingTool · b) extract `_exec_loop` to reusable function · c) defer as limitation

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-221`** — *Rationale*: Localization is high-confidence across all 12
affected code areas, the scope is well-defined with 8 new components and clear integration
points, and the brainstorm already explored and rejected alternatives. The two unresolved
questions are implementation-level decisions best resolved during spec writing.

### Alternatives

- **`/sdd-brainstorm FEAT-221`** — not needed; the source document already IS a brainstorm
  with Option A validated. Research confirms the design, with corrections noted above.
- **`/sdd-task FEAT-221`** — premature; the scope is too large for direct task decomposition
  without a spec.
- **Manual review** — not needed; research was complete (not truncated) and confidence is high.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-221/state.json` |
| Source (raw) | `sdd/state/FEAT-221/source.md` |
| Findings (digests) | `sdd/state/FEAT-221/findings/F001-*.md` through `F010-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-221/synthesis.json` |

**Budget consumed**:
- Files read: ~35 / 100 (loose)
- Grep calls: ~15 / 60
- Git calls: ~5 / 20
- Wall time: ~210s / 900s
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs: "implement",
"compose", "parametrize"; no negation or bug indicators).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude (FEAT-221 research session) |
