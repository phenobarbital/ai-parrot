---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: "Tales" — Research Flow with Structured Citations, Decks & Final Report

**Feature ID**: FEAT-425
**Date**: 2026-08-17
**Author**: Jesús Lara (with Claude Code research)
**Status**: draft
**Target version**: 0.26.x
**Brainstorm**: `sdd/proposals/agentcrew-tales-research.brainstorm.md`

> Named after Thales of Miletus. Despite the working slug
> `agentcrew-tales-research`, the orchestration backbone is **AgentsFlow**
> (DAG), decided in brainstorm Round 1 — the pipeline's fan-out → fan-in →
> per-deck transform shape maps to explicit edges, not `AgentCrew.run_flow()`.

---

## 1. Motivation & Business Requirements

### Problem Statement

A user states a **thesis** ("remote work increases regional inequality",
"open-source flight stacks bridge LATAM engineering talent") and wants a
finished, *sourced* research package back — not a wall of unattributed LLM
prose. Today AI-Parrot has every building block (WebSearchAgent with Gemini
built-in search, `GoogleGenAIClient.ask(deep_research=True)`, ArxivTool,
deterministic groundedness scoring, InfographicToolkit, an ArtifactStore, a
weasyprint PDF renderer) but **no flow that assembles them into a research
product**.

Tales closes that gap: a parallel multi-agent investigation whose every
factual claim carries **source metadata** (URL, publication date, authors,
publisher), materialized as research decks (structured JSON), per-deck HTML
slides (charts/tables/quotes), a final print-CSS HTML document with an
APA-ish bibliography (plus a real `.pdf` when the pdf extra is installed),
and an executive summary + summary infographic.

### Goals

- G1. **Thesis → N research decks**: a planner splits the user thesis into a
  configurable number of research angles (**minimum 10, no hard cap** —
  resolved in brainstorm); each angle is researched across *all* enabled
  research sources; one `ResearchDeck` per angle.
- G2. **Every claim is sourced**: findings carry `SourceClaim` metadata
  (url, title, authors, publisher, published_date when discoverable,
  accessed_date, source_tool) and a per-claim verification channel
  (`groundedness` | `provider_grounding` | `unverified`).
- G3. **Per-agent anti-hallucination**: every research agent runs with
  `enable_groundedness=True` (FEAT-398); its `GroundednessReport` lands in
  deck provenance. `provider_grounding` labeling for Gemini built-in
  search / Deep Research is accepted for v1 (resolved in brainstorm).
- G4. **Deterministic rendering**: LLMs only fill structured Pydantic specs
  (`ResearchDeck`, `SlideSpec`); slide/document HTML is produced by pure
  Python (TemplateEngine/Jinja2 + ECharts option-JSON with static-SVG print
  fallback, FEAT-273 convention). No LLM in the render path.
- G5. **Four delivery surfaces in this spec**: Python API (`TalesRunner`),
  aiohttp HTTP handler (POST + polling — resolved in brainstorm),
  filesystem output dir with `manifest.json`, and persistence via
  `ArtifactStore` (public URLs).
- G6. **Final document**: all slides + an **APA-ish** bibliography (resolved
  in brainstorm) as one print-CSS HTML (`@page`, page-break per slide);
  additionally emit a real **`.pdf` artifact when weasyprint is importable**
  (pdf extra — resolved in brainstorm).
- G7. **Executive summary + infographic**: synthesis over all decks, then
  `InfographicToolkit` invocation (FEAT-308 ResultAgent pattern).
- G8. **Contract for future sources**: the `SourceClaim`/research-node
  contract is the interface the separate `research-tools-for-agents` spec
  (World Bank, EU Open Data, Oxford Academic, Gallup) implements against —
  adding a source is adding a node, no flow changes.

### Non-Goals (explicitly out of scope)

- New external data-source toolkits (World Bank, EU Open Data, Oxford
  Academic, Gallup) — they belong to the separate **`research-tools-for-agents`**
  spec (resolved in brainstorm; Gartner is almost certainly paywalled).
- Third-party **image/photo extraction** from source pages (licensing) —
  charts/tables/quotes only in v1; image extraction is a named follow-up.
- SSE/WebSocket progress streaming — the HTTP surface is POST + polling
  (resolved in brainstorm); node events feed the polled status document.
- matplotlib-based chart generation — matplotlib is purged from this
  codebase (`sdd/specs/purge-matplotlib-renderer-libs.spec.md`).
- AgentCrew-based orchestration (brainstorm Option B) and engine-less
  pipeline (Option C) — rejected in brainstorm; see
  `sdd/proposals/agentcrew-tales-research.brainstorm.md`.

---

## 2. Architectural Design

### Overview

Tales is a **domain flow package** at `parrot/flows/tales/`, following the
documented application-flow pattern (`parrot/flows/dev_loop/` template:
`definition.py + factories.py + models/ + nodes/ + runner.py`) built on
`AgentsFlow.from_definition(..., node_factories=...)` so live dependencies
(ArtifactStore, TemplateEngine, toolkits) close over factories instead of
traveling through config dicts.

Execution is **two-phase**: (1) the planner LLM turns the thesis into N
`ResearchAngle`s (structured output); (2) a pure function assembles the
run's `FlowDefinition` (N×M research nodes + per-deck transform chains +
fan-ins) and `run_flow()` executes it with `checkpoint=True` (FEAT-399) so
long Deep Research runs are resumable. Research agents live in an ephemeral
per-run `AgentRegistry`.

Research nodes per angle (v1 sources, M=3):
- **web** — `WebSearchAgent(use_builtin_search=True, contrastive_search=True,
  enable_groundedness=True)` (Gemini internal Google Search via
  `tool_type='builtin_tools'`).
- **deep** — a node calling `GoogleGenAIClient.ask(prompt, deep_research=True)`
  (the flag routes to `_deep_research_ask`, background interactions API).
  v1 is Google-only: no other provider client exposes this flag (verified).
- **arxiv** — an agent carrying `ArxivTool` (`enable_groundedness=True`);
  its result fields map 1:1 onto `SourceClaim`.

Downstream, per angle: `deck_builder` (fan-in of the angle's sources →
`ResearchDeck` via structured output), `slide_spec` (LLM fills `SlideSpec`,
never HTML), `slide_render` (deterministic Jinja2 + ECharts/static-SVG;
visual identity: the hanademi.com deck page is the layout reference —
resolved in brainstorm). Global fan-ins: `bibliography` (deterministic
APA-ish dedupe/format of all SourceClaims), `exec_summary`
(`SynthesisNode`), `final_document` (print-CSS HTML; plus `.pdf` via
weasyprint when importable), `infographic` (`InfographicToolkit`).

All artifacts persist through `ArtifactStore.save_artifact` /
`get_public_url`, mirror to `output_dir`, and are indexed in
`manifest.json` + the returned `TalesResult`.

### Component Diagram

```
TalesRunner.run()
  │ phase 1: planner LLM ──▶ list[ResearchAngle]  (len ≥ 10, no cap)
  │ phase 2: build FlowDefinition ──▶ AgentsFlow.from_definition(node_factories=…, checkpoint=True)
  ▼
start ─▶ per angle i (parallel):
           research[i][web]   ─┐
           research[i][deep]   ├─▶ deck_builder[i] ─▶ slide_spec[i] ─▶ slide_render[i] ─┐
           research[i][arxiv] ─┘   (OR-join)          (structured)     (deterministic)  │
         bibliography  ◀── all decks' SourceClaims (deterministic, APA-ish) ◀───────────┤
         exec_summary  ◀── all decks (SynthesisNode)                                    │
         final_document ◀── slides + bibliography (print-CSS HTML [+ .pdf])             │
         infographic   ◀── exec_summary + decks (InfographicToolkit) ─▶ end ◀───────────┘
  ▼
ArtifactStore + output_dir/manifest.json ──▶ TalesResult
  ▲
TalesHandler (ai-parrot-server): POST /api/v1/tales ─▶ run_id; GET …/{run_id} ─▶ status/manifest
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentsFlow` (`bots/flows/flow/flow.py`) | uses | `from_definition(node_factories=…)`, `run_flow`, `on_node_event`, `checkpoint=True` — no changes |
| `WebSearchAgent` (`bots/search.py`) | uses | `use_builtin_search=True`, `contrastive_search=True`, `enable_groundedness=True` |
| `GoogleGenAIClient` (`clients/google/client.py`) | uses | `ask(deep_research=True)` → `_deep_research_ask` (background interactions) |
| `ArxivTool` (`parrot_tools/arxiv_tool.py`) | uses | as-is; result fields map to `SourceClaim` |
| Groundedness (`security/groundedness/`) | uses | `enable_groundedness=True` per research agent (FEAT-398) |
| `SynthesisNode` (`bots/flows/flow/flow.py`) | uses | executive summary fan-in |
| `InfographicToolkit` + `ResultAgent` (FEAT-308/197) | depends on | final infographic from summary + decks |
| `ArtifactStore` (`storage/artifacts.py`) | uses | persistence + signed public URLs for all artifacts |
| `TemplateEngine` (`template/engine.py`) | uses | slide + document Jinja templates |
| `weasyprint` (lazy, pdf extra) | optional uses | real `.pdf` of the final document; mirror `_import_weasyprint` pattern (`a2ui_renderers/pdf.py:36`) |
| ai-parrot-server `handlers/` | extends | new `handlers/tales.py` (precedent: `handlers/infographic.py`) |
| `research-tools-for-agents` (separate spec) | contract consumer | implements research nodes against `SourceClaim` / research-node contract |

### Data Models

```python
# parrot/flows/tales/models/ — key Pydantic contracts (names are normative)

class ResearchAngle(BaseModel):
    angle_id: str
    title: str
    question: str                 # the sub-thesis to investigate
    rationale: str

class SourceClaim(BaseModel):
    url: str
    title: Optional[str]
    authors: list[str] = []
    publisher: Optional[str]
    published_date: Optional[str]   # ISO date when discoverable; never invented
    accessed_date: str              # ISO date of retrieval
    source_tool: str                # e.g. "web_search", "deep_research", "arxiv_search"
    verification: Literal["groundedness", "provider_grounding", "unverified"]

class Finding(BaseModel):
    text: str                       # extracted paragraph(s), capped
    claims: list[SourceClaim]
    numeric_series: Optional[dict]  # chartable data, when present

class ResearchDeck(BaseModel):
    angle: ResearchAngle
    findings: list[Finding]
    tools_used: list[str]
    groundedness: dict[str, Any] = {}   # per-source GroundednessReport dumps
    failed_sources: list[str] = []

class SlideSpec(BaseModel):             # LLM fills this; never HTML
    deck_ref: str
    layout: str                          # template variant hint
    headline: str
    bullets: list[str]
    charts: list[dict] = []              # ECharts option-JSON payloads
    tables: list[dict] = []
    quotes: list[dict] = []              # quote + SourceClaim ref

class Bibliography(BaseModel):
    entries: list[str]                   # APA-ish formatted, deduped
    claims: list[SourceClaim]

class TalesConfig(BaseModel):
    thesis: str
    num_decks: int = Field(default=10, ge=10)   # minimum 10, NO upper cap (resolved)
    sources: list[str] = ["web", "deep_research", "arxiv"]
    output_dir: Optional[Path] = None
    per_node_timeout: Optional[float] = None
    max_paragraphs_per_finding: int = 6

class ArtifactRef(BaseModel):
    kind: str                            # deck_json | slide_html | final_html | final_pdf | infographic | raw_research
    artifact_id: Optional[str]
    url: Optional[str]
    path: Optional[Path]

class TalesResult(BaseModel):            # the manifest
    thesis: str
    decks: list[ResearchDeck]
    slides: list[ArtifactRef]
    bibliography: Bibliography
    executive_summary: str
    final_document: ArtifactRef
    final_pdf: Optional[ArtifactRef]     # present when weasyprint available
    infographic: Optional[Any]           # InfographicRenderResult
    manifest_path: Optional[Path]
    warnings: list[str] = []
```

### New Public Interfaces

```python
# parrot/flows/tales/runner.py
class TalesRunner:
    def __init__(self, thesis: str, *, num_decks: int = 10,
                 sources: Optional[list[str]] = None,
                 output_dir: Optional[Path] = None,
                 artifact_store: Optional[ArtifactStore] = None,
                 llm: Optional[str] = None, **kwargs) -> None: ...
    async def run(self) -> TalesResult: ...
    # progress: forwards AgentsFlow on_node_event to registered listeners

# packages/ai-parrot-server/src/parrot/handlers/tales.py
class TalesHandler:                      # aiohttp, precedent handlers/infographic.py
    # POST /api/v1/tales               → {"run_id": ...}          (launch)
    # GET  /api/v1/tales/{run_id}      → status + manifest-so-far  (polling)
    # GET  /api/v1/tales/{run_id}/artifacts → ArtifactStore public URLs
```

---

## 3. Module Breakdown

### Module 1: Deck & Config Models
- **Path**: `packages/ai-parrot/src/parrot/flows/tales/models/` (`__init__.py`, `deck.py`, `slides.py`, `config.py`, `result.py`)
- **Responsibility**: All Pydantic contracts (§2 Data Models). This module IS
  the interface the `research-tools-for-agents` spec implements against —
  keep it dependency-light (pydantic + stdlib only).
- **Depends on**: nothing new.

### Module 2: Research Agent & Node Factories
- **Path**: `packages/ai-parrot/src/parrot/flows/tales/factories.py`
- **Responsibility**: Build per-run research agents — WebSearchAgent
  (builtin search + contrastive + groundedness), Deep Research node
  (`GoogleGenAIClient.ask(deep_research=True)`), Arxiv agent — registered in
  an ephemeral `AgentRegistry`; normalize each source's raw output +
  grounding/groundedness metadata into `Finding`/`SourceClaim` lists.
- **Depends on**: Module 1.

### Module 3: Flow Nodes
- **Path**: `packages/ai-parrot/src/parrot/flows/tales/nodes/` (`planner.py`, `deck_builder.py`, `slide_spec.py`, `bibliography.py`, `summary.py`, `document.py`, `infographic.py`)
- **Responsibility**: PlannerNode (thesis → ≥10 `ResearchAngle`s, structured
  output); DeckBuilderNode (per-angle OR-join fan-in → `ResearchDeck`);
  SlideSpecNode (deck → `SlideSpec`, structured output); BibliographyNode
  (deterministic APA-ish formatter + dedupe); ExecSummaryNode (wraps
  `SynthesisNode`/`synthesize_results`); FinalDocumentNode;
  InfographicNode (InfographicToolkit via FEAT-308 pattern). Node classes
  are injected via `node_factories` — do NOT register app-specific types in
  the global `NODE_REGISTRY`.
- **Depends on**: Modules 1–2, Module 4 (document/slide rendering calls).

### Module 4: Deterministic Renderer
- **Path**: `packages/ai-parrot/src/parrot/flows/tales/rendering/` (`slides.py`, `document.py`, `charts.py`, `templates/*.html.j2`)
- **Responsibility**: Jinja2 slide templates (hanademi.com deck page as the
  v1 layout reference); chart emission as ECharts option-JSON (browser path)
  + static SVG (print path, FEAT-273/SPK-1 constraint); print-CSS
  final-document composer (`@page`, page-break per slide, bibliography as
  final section); optional `.pdf` rasterization via lazy weasyprint import
  (mirror `a2ui_renderers/pdf.py:36` `_import_weasyprint`). Pure functions
  over Module-1 models — unit-testable without any LLM.
- **Depends on**: Module 1.

### Module 5: Definition Assembly + Runner
- **Path**: `packages/ai-parrot/src/parrot/flows/tales/definition.py`, `runner.py`, `__init__.py`
- **Responsibility**: Pure function `build_tales_definition(angles, config)
  -> FlowDefinition` (N×M research nodes, per-deck chains, fan-in edges);
  `TalesRunner` (two-phase run, ephemeral `AgentRegistry`,
  `checkpoint=True`, ArtifactStore persistence, `output_dir` mirroring,
  `manifest.json`, `TalesResult` aggregation, node-event forwarding).
- **Depends on**: Modules 1–4.

### Module 6: HTTP Handler
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/tales.py`
- **Responsibility**: POST + polling surface (§2 New Public Interfaces);
  in-memory/redis run registry keyed by `run_id`; status document updated
  from `on_node_event`; artifact listing via `ArtifactStore.get_public_url`.
- **Depends on**: Module 5.

### Module 7: Tests, Fixtures & Docs
- **Path**: `packages/ai-parrot/tests/flows/tales/`, `packages/ai-parrot-server/tests/…`, `docs/flows/tales.md`
- **Responsibility**: §4 test spec + user guide (API + HTTP examples).
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_models_roundtrip` | 1 | Deck/SlideSpec/TalesResult serialize/deserialize; `num_decks` ge=10 enforced; no upper cap |
| `test_source_claim_verification_labels` | 1 | verification ∈ {groundedness, provider_grounding, unverified} |
| `test_factory_websearch_agent_flags` | 2 | agent built with builtin search + contrastive + `enable_groundedness=True` |
| `test_factory_arxiv_mapping` | 2 | ArxivTool result dict → `SourceClaim` (title/authors/published/pdf_url/journal_ref) |
| `test_deep_research_node_google_only` | 2 | non-Google client config → clear error/skip, never AttributeError |
| `test_planner_min_angles` | 3 | planner output < 10 angles → re-ask/pad behavior per §7 |
| `test_deck_builder_or_join_degrade` | 3 | one source failed → deck built from survivors, `failed_sources` recorded |
| `test_bibliography_apa_dedupe` | 3 | duplicate URLs deduped; APA-ish entry; missing dates render "n.d." (never invented) |
| `test_slide_render_deterministic` | 4 | same SlideSpec → byte-identical HTML; charts only when `numeric_series` present |
| `test_document_print_css` | 4 | final HTML has `@page` rules + page-break per slide + bibliography last |
| `test_pdf_optional` | 4 | weasyprint absent → no `.pdf`, warning in manifest; present → `.pdf` artifact emitted |
| `test_build_definition_shape` | 5 | N angles × M sources → expected node/edge counts, valid `FlowDefinition` |
| `test_runner_manifest` | 5 | artifacts persisted (mock store), `manifest.json` written, `TalesResult` complete |
| `test_handler_post_poll` | 6 | POST returns run_id; GET reflects node-event progress; artifact listing |

### Integration Tests
| Test | Description |
|---|---|
| `test_tales_e2e_mocked_llm` | Full run with mocked LLM/tool responses: thesis → ≥10 decks → slides → document (+pdf if available) → infographic; manifest complete |
| `test_tales_checkpoint_resume` | Kill after research phase; resume via FEAT-399 checkpoint completes the run |
| `test_tales_partial_sources` | deep_research disabled/unavailable → run degrades, decks cite web+arxiv only |

### Test Data / Fixtures
```python
@pytest.fixture
def mock_research_outputs():
    """Canned WebSearch/DeepResearch/Arxiv responses with known citation
    metadata, incl. one duplicate URL (dedupe) and one date-less source (n.d.)."""

@pytest.fixture
def sample_slide_spec():
    """SlideSpec with one chart series, one table, one quote — golden-file
    HTML comparison for determinism."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/flows/tales/ -v`)
- [ ] Integration tests pass (mocked-LLM e2e, checkpoint resume, partial sources)
- [ ] A run produces, for N angles: N `ResearchDeck` JSON artifacts, N slide
      HTML artifacts, 1 final print-CSS HTML (slides + APA-ish bibliography
      as final section), 1 executive summary, 1 infographic — all persisted
      via `ArtifactStore` AND mirrored under `output_dir` with `manifest.json`
- [ ] `num_decks` defaults to 10, rejects < 10, has **no upper cap**
- [ ] Every `Finding` carries ≥1 `SourceClaim` with `source_tool` and
      `verification` set; missing publication dates render as "n.d.", never invented
- [ ] Research agents are constructed with `enable_groundedness=True`;
      `GroundednessReport`s appear in deck provenance for tool-based sources
- [ ] Rendering is deterministic: same `SlideSpec`/deck inputs → byte-identical
      HTML (golden-file test); **no matplotlib anywhere** in the feature
- [ ] With weasyprint importable, a real `.pdf` of the final document is
      emitted; without it, the run succeeds with a manifest warning
- [ ] A failed research source degrades (OR-join): deck built from surviving
      sources with `failed_sources` recorded; run aborts only if ALL decks fail
- [ ] HTTP surface: `POST /api/v1/tales` returns `run_id`; polling GET
      reflects node-event progress; artifacts listed with public URLs
- [ ] No changes to `flow.py`, `crew.py`, `abstract.py`, or any existing
      public API (purely additive feature)
- [ ] Documentation added at `docs/flows/tales.md`

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified 2026-08-17 against `dev`. Package roots: core
> `packages/ai-parrot/src/parrot/`, tools `packages/ai-parrot-tools/src/parrot_tools/`,
> server `packages/ai-parrot-server/src/parrot/`, visualizations
> `packages/ai-parrot-visualizations/src/parrot/`.

### Verified Imports
```python
from parrot.bots.flows.flow.flow import AgentsFlow            # flow/flow.py:173
from parrot.bots.flows.flow.definition import (               # flow/definition.py
    FlowDefinition, NodeDefinition, EdgeDefinition,
)
from parrot.bots.search import WebSearchAgent                 # bots/search.py:45
from parrot_tools.arxiv_tool import ArxivTool                 # arxiv_tool.py:36
from parrot.tools.infographic_toolkit import InfographicToolkit  # infographic_toolkit.py:180
from parrot.storage.artifacts import ArtifactStore            # storage/artifacts.py:27
from parrot.security.groundedness.guardrail import GroundednessGuardrail
from parrot.template.engine import TemplateEngine             # used by InfographicToolkit
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                       # L173
    def add_node(self, node: Node) -> None: ...           # L300
    def add_edge(self, from_: str, to: str, *,            # L317
                 condition: str = "always", predicate=None) -> FlowEdge: ...
    @classmethod
    def from_definition(cls, definition: FlowDefinition, *,      # L428
                        agent_registry=None, node_factories=None,
                        checkpoint=None, ...) -> "AgentsFlow": ...
    async def run_flow(self, ctx) -> FlowResult: ...      # L912
class SynthesisNode(Node): ...                            # L1963

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
                 **kwargs): ...
    # use_builtin_search=True → Gemini internal Google Search via
    # kwargs['tool_type'] = 'builtin_tools' in _do_search()
    # default llm = 'google:gemini-3-flash'

# packages/ai-parrot/src/parrot/clients/google/client.py
class GoogleGenAIClient(...):
    async def ask(self, ..., deep_research: bool = False, ...): ...        # L2876
    #   if deep_research: → return await self._deep_research_ask(...)      # L2914
    async def ask_stream(self, ..., deep_research: bool = False, ...): ... # L3783
    async def _deep_research_ask(...): ...                                 # L5015
    #   model = "deep-research-pro-preview-12-2025"                        # L5026
    async def deep_research(self, query, files=None, ...): ...             # L5102

# packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py
class ArxivSearchArgsSchema(AbstractToolArgsSchema): ...  # L13
class ArxivTool(AbstractTool):                            # L36
    # _format_paper → title, authors, published, updated, summary,
    # arxiv_id, pdf_url, categories, journal_ref

# packages/ai-parrot/src/parrot/bots/abstract.py
#   self.enable_groundedness = bool(kwargs.pop('enable_groundedness', False))  # L718
#   (True → GroundednessGuardrail registered on the OUTPUT stage)

# packages/ai-parrot/src/parrot/security/groundedness/guardrail.py
class GroundednessGuardrail(Guardrail):
    name = "groundedness"; stages = {GuardrailStage.OUTPUT}; priority = 200
    # FLAG-only; report → AIMessage.metadata["guardrails"]["groundedness"];
    # evidence = AIMessage.tool_calls[].result

# packages/ai-parrot/src/parrot/tools/infographic_toolkit.py
class InfographicToolkit(AbstractToolkit):                # L180
    async def render(self, template_name, theme, mode,
                     data_variables, blocks=None, ...): ...      # L403
    async def render_template(self, template_name, data=None, ...): ...  # L520

# packages/ai-parrot/src/parrot/bots/flows/result_agent.py (FEAT-308)
@register_agent(name="result-agent")                      # L106
class ResultAgent(Agent): ...                             # L107
#   NOTE: @register_agent requires the keyword form (name=...) — positional raises TypeError.

# packages/ai-parrot/src/parrot/bots/flows/core/result.py
class FlowResult:
    infographic: Optional["InfographicRenderResult"] = None  # L395 (FEAT-308)

# packages/ai-parrot/src/parrot/storage/artifacts.py
class ArtifactStore:                                      # L27
    async def save_artifact(...): ...                     # L46
    async def get_public_url(...): ...                    # L177

# packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/pdf.py
def _import_weasyprint(): ...                             # L36 (lazy-import pattern to mirror)
class PDFRenderer(AbstractA2UIRenderer):                  # L99 (weasyprint; SPK-1 backend)
    async def render(...): ...                            # L102
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `build_tales_definition()` | `AgentsFlow.from_definition(node_factories=…)` | classmethod call | `flow/flow.py:428` |
| research node (web) | `WebSearchAgent.ask()` | agent call | `bots/search.py:45` |
| research node (deep) | `GoogleGenAIClient.ask(deep_research=True)` | flag on ask | `clients/google/client.py:2876` |
| research node (arxiv) | `ArxivTool._execute()` via agent tools | tool call | `arxiv_tool.py:36` |
| deck provenance | `AIMessage.metadata["guardrails"]["groundedness"]` | metadata read | `groundedness/guardrail.py` |
| ExecSummaryNode | `SynthesisNode` / `synthesize_results` | node reuse | `flow/flow.py:1963` |
| InfographicNode | `InfographicToolkit.render` / `render_template` | toolkit call | `infographic_toolkit.py:403/520` |
| persistence | `ArtifactStore.save_artifact` / `get_public_url` | method calls | `storage/artifacts.py:46/177` |
| PDF emission | weasyprint via lazy import | `_import_weasyprint` pattern | `a2ui_renderers/pdf.py:36` |
| `TalesHandler` | aiohttp handler registration | precedent | `packages/ai-parrot-server/src/parrot/handlers/infographic.py` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/flows/tales/`~~ — created by this feature (no "tales" reference
  in `parrot/` today; verified by grep).
- ~~`ResearchAngle` / `SourceClaim` / `Finding` / `ResearchDeck` /
  `SlideSpec` / `Bibliography` / `TalesConfig` / `TalesResult`~~ — created
  by this feature (Module 1).
- ~~`deep_research` flag on any non-Google client~~ — ONLY
  `clients/google/client.py` implements it (verified by grep across
  `parrot/clients/`); gpt.py/claude.py/bedrock.py/groq.py/grok.py do NOT.
- ~~A `DeepResearchAgent` bot class~~ — Deep Research is the `ask()` flag
  above, not an agent; Tales wraps it in a node.
- ~~`WorldBankDataTool` / `EuropeanOpenDataTool` / `OxfordAcademicTool` /
  `GallupTool`~~ — deferred to the separate `research-tools-for-agents` spec.
- ~~A bibliography/citation formatter anywhere in `parrot/`~~ — none exists;
  Module 3 creates the APA-ish formatter.
- ~~`matplotlib`~~ — purged (`sdd/specs/purge-matplotlib-renderer-libs.spec.md`);
  charts are ECharts option-JSON + static SVG only.
- ~~Groundedness verification of Gemini built-in search / Deep Research
  output~~ — scorer needs `ToolCall.result` evidence; those paths produce
  none → label `provider_grounding` (resolved in brainstorm).
- ~~A generic "deck"/slide template in `infographic_registry`~~ — only
  infographic templates exist (`multi_tab`, `crew_report`); Module 4 ships
  Tales' own Jinja slide/document templates.
- ~~SSE/WebSocket progress endpoints~~ — out of scope; POST + polling only.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Domain-flow package layout per `parrot/flows/dev_loop/`
  (`definition.py + factories.py + models/ + nodes/ + runner.py`).
- Inject node types via `from_definition(node_factories=…)`; do NOT touch
  the global `NODE_REGISTRY`.
- Async-first throughout; Pydantic for every contract; `self.logger`.
- ECharts option-JSON primary + static-SVG pre-render for anything that
  must survive weasyprint (executes no JS) — SPK-1 constraint
  (`artifacts/spikes/spk1-rasterization/results.md`).
- Lazy weasyprint import exactly like `a2ui_renderers/pdf.py:36`; the pdf
  extra must remain optional.
- Summarize-or-link-out for oversized content (FEAT-308 rule): raw research
  output persists as a companion artifact, never inlined into a slide.

### Known Risks / Gotchas
- **Deep Research latency/cost** (minutes-scale background interactions ×
  ≥10 angles): run with `checkpoint=True`; per-node timeout skips the
  source on expiry; document expected cost per run.
- **Planner returns < 10 angles**: re-prompt once with explicit count; if
  still short, pad by decomposing the widest angle; never silently run with
  fewer (AC pins the minimum).
- **≥10 decks × 3 sources = ≥30 research calls**: no hard cap is enforced
  (resolved) — surface projected call counts in the run log and status doc
  before the research phase starts.
- **Groundedness evidence gap**: only tool-based sources yield
  `ToolCall.result` evidence; deck labels each claim's channel; v1 accepts
  `provider_grounding` (resolved).
- **OR-join degrade ordering**: a deck with zero surviving sources is
  dropped with a warning; the run aborts only if all decks drop.
- **Citation honesty**: `published_date` is Optional; APA-ish formatter
  renders "n.d." — inventing dates is a spec violation.
- **`num_decks ≥ 10` floor** may surprise API users expecting small cheap
  runs — document prominently in `docs/flows/tales.md` and the handler's
  400 error message.
- **Dynamic FlowDefinition per run**: build-then-run two-phase; keep
  `build_tales_definition()` a pure function so it is exhaustively
  unit-testable without executing anything.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `jinja2` (via `TemplateEngine`) | existing | slide + document templates |
| `arxiv` | existing | ArxivTool backend |
| `google-genai` | existing | built-in search + Deep Research interactions |
| `weasyprint` | existing optional (pdf extra) | real `.pdf` of final document |
| — | — | **no new runtime dependencies** |

---

## 8. Open Questions

> All brainstorm questions were resolved before this spec (see
> `sdd/proposals/agentcrew-tales-research.brainstorm.md`).

- [x] Deep Research mechanism — *Resolved in brainstorm*: it is a flag of
  the `ask()` method on `GoogleGenAIClient` (verified: Google-only today),
  not a model/agent of its own.
- [x] Groundedness evidence gap for built-in search / Deep Research —
  *Resolved in brainstorm*: `provider_grounding` labeling is acceptable in v1.
- [x] Real PDF artifact in addition to print-CSS HTML — *Resolved in
  brainstorm*: yes — emit `.pdf` via weasyprint when the pdf extra is installed.
- [x] `num_decks` default/cap — *Resolved in brainstorm*: minimum decks is
  10, with no hard cap.
- [x] Bibliography citation style — *Resolved in brainstorm*: APA-ish format.
- [x] HTTP surface shape — *Resolved in brainstorm*: `POST /api/v1/tales`
  + polling.
- [x] Oxford Academic / Gallup access model — *Resolved in brainstorm*: not
  in this scope; handled by the separate `research-tools-for-agents` spec.
- [x] Slide visual identity — *Resolved in brainstorm*: yes — the
  hanademi.com deck page is the layout reference for the v1 templates.
- [ ] Handler run-registry backend (in-memory vs redis) for `run_id`
  polling state — decide during Module 6 implementation. — *Owner: Jesús*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  (`feat-425-agentcrew-tales-research`), tasks sequential.
- **Short parallel window**: Modules 2 (factories) and 4 (renderer) are
  independent once Module 1 lands — may interleave inside the same worktree,
  not separate worktrees.
- **Cross-feature dependencies**: none to merge first — all new files under
  `parrot/flows/tales/` + one new server handler; no edits to `flow.py`,
  `crew.py`, or `abstract.py`. The separate `research-tools-for-agents`
  spec consumes Module 1's `SourceClaim` contract and can proceed in its
  own worktree in parallel once Module 1 is merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-17 | Jesús Lara + Claude Code | Initial draft from brainstorm (all 8 open questions pre-resolved) |
