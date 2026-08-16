---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: "Tales" — Research Flow with Structured Citations, Decks & Final Report

**Date**: 2026-08-17
**Author**: Jesús Lara (with Claude Code research)
**Status**: exploration
**Recommended Option**: A

> Named after Thales of Miletus. Despite the working title
> `agentcrew-tales-research`, discovery Round 1 selected **AgentsFlow (DAG)**
> as the orchestration backbone — the pipeline's fan-out → fan-in → per-deck
> transform shape maps to explicit edges, not to `AgentCrew.run_flow()`.

---

## Problem Statement

A user states a **thesis** ("remote work increases regional inequality",
"open-source flight stacks bridge LATAM engineering talent") and wants a
finished, *sourced* research package back — not a wall of unattributed LLM
prose. Today AI-Parrot has every building block (WebSearchAgent with Gemini
built-in search, `GoogleGenAIClient.deep_research`, ArxivTool, deterministic
groundedness scoring, InfographicToolkit, an ArtifactStore, a weasyprint PDF
renderer) but **no flow that assembles them into a research product**.

Tales closes that gap: a parallel multi-agent investigation whose every
factual claim carries **source metadata** (URL, publication date, authors,
publisher), materialized as:

1. **Research decks** — structured JSON blocks (findings + extracted
   paragraphs + tool used + per-claim source metadata).
2. **HTML slides** — one per deck, with charts, tables, and quotes, in the
   style of a published deck page (reference example:
   https://hanademi.com/decks/open-source-flight-stacks-bridge-latam-engineering-talent-20260810-030435/).
3. A **final document** (slides + structured bibliography), print-CSS HTML
   the user saves as PDF from any browser.
4. An **executive summary** + a summary **infographic** rendered via the
   existing `InfographicToolkit`.

**Who is affected**: analysts/consultants producing sourced research
deliverables; developers embedding "research-to-deck" in products; end
recipients of the decks/PDF/infographic.

**Why now**: FEAT-398 (deterministic groundedness) and FEAT-308 (crew
infographic ResultAgent) just landed; FEAT-273 settled the deterministic
HTML→PDF story (weasyprint). The blocks exist and are unassembled — the same
situation FEAT-308 exploited for crews.

## Constraints & Requirements

Decisions locked during discovery (Rounds 0–3 with Jesús):

- **Flow type**: `feature`, base branch `dev`.
- **Engine**: **AgentsFlow** (`parrot/bots/flows/flow/`) — explicit edges,
  fan-out research, OR-join fan-in, conditional routing, node-event telemetry.
- **Deck model**: **N sub-theses × all sources.** A planner node splits the
  user thesis into a configurable number **N** of research angles; each angle
  is researched across *all* enabled research nodes; **one deck per angle**,
  each deck citing multiple sources. N is the "cuántas ideas deseo explorar"
  knob.
- **Anti-hallucination**: **per research agent** — every research agent runs
  with `enable_groundedness=True` (FEAT-398 guardrail); its
  `GroundednessReport` is carried into the deck metadata. (Honest limitation
  recorded in Edge Cases: groundedness scores against `ToolCall.result`
  evidence, so it is fully effective for tool-based nodes; Gemini built-in
  search / Deep Research responses carry provider grounding metadata instead.)
- **New data-source tools deferred**: World Bank Open Data, EU Open Data,
  Oxford Academic, Gallup ship in a **named follow-up spec**
  (`tales-research-source-toolkits`) that this spec shapes contractually so
  it can be built in a parallel worktree. Tales v1 ships with WebSearch +
  Deep Research + Arxiv.
- **Rendering**: **deterministic templates** — LLMs only fill structured
  Pydantic specs (`ResearchDeck`, `SlideSpec`); rendering is pure Python
  (TemplateEngine/Jinja2 + ECharts/static-SVG per the FEAT-273 pattern). No
  LLM in the render path. **matplotlib is purged from this codebase**
  (`sdd/specs/purge-matplotlib-renderer-libs.spec.md`) — chart generation
  must NOT reintroduce it (this supersedes the abstract's "python svg-library
  in PythonREPL" sketch).
- **Delivery surfaces — all four in this spec**: Python API (library),
  aiohttp HTTP handler (ai-parrot-server), filesystem output dir with a
  manifest, and persistence via the existing `ArtifactStore` (object
  storage/DB surface).
- **PDF**: **print-CSS HTML only** — the final document is a single
  print-optimized HTML (`@page` rules, page-break per slide) saved as PDF
  from the browser. (The existing weasyprint `PDFRenderer` is noted as a
  zero-new-dependency upgrade path — see Open Questions.)
- **Images**: **charts/tables/quotes only** in v1 — no third-party image
  scraping (licensing); source-image extraction is a named follow-up.
- Async-first, Pydantic models, `self.logger`, no new blocking I/O — per
  project rules.

---

## Options Explored

### Option A: `parrot/flows/tales/` — a domain flow package on AgentsFlow *(RECOMMENDED)*

Follow the established application-flow pattern (`parrot/flows/dev_loop/` is
the documented template: `definition.py + factories.py + nodes/ + runner.py`).
Tales becomes `parrot/flows/tales/` — a `FlowDefinition` + custom node
factories materialized through `AgentsFlow.from_definition(...,
node_factories=...)`, so live dependencies (ArtifactStore, TemplateEngine,
toolkits) close over factories instead of traveling through config dicts.

DAG shape (edges, not prose):

```
start → planner ──(angle 1..N fan-out)──▶ research[i][web]     ─┐
                                          research[i][deep]     ├─▶ deck_builder[i] ─▶ slide_spec[i] ─▶ slide_render[i] ─┐
                                          research[i][arxiv]    ─┘   (fan-in per angle)   (structured)   (deterministic)  │
                                          research[i][<future>]                                                           │
                 bibliography ◀──(fan-in: all decks' SourceClaims)◀───────────────────────────────────────────────────────┤
                 exec_summary ◀──(fan-in: all decks)                                                                      │
                 final_document ◀── slides + bibliography (print-CSS HTML)                                                │
                 infographic ◀── exec_summary + decks (InfographicToolkit / ResultAgent pattern) ─▶ end ◀─────────────────┘
```

- **planner** — LLM (structured output, combined tools+schema per TASK-1304)
  splits the thesis into N `ResearchAngle`s.
- **research nodes** — per angle: a `WebSearchAgent` (with
  `use_builtin_search=True` → Gemini internal Google Search, plus
  `contrastive_search=True` — both already exist), a Deep Research node
  wrapping `GoogleGenAIClient.deep_research()` (exists, background
  interactions API, agent `"deep-research-pro-preview-12-2025"`), and an
  Arxiv agent carrying `ArxivTool` (exists; returns title/authors/
  published/pdf_url/journal_ref — exactly the SourceClaim fields). All
  research agents constructed with `enable_groundedness=True`.
- **deck_builder[i]** — merges an angle's research outputs into one
  `ResearchDeck` (structured output): findings, extracted paragraphs,
  tool provenance, `SourceClaim[]` (url, title, authors, publisher,
  published_date, accessed_date, source_tool), groundedness reports.
- **slide_spec[i]** — LLM fills a `SlideSpec` Pydantic model (layout hints,
  chartable series, table rows, pull-quotes) from the deck. LLM never writes
  HTML.
- **slide_render[i]** — deterministic: Jinja2 slide template + ECharts
  option-JSON (browser path) / static SVG (print path), per the FEAT-273
  renderer convention.
- **bibliography** — deterministic fan-in: dedupes all `SourceClaim`s into a
  `Bibliography` (report-style entries: site, URL/paper link, authors, date,
  publisher), appended as the final section of the research.
- **exec_summary** — synthesis over all decks (reuse `SynthesisNode` /
  `synthesize_results` util already in flows).
- **final_document** — deterministic: all slides + bibliography into one
  print-CSS HTML (`@page`, page-break per slide), persisted via
  `ArtifactStore`.
- **infographic** — invokes `InfographicToolkit` with summary + decks
  (mirrors FEAT-308's `ResultAgent`/`crew_report` pattern, which landed and
  is reusable).
- **Delivery**: `TalesRunner` (Python API) returns a `TalesResult` manifest
  (deck JSONs, slide HTMLs, final doc, infographic — artifact ids + URLs +
  filesystem paths); a `TalesHandler` in ai-parrot-server (precedent:
  `packages/ai-parrot-server/src/parrot/handlers/infographic.py`) launches
  runs and serves artifacts; everything persisted through `ArtifactStore`
  (`save_artifact` / `get_public_url` — signed public URLs already exist).

✅ **Pros:**
- Matches every discovery decision natively (DAG fan-out/fan-in, conditional
  edges, per-node telemetry for a progress UI, checkpointing for long Deep
  Research runs via FEAT-399 `checkpoint=True`).
- Follows the documented domain-flow template (`dev_loop`), so structure is
  familiar and reviewable.
- `node_factories` keeps live dependencies out of config dicts and avoids
  polluting the global `NODE_REGISTRY` with app-specific types.
- Deterministic render path is unit-testable without an LLM; slide/bibliography/
  final-document nodes are pure functions over Pydantic models.
- Reuses FEAT-308, FEAT-398, FEAT-273, FEAT-197 investments as-is.

❌ **Cons:**
- Largest new-code surface of the three options (~5 node families + models +
  templates + handler).
- Dynamic N×M fan-out means the `FlowDefinition` is *generated* per run
  (planner output determines node count) — the flow is built after planning,
  slightly unusual vs a static definition (mitigation: two-phase — plan
  first, then build+run the research flow).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jinja2` (via `parrot.template.engine.TemplateEngine`) | slide + document templates | already a core dep |
| `arxiv` | ArxivTool backend | already used by `parrot_tools.arxiv_tool` |
| `google-genai` | Gemini built-in search + Deep Research interactions | already the google client backend |
| ECharts (JS, embedded option-JSON) + static SVG | charts in slides | FEAT-273 pattern; **no matplotlib** (purged) |
| `weasyprint` (optional, existing extra) | server-side PDF upgrade path | already the SPK-1-confirmed backend; NOT required for v1 print-CSS |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` — `AgentsFlow` (L173), `add_node` (L300), `add_edge` (L317), `from_definition(..., node_factories=...)` (L428), `run_flow` (L912), `SynthesisNode` (L1963).
- `packages/ai-parrot/src/parrot/bots/search.py` — `WebSearchAgent` (L45): `use_builtin_search` (Gemini internal search via `tool_type='builtin_tools'`), `contrastive_search`, `synthesize`.
- `packages/ai-parrot/src/parrot/clients/google/client.py` — `_deep_research_ask` (L5015, agent `"deep-research-pro-preview-12-2025"` L5026), `deep_research` (L5102, files + background).
- `packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py` — `ArxivTool` (L36).
- `packages/ai-parrot/src/parrot/security/groundedness/guardrail.py` — `GroundednessGuardrail`; enabled per-bot via `enable_groundedness=True` (`bots/abstract.py:718`).
- `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` — `InfographicToolkit` (L180), `render` (L403), `render_template` (L520).
- `packages/ai-parrot/src/parrot/bots/flows/result_agent.py` — `ResultAgent` (L107, FEAT-308) + `crew/result_infographic.py` deterministic tab assembly.
- `packages/ai-parrot/src/parrot/storage/artifacts.py` — `ArtifactStore` (L27), `save_artifact` (L46), `get_public_url` (L177).
- `packages/ai-parrot-server/src/parrot/handlers/infographic.py` — HTTP handler precedent for artifact-producing endpoints.
- `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py` — `PDFRenderer` (L99, weasyprint) — optional upgrade path.
- `parrot/flows/dev_loop/` — the documented domain-flow package template.

---

### Option B: AgentCrew (`run_flow` / `task_flow`) — literal to the abstract

Build Tales as an `AgentCrew` from a `CrewDefinition`: research agents run
via `run_parallel()` per angle, then sequential post-processing tasks, and
FEAT-308's `generate_infographic=True` for the final infographic.

✅ **Pros:**
- Closest to the abstract's wording ("AgentCrew Tales").
- FEAT-308 finalizer works out of the box for the infographic tab report.
- `CrewDefinition` gives declarative crew configs (saved-crews machinery).

❌ **Cons:**
- The pipeline is genuinely a DAG with per-item transform chains
  (deck[i] → slide_spec[i] → slide_render[i]); crew task_flow expresses
  agent-to-agent handoff, not N-way per-item pipelines — the per-deck stages
  would collapse into monolithic "do all decks" tasks (loses per-deck
  parallelism and per-node telemetry).
- Deterministic (non-agent) stages — bibliography, slide render, final
  document — have no natural home in a crew of agents; they'd be shoehorned
  into agents or hidden in hooks.
- Conditional routing / OR-join / checkpointing (long Deep Research runs)
  are AgentsFlow features, absent in crew mode.

📊 **Effort:** Medium-High (less new orchestration, more shoehorning)

📦 **Libraries / Tools:** same as Option A.

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` — `AgentCrew`, `run_parallel`, `run_flow`, `generate_infographic` (FEAT-308).
- Rest identical to Option A.

---

### Option C: Thin deterministic pipeline (no flow engine) *(unconventional)*

Skip orchestration entirely: `TalesPipeline` is plain async Python —
`asyncio.gather` over research agents per angle, then a sequence of pure
functions (deck merge → slide spec via one structured-output LLM call →
render → bibliography → summary → infographic). No AgentsFlow, no crew.

✅ **Pros:**
- Smallest conceptual surface; the whole run is one readable coroutine.
- Trivially unit-testable; no DAG materialization ceremony for a dynamic N.
- No two-phase "plan then build flow" wrinkle — N is just a loop bound.

❌ **Cons:**
- Loses everything the flow plane provides: node-event telemetry (progress
  UI for multi-minute Deep Research runs), checkpoint/resume (FEAT-399),
  persistence mixins, `FlowDefinition` export, future UI composition of
  Tales variants.
- A second orchestration idiom in a repo that just consolidated on
  `bots/flows/` (FEAT-143/163/196) — strategic regression.
- The HTTP handler would need bespoke progress reporting instead of
  reusing `on_node_event`.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as Option A minus the flow engine.

🔗 **Existing Code to Reuse:** agents/tools/renderers as in Option A; no flow plane.

---

## Recommendation

**Option A** is recommended because:

- The product shape *is* a DAG — configurable fan-out (N angles × M source
  nodes), two distinct fan-ins (bibliography, executive summary), and
  per-deck transform chains. AgentsFlow expresses this natively; Option B
  flattens it and Option C re-implements scheduling by hand.
- Long-running Deep Research makes **telemetry and checkpointing**
  first-order requirements, not nice-to-haves: `on_node_event` feeds the
  HTTP handler's progress surface, and `checkpoint=True` (FEAT-399) makes a
  45-minute research run resumable. Only Option A gets both for free.
- It aligns with the repo's direction: domain flows live in `parrot/flows/`
  built on `bots/flows/` (dev_loop precedent), and it consumes — rather than
  duplicates — FEAT-308 (ResultAgent/infographic), FEAT-398 (groundedness),
  FEAT-273 (ECharts/static-SVG/PDF), FEAT-197 (InfographicToolkit).

**Trade-off accepted**: highest effort of the three, and the per-run
generated `FlowDefinition` (planner output determines node count) adds a
two-phase build step. That cost is bounded — the planner runs first, then a
pure function assembles the definition — and buys per-deck parallelism,
observability, and resumability.

---

## Feature Description

### User-Facing Behavior

```python
from parrot.flows.tales import TalesRunner

runner = TalesRunner(
    thesis="Open-source flight stacks bridge LATAM engineering talent",
    num_decks=4,                      # N research angles to explore
    sources=["web", "deep_research", "arxiv"],   # enabled research nodes
    output_dir="artifacts/tales/flight-stacks/", # filesystem surface
)
result = await runner.run()          # TalesResult manifest

result.decks            # list[ResearchDeck] — structured JSON, per angle
result.slides           # list of per-deck HTML artifact refs (id, url, path)
result.final_document   # print-CSS HTML (slides + bibliography) artifact ref
result.bibliography     # Bibliography model (also embedded in the document)
result.executive_summary
result.infographic      # InfographicRenderResult (html_url / html_inline)
```

Over HTTP (ai-parrot-server): `POST /api/v1/tales` launches a run (thesis +
config), progress streams from `on_node_event`; `GET` endpoints list/serve
the run's artifacts via `ArtifactStore` public URLs. Every artifact is also
written under `output_dir` with a `manifest.json` at its root.

Each deck's JSON carries, per finding: the extracted paragraphs, which tool
produced it, and `SourceClaim` metadata (url, title, authors, publisher,
published_date when discoverable, accessed_date) — the "claims" the user
asked for. The bibliography renders those claims report-style as the final
section. Slides contain charts (only where the deck holds numeric series),
tables, and pull-quotes — no scraped third-party images in v1.

### Internal Behavior

1. **Plan** — planner LLM (structured output) → N `ResearchAngle`s.
2. **Assemble** — a pure function builds the run's `FlowDefinition` (N×M
   research nodes + per-deck chains + fan-ins) and materializes it via
   `AgentsFlow.from_definition(..., node_factories=...)`; research agents are
   registered in an ephemeral `AgentRegistry` for the run.
3. **Research** — per angle, in parallel: WebSearchAgent
   (`use_builtin_search=True`, `contrastive_search=True`,
   `enable_groundedness=True`), Deep Research node
   (`GoogleGenAIClient.deep_research`, background interactions), Arxiv agent
   (`ArxivTool`). Each returns findings + raw source metadata.
4. **Deck build** — merge an angle's outputs into `ResearchDeck` (structured
   output pass normalizes findings into claims; provider grounding metadata
   and `GroundednessReport`s attach to deck provenance).
5. **Slide spec → render** — LLM fills `SlideSpec` (never HTML); the
   deterministic renderer produces per-deck slide HTML (Jinja2 + ECharts
   option-JSON, static-SVG fallback for print).
6. **Fan-ins** — bibliography (deterministic dedupe/format of all
   `SourceClaim`s); executive summary (`SynthesisNode` over all decks).
7. **Final document** — deterministic: slides + bibliography into one
   print-CSS HTML (`@page`, page-break per slide).
8. **Infographic** — summary + decks → `InfographicToolkit` (FEAT-308
   ResultAgent pattern).
9. **Persist** — every artifact through `ArtifactStore.save_artifact` (+
   `get_public_url`), mirrored to `output_dir`, indexed in `manifest.json`
   and the returned `TalesResult`.

### Edge Cases & Error Handling

- **A research node fails** (quota, network): OR-join fan-in — the deck
  builds from surviving sources; the deck records which sources failed.
  A deck with zero surviving sources is dropped with a warning; the run
  degrades, never aborts, as long as ≥1 deck survives.
- **Deep Research latency** (minutes-scale, background interactions): the
  flow runs with `checkpoint=True`; node-event telemetry surfaces progress;
  a per-node timeout (configurable) skips the source on expiry.
- **Groundedness evidence gap** (honest limitation): the FEAT-398 scorer
  verifies against `ToolCall.result` — fully effective for tool-based nodes
  (ArxivTool, search tools). Gemini built-in search and Deep Research don't
  produce parrot `ToolCall`s; for those nodes citation confidence comes from
  provider grounding metadata, and the deck labels each claim's verification
  channel (`groundedness` | `provider_grounding` | `unverified`).
- **Missing publication dates/authors**: `SourceClaim` fields are Optional;
  bibliography renders "n.d."/publisher-only entries rather than inventing
  dates (anti-hallucination stance extends to citations).
- **No chartable data in a deck**: renderer falls back to table/quote
  layouts; charts are emitted only for numeric series present in the deck.
- **Oversized decks**: extracted paragraphs are capped per finding
  (configurable); full raw research output is persisted as a companion
  artifact and linked, never inlined into a slide (FEAT-308's summarize-or-
  link-out rule).
- **Render/persist failure on one deck**: that slide is skipped and noted in
  the manifest; final document and infographic build from surviving slides.
- **`num_decks` bounds**: validated 1..configurable max (default cap ~8) —
  N×M fan-out costs real money; the planner may return fewer angles than N
  if the thesis doesn't decompose.

---

## Capabilities

### New Capabilities
- `tales-research-flow`: `parrot/flows/tales/` package — planner, dynamic
  FlowDefinition assembly, research/deck/render/fan-in node factories,
  `TalesRunner` API.
- `research-deck-models`: Pydantic contracts — `ResearchAngle`,
  `ResearchDeck`, `SourceClaim`, `Bibliography`, `SlideSpec`, `TalesResult`
  (manifest). These models are the interface the follow-up toolkits spec
  implements against.
- `tales-deck-renderer`: deterministic Jinja2 slide templates + ECharts/
  static-SVG chart emission + print-CSS final-document composer.
- `tales-http-handler`: ai-parrot-server endpoint(s) to launch runs, stream
  node-event progress, and serve artifacts.
- `tales-research-source-toolkits` *(follow-up spec — named here, built in
  parallel)*: `WorldBankDataTool` (data.worldbank.org, free JSON API) and
  `EuropeanOpenDataTool` (data.europa.eu, free API) in `parrot_tools`;
  evaluation of Oxford Academic (academic.oup.com) and Gallup as trusted
  origins (Gartner likely not freely queryable). Contract: each tool returns
  findings shaped to `SourceClaim`, so Tales picks them up by adding a
  source node — no flow changes.

### Modified Capabilities
- (none — WebSearchAgent, GoogleGenAIClient.deep_research, ArxivTool,
  InfographicToolkit, ArtifactStore, groundedness are consumed as-is)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/flows/tales/` | creates | new domain-flow package (dev_loop template: definition/factories/nodes/runner) |
| `parrot/bots/flows/flow/flow.py` | depends on | `from_definition(node_factories=...)`, `run_flow`, checkpointing — no changes expected |
| `parrot/bots/search.py` (`WebSearchAgent`) | uses | `use_builtin_search=True` (Gemini internal search), `contrastive_search=True` |
| `parrot/clients/google/client.py` | uses | `deep_research()` — verify preview-model availability/quota |
| `parrot_tools/arxiv_tool.py` | uses | as-is |
| `parrot/security/groundedness/` | uses | `enable_groundedness=True` per research agent |
| `parrot/tools/infographic_toolkit.py` + `bots/flows/result_agent.py` | depends on | FEAT-308/197 for the final infographic |
| `parrot/storage/artifacts.py` (`ArtifactStore`) | uses | persistence + public URLs for all artifacts |
| `parrot/template/engine.py` (`TemplateEngine`) | uses | slide + document Jinja templates |
| `packages/ai-parrot-server/src/parrot/handlers/` | extends | new `tales.py` handler (precedent: `infographic.py`) |
| `packages/ai-parrot-tools/` | extends (follow-up spec) | `tales-research-source-toolkits` |
| `packages/ai-parrot-visualizations/.../a2ui_renderers/pdf.py` | optional depends | weasyprint PDF upgrade path (Open Question) |

No breaking changes; everything is additive and opt-in. No new runtime
dependencies for v1.

---

## Code Context

### User-Provided Code

_None — requirement provided as prose (abstract in the /sdd-brainstorm
invocation). Reference deck-page example:
https://hanademi.com/decks/open-source-flight-stacks-bridge-latam-engineering-talent-20260810-030435/_

### Verified Codebase References

> Package roots: core `packages/ai-parrot/src/parrot/`, tools
> `packages/ai-parrot-tools/src/parrot_tools/`, server
> `packages/ai-parrot-server/src/parrot/`, visualizations
> `packages/ai-parrot-visualizations/src/parrot/`.

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                       # L173
    def add_node(self, node: Node) -> None: ...           # L300
    def add_edge(self, from_: str, to: str, *,            # L317
                 condition: str = "always", predicate=None) -> FlowEdge: ...
    @classmethod
    def from_definition(cls, definition: FlowDefinition, *,          # L428
                        agent_registry=None, node_factories=None,
                        checkpoint=None, ...) -> "AgentsFlow": ...
    async def run_flow(self, ctx) -> FlowResult: ...      # L912
class SynthesisNode(Node): ...                            # L1963 (LLM synthesis over dep results)

# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class Node(BaseModel): ...                                # L68
class AgentNode(Node):                                    # L182
    async def execute(self, ctx, deps, **kwargs): ...     # L270
class StartNode(Node): ...                                # L323
class EndNode(Node): ...                                  # L408

# packages/ai-parrot/src/parrot/bots/search.py
class WebSearchAgent(BasicAgent):                         # L45
    def __init__(self, ..., use_builtin_search: bool = False,
                 contrastive_search: bool = False, synthesize: bool = False,
                 competitor_search: bool = False, **kwargs): ...
    # use_builtin_search=True → Gemini internal Google Search via
    # kwargs['tool_type'] = 'builtin_tools' in _do_search()

# packages/ai-parrot/src/parrot/clients/google/client.py
class GoogleGenAIClient(...):
    async def _deep_research_ask(...): ...                # L5015
    #   model = "deep-research-pro-preview-12-2025"       # L5026
    async def deep_research(self, query, files=None, ...): ...  # L5102 (background=True)

# packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py
class ArxivSearchArgsSchema(AbstractToolArgsSchema): ...  # L13
class ArxivTool(AbstractTool):                            # L36
    # _format_paper returns: title, authors, published, updated, summary,
    # arxiv_id, pdf_url, categories, journal_ref → maps 1:1 onto SourceClaim

# packages/ai-parrot/src/parrot/bots/abstract.py
#   self.enable_groundedness = bool(kwargs.pop('enable_groundedness', False))  # L718
#   (when True, GroundednessGuardrail is registered on the OUTPUT stage)

# packages/ai-parrot/src/parrot/security/groundedness/guardrail.py
class GroundednessGuardrail(Guardrail):
    name = "groundedness"; stages = {GuardrailStage.OUTPUT}; priority = 200
    # FLAG-only; report → AIMessage.metadata["guardrails"]["groundedness"];
    # evidence = AIMessage.tool_calls[].result (ctx.extras["ai_message"])

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                # L180
    async def render(self, template_name, theme, mode,
                     data_variables, blocks=None, ...): ...       # L403
    async def render_template(self, template_name, data=None, ...): ...  # L520

# packages/ai-parrot/src/parrot/bots/flows/result_agent.py (FEAT-308)
@register_agent(name="result-agent")                      # L106
class ResultAgent(Agent): ...                             # L107

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
class FlowResult:
    infographic: Optional["InfographicRenderResult"] = None  # L395 (FEAT-308)

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                                      # L27
    async def save_artifact(...): ...                     # L46
    async def get_public_url(...): ...                    # L177

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py
class PDFRenderer(AbstractA2UIRenderer):                  # L99 (weasyprint; SPK-1)
    async def render(...): ...                            # L102
```

#### Verified Imports
```python
from parrot.bots.flows.flow.flow import AgentsFlow, register_node   # flow.py
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition
from parrot.bots.search import WebSearchAgent                       # bots/search.py:45
from parrot_tools.arxiv_tool import ArxivTool                       # arxiv_tool.py:36
from parrot.tools.infographic_toolkit import InfographicToolkit     # infographic_toolkit.py:180
from parrot.storage.artifacts import ArtifactStore                  # artifacts.py:27
from parrot.security.groundedness.guardrail import GroundednessGuardrail
from parrot.template.engine import TemplateEngine                   # used by InfographicToolkit
```

#### Key Attributes & Constants
- Deep Research agent id → `"deep-research-pro-preview-12-2025"` (clients/google/client.py:5026) — **preview id; confirm availability at spec time**.
- `WebSearchAgent` default LLM → `'google:gemini-3-flash'` (bots/search.py).
- Groundedness toggle → `enable_groundedness` bot kwarg (bots/abstract.py:718).
- Infographic inline threshold → `_INLINE_THRESHOLD = 50_000` bytes (infographic_toolkit.py).
- SPK-1 decision → **weasyprint is the confirmed default PDF backend**; charts must be static SVG on the PDF path (artifacts/spikes/spk1-rasterization/results.md).
- FEAT-273 chart convention → ECharts option-JSON primary + static-SVG pre-render companion (TASK-1731).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/flows/tales/`~~ — created by this feature (no "tales" reference
  anywhere in `parrot/` today; verified by grep).
- ~~`ResearchDeck` / `SourceClaim` / `SlideSpec` / `Bibliography` /
  `ResearchAngle` / `TalesResult` models~~ — created by this feature.
- ~~`WorldBankDataTool` / `EuropeanOpenDataTool` / `OxfordAcademicTool` /
  `GallupTool`~~ — do NOT exist; deferred to the
  `tales-research-source-toolkits` follow-up spec.
- ~~A `DeepResearchAgent` bot class~~ — Deep Research is a **client method**
  (`GoogleGenAIClient.deep_research`), not an agent; Tales must wrap it in a
  node/agent.
- ~~A bibliography/citation formatter anywhere in `parrot/`~~ — none exists.
- ~~`matplotlib` for chart generation~~ — purged from the codebase
  (`sdd/specs/purge-matplotlib-renderer-libs.spec.md`); do not plan
  matplotlib-in-PythonREPL charts.
- ~~Groundedness verification of Gemini built-in search / Deep Research
  output~~ — the scorer needs `ToolCall.result` evidence; those paths don't
  produce parrot ToolCalls (see Edge Cases).
- ~~A generic "deck" template in `infographic_registry`~~ — templates exist
  for infographics (`multi_tab`, `crew_report`), not slide decks; Tales
  ships its own slide/document Jinja templates.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Natural seams: (1) `research-deck-models`
  (pure Pydantic, no deps) → everything else depends on it; (2)
  `tales-deck-renderer` (templates + deterministic composer — testable
  standalone); (3) `tales-research-flow` (nodes + runner); (4)
  `tales-http-handler` (depends on 3). Seams 2 and 3 can proceed in parallel
  once 1 lands.
- **Cross-feature independence**: file-disjoint from in-flight work — all
  new files under `parrot/flows/tales/`, one new server handler, no edits to
  `flow.py`/`crew.py`/`abstract.py`. The **`tales-research-source-toolkits`
  follow-up spec is fully parallel** (separate distribution,
  `parrot_tools/`), coupled only through the `SourceClaim` contract defined
  in seam 1.
- **Recommended isolation**: per-spec for this feature (one worktree,
  tasks mostly sequential with a short parallel window for renderer vs flow
  nodes); the follow-up toolkits spec runs in its own parallel worktree.
- **Rationale**: the internal seams share the models package and converge in
  the runner — worktree-per-task would thrash; the genuine parallelism is
  cross-spec (toolkits), which the named follow-up spec captures.

---

## Open Questions

- [ ] Deep Research model id `deep-research-pro-preview-12-2025` is a
  preview — confirm GA id, quota, and per-run cost ceiling before spec
  freeze; define behavior when the account lacks access (skip node vs fail
  run). — *Owner: Jesús*
- [ ] Groundedness evidence gap for Gemini built-in search / Deep Research
  (no parrot `ToolCall`s): is labeling those claims `provider_grounding`
  acceptable for v1, or should a post-hoc verification pass (e.g. re-fetch
  cited URLs and score extracts) be a follow-up? — *Owner: Jesús*
- [ ] Final PDF: v1 ships print-CSS HTML only (Round-3 decision), but the
  weasyprint `PDFRenderer` already exists (SPK-1/FEAT-273, zero new deps) —
  emit a real `.pdf` artifact too when the `pdf` extra is installed? —
  *Owner: Jesús*
- [ ] Default `num_decks` (proposal: 3) and hard cap (proposal: 8) — N×M
  research calls have real cost/latency. — *Owner: Jesús*
- [ ] Bibliography citation style: house style (site/url/author/date, as in
  the abstract) vs a formal style (APA-ish)? Affects the deterministic
  formatter only. — *Owner: Jesús*
- [ ] HTTP surface shape: single `POST /api/v1/tales` + polling, or
  SSE/WebSocket progress from `on_node_event`? (Handler precedent
  `infographic.py` is request/response.) — *Owner: Jesús*
- [ ] Oxford Academic and Gallup access model (scraping ToS / licensing;
  Gartner almost certainly paywalled) — resolve inside the
  `tales-research-source-toolkits` follow-up spec, not here. — *Owner: Jesús*
- [ ] Deck slide visual identity: adopt the hanademi.com deck page as the
  layout reference for the v1 slide template set? — *Owner: Jesús*
