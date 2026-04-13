# Feature Specification: Intelligent Extraction Pipeline for ScrapingAgent

**Feature ID**: FEAT-096
**Date**: 2026-04-13
**Author**: Jesus (architect) + Claude (design partner)
**Status**: draft
**Target version**: 1.x
**Brainstorm**: `sdd/proposals/intelligent-scraping-pipeline.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `WebScrapingLoader` extracts web page content as flat text/markdown,
producing Documents via tag-based fragmentation or full-page markdown. This approach
fails for **structured commercial pages** (e.g., att.com/prepaid/, Amazon product
listings, telecom plan catalogs) because:

1. **Context collapse**: Stripping tags produces text where "$30/mo" loses its
   association with "AT&T Prepaid 5 GB plan".
2. **Noise pollution**: Navigation menus, footers, legal disclaimers contaminate
   RAG chunks.
3. **No semantic structure**: RAG chatbots cannot answer comparative queries like
   "Which plan has the most data under $50?" because plans aren't discrete entities.
4. **Per-site developer effort**: Writing CSS selectors for each client site doesn't scale.

### Goals

- Enable LLM-driven plan generation that analyzes a page and produces an
  `ExtractionPlan` describing what entities and fields to extract
- Translate ExtractionPlans into `ScrapingPlan` format for mechanical execution
  by WebScrapingToolkit (no LLM during extraction)
- Support pre-built (developer-authored) ExtractionPlans for known sites
- Cache successful ExtractionPlans for reuse via a dedicated registry
- Post-extraction LLM "recall" step to generate rag_text and catch missed data
- Output `List[Document]` with entity-level granularity, ready for vector store

### Non-Goals (explicitly out of scope)

- Delta extraction (compare with previous run, update only changed entities)
- Visual extraction via multimodal LLM (screenshots, images, charts)
- Cross-page entity merging (plan overview + detail page into single Document)
- Extraction analytics dashboard
- CLI tool for ExtractionPlan authoring (future feature)
- Modifying WebScrapingLoader — it remains as-is for simple sites

---

## 2. Architectural Design

### Overview

The Intelligent Extraction Pipeline adds a new orchestration method
`extract_documents()` to `ScrapingAgent` that implements a 5-phase pipeline:

1. **Plan Resolution** — Check for explicit/cached/pre-built ExtractionPlan
2. **Navigate & Download** — Use existing ScrapingPlan/WebScrapingToolkit to load page
3. **LLM Reconnaissance** — Analyze page content, produce ExtractionPlan, translate to ScrapingPlan
4. **Mechanical Extraction** — Execute translated ScrapingPlan via WebScrapingToolkit
5. **LLM Recall** — Post-process: generate rag_text, fill gaps, catch missed entities
6. **Document Assembly** — Convert extracted entities to `List[Document]`

**Key architectural principle**: LLM is used ONLY for plan generation (Phase 3) and
post-extraction recall (Phase 5). Extraction itself (Phase 4) is purely mechanical
via Selenium-driven plan execution.

### Component Diagram

```
Handler / User
    |
    |  "Extract prepaid plans from att.com/prepaid/"
    v
+---------------------------------------------------------------+
|                      ScrapingAgent                             |
|                   (BaseBot + LLM + Tools)                      |
+---------------------------------------------------------------+
|                                                                |
|  +----------------------------------------------------------+ |
|  |  Phase 1: PLAN RESOLUTION                                 | |
|  |  1. Explicit ExtractionPlan provided?         --> USE     | |
|  |  2. Cached plan in ExtractionPlanRegistry?    --> USE     | |
|  |  3. Pre-built plan for domain?                --> USE     | |
|  |  4. None available?  --> Run LLM Reconnaissance (Phase 3) | |
|  +-----------------------------+----------------------------+  |
|                                |                               |
|                                v                               |
|  +----------------------------------------------------------+ |
|  |  Phase 2: NAVIGATE & DOWNLOAD                             | |
|  |  Input:  URL + optional navigation ScrapingPlan           | |
|  |  Tool:   WebScrapingToolkit.scrape()                      | |
|  |  Output: ScrapingResult (HTML + BeautifulSoup)            | |
|  +-----------------------------+----------------------------+  |
|                                |                               |
|       [only if no ExtractionPlan from Phase 1]                 |
|                                v                               |
|  +----------------------------------------------------------+ |
|  |  Phase 3: LLM RECONNAISSANCE                              | |
|  |  Input:  cleaned HTML content + objective                  | |
|  |  Tool:   ExtractionPlanGenerator.generate()               | |
|  |  Output: ExtractionPlan (entities, fields, selectors)     | |
|  +-----------------------------+----------------------------+  |
|                                |                               |
|                                v                               |
|  +----------------------------------------------------------+ |
|  |  Phase 3b: PLAN TRANSLATION                               | |
|  |  Input:  ExtractionPlan                                   | |
|  |  Method: ExtractionPlan.to_scraping_plan()                | |
|  |  Output: ScrapingPlan (steps + selectors for toolkit)     | |
|  +-----------------------------+----------------------------+  |
|                                |                               |
|                                v                               |
|  +----------------------------------------------------------+ |
|  |  Phase 4: MECHANICAL EXTRACTION                           | |
|  |  Input:  ScrapingResult.bs_soup + translated ScrapingPlan | |
|  |  Tool:   WebScrapingToolkit.scrape() with selectors       | |
|  |  Output: ScrapingResult.extracted_data (Dict[str, Any])   | |
|  +-----------------------------+----------------------------+  |
|                                |                               |
|                                v                               |
|  +----------------------------------------------------------+ |
|  |  Phase 5: LLM RECALL                                      | |
|  |  Input:  extracted entities + page HTML excerpt            | |
|  |         + ExtractionPlan entity definitions               | |
|  |  Output: enriched entities with rag_text + gap-filled     | |
|  +-----------------------------+----------------------------+  |
|                                |                               |
|                                v                               |
|  +----------------------------------------------------------+ |
|  |  Phase 6: DOCUMENT ASSEMBLY                               | |
|  |  Input:  List[ExtractedEntity] + metadata                 | |
|  |  Output: List[Document] (page_content=rag_text)           | |
|  +----------------------------------------------------------+ |
|                                                                |
|  +----------------------------------------------------------+ |
|  |  PLAN CACHING (fire-and-forget on success)                | |
|  |  Save ExtractionPlan to ExtractionPlanRegistry            | |
|  +----------------------------------------------------------+ |
+---------------------------------------------------------------+
         |
         v
   List[Document]  -->  VectorStore / KnowledgeBase
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ScrapingAgent` (BaseBot) | extends | Add `extract_documents()`, recall, document assembly methods |
| `WebScrapingToolkit` | uses | Execute translated ScrapingPlans for navigation and extraction |
| `ScrapingPlan` | depends on | Translation target from ExtractionPlan |
| `PlanRegistry` | pattern-reuse | Extract `BasePlanRegistry[T]` generic; create `ExtractionPlanRegistry` |
| `PlanGenerator` | pattern-reuse | ExtractionPlanGenerator follows same architecture |
| `ScrapingResult` | uses | Source of HTML + BeautifulSoup + extracted_data |
| `Document` | uses | Output model for vector store ingestion |

### Data Models

```python
# New Pydantic models — all in extraction_models.py

class EntityFieldSpec(BaseModel):
    """Specification for a single field within an entity."""
    name: str                           # e.g. "price_monthly"
    description: str                    # Hint for the LLM extractor
    field_type: str = "text"            # text | number | currency | url | boolean | list
    required: bool = True
    selector: Optional[str] = None      # CSS selector hint
    selector_type: str = "css"          # css | xpath
    extract_from: str = "text"          # text | attribute | html
    attribute: Optional[str] = None     # For extract_from="attribute"

class EntitySpec(BaseModel):
    """Specification for one type of entity to extract."""
    entity_type: str                    # e.g. "prepaid_plan"
    description: str                    # What this entity represents
    fields: List[EntityFieldSpec]
    repeating: bool = True              # Multiple instances on page?
    container_selector: Optional[str] = None  # CSS selector for repeating container
    container_selector_type: str = "css"

class ExtractionPlan(BaseModel):
    """Rich schema describing WHAT to extract — translates to ScrapingPlan for execution."""
    # Identity (reuse utility functions from plan.py)
    name: Optional[str] = None
    url: str
    domain: str = ""                    # Auto-derived from url
    objective: str
    fingerprint: str = ""               # URL-based fingerprint for cache lookup

    # Extraction schema
    entities: List[EntitySpec]
    ignore_sections: List[str] = []     # Sections to skip (nav, footer, etc.)
    page_category: str = ""             # e.g. "telecom_prepaid_plans"

    # Strategy & provenance
    extraction_strategy: str = "hybrid" # hybrid | css
    source: str = "llm"                 # llm | developer | cache
    version: int = 1
    confidence: float = 0.0

    # Cache lifecycle
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0

    def to_scraping_plan(self) -> "ScrapingPlan":
        """Translate entity/field specs into ScrapingPlan selectors."""
        ...

class ExtractedEntity(BaseModel):
    """A single structured entity extracted from a page."""
    entity_type: str
    fields: Dict[str, Any]
    source_url: str
    confidence: float = 0.0
    raw_text: Optional[str] = None
    rag_text: str = ""                  # Generated by LLM recall step

class ExtractionResult(BaseModel):
    """Complete result from an extraction run."""
    url: str
    objective: str
    entities: List[ExtractedEntity]
    plan_used: ExtractionPlan
    extraction_strategy: str
    total_entities: int = 0
    success: bool = True
    error_message: Optional[str] = None
    elapsed_seconds: float = 0.0
```

### New Public Interfaces

```python
# On ScrapingAgent (parrot/bots/scraper/scraper.py)
class ScrapingAgent(BaseBot):
    async def extract_documents(
        self,
        url: str,
        objective: str,
        extraction_plan: Optional[ExtractionPlan] = None,
        scraping_plan: Optional[ScrapingPlan] = None,
        save_plan: bool = True,
        crawl: bool = False,
        depth: int = 0,
        max_pages: int = 10,
        follow_pattern: Optional[str] = None,
    ) -> List[Document]:
        """High-level entry point: scrape + extract + recall + return Documents."""
        ...
```

---

## 3. Module Breakdown

> These directly map to Task Artifacts in Phase 2.

### Module 1: ExtractionPlan Data Models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py`
- **Responsibility**: Pydantic models for `EntityFieldSpec`, `EntitySpec`, `ExtractionPlan`,
  `ExtractedEntity`, `ExtractionResult`. Includes `to_scraping_plan()` translation method.
  Reuses `_normalize_url()`, `_compute_fingerprint()`, `_sanitize_domain()` from `plan.py`.
- **Depends on**: `plan.py` (ScrapingPlan, utility functions)

### Module 2: BasePlanRegistry Generic Extraction
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/base_registry.py`
- **Responsibility**: Extract a generic `BasePlanRegistry[T]` from the existing `PlanRegistry`.
  Both `PlanRegistry` (ScrapingPlan) and `ExtractionPlanRegistry` (ExtractionPlan) inherit
  from it. Provides: `load()`, `lookup()` (3-tier), `register()`, `touch()`, `remove()`,
  `invalidate()`, `list_all()`.
- **Depends on**: Module 1 (ExtractionPlan model), existing `plan.py` and `registry.py`

### Module 3: ExtractionPlanRegistry
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_registry.py`
- **Responsibility**: Disk-backed registry for ExtractionPlans using `BasePlanRegistry[ExtractionPlan]`.
  Adds extraction-specific cache lifecycle: success/failure counting, invalidation
  after 3 consecutive failures, pre-built plan loading from a well-known directory.
- **Depends on**: Module 1, Module 2

### Module 4: ExtractionPlanGenerator (LLM Reconnaissance)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_plan_generator.py`
- **Responsibility**: LLM-driven reconnaissance. Input: cleaned HTML content + objective.
  Output: validated `ExtractionPlan`. Follows `PlanGenerator` architecture: build prompt,
  call LLM `complete()`, parse JSON response. Content preparation: strip `<script>`,
  `<style>`, `<noscript>`, extract `<main>`/`<article>`, truncate to ~8K tokens.
  Uses HTML format (not markdown) for LLM input — preserves CSS classes and DOM nesting
  for accurate selector generation.
- **Depends on**: Module 1

### Module 5: RecallProcessor (Post-Extraction LLM)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/recall_processor.py`
- **Responsibility**: Single post-extraction LLM call that receives: extracted entities,
  page HTML excerpt (sections matching selectors + 500-token context window), and
  ExtractionPlan entity definitions. Generates `rag_text` for each entity, fills data
  gaps, flags missed entities. Returns enriched `List[ExtractedEntity]`.
- **Depends on**: Module 1

### Module 6: ScrapingAgent.extract_documents() Orchestration
- **Path**: `packages/ai-parrot/src/parrot/bots/scraper/scraper.py`
- **Responsibility**: Add `extract_documents()` method to ScrapingAgent implementing
  the full 5-phase pipeline. Plan resolution chain (explicit → cached → pre-built → LLM recon).
  Entity-to-Document conversion (`_entities_to_documents()`). Auto-save successful plans.
  Crawl mode: apply ExtractionPlan across multiple pages with optimistic plan reuse.
  Wires together Modules 1-5.
- **Depends on**: Module 1, Module 3, Module 4, Module 5

### Module 7: Pre-built ExtractionPlans
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_plans/_prebuilt/`
- **Responsibility**: Hand-authored JSON ExtractionPlan files for common site patterns.
  Initial set: `generic_ecommerce.json`, `generic_telecom.json`. Loaded into
  ExtractionPlanRegistry at initialization with `source="developer"`.
- **Depends on**: Module 1, Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_entity_field_spec_validation` | Module 1 | Validates EntityFieldSpec with all field_type values |
| `test_entity_spec_validation` | Module 1 | Validates EntitySpec with repeating/non-repeating entities |
| `test_extraction_plan_auto_fields` | Module 1 | Verifies domain, name, fingerprint auto-population |
| `test_extraction_plan_to_scraping_plan` | Module 1 | Translation produces valid ScrapingPlan with correct selectors |
| `test_extraction_plan_serialization` | Module 1 | JSON round-trip (serialize → deserialize) preserves all fields |
| `test_base_registry_lookup_exact` | Module 2 | Exact fingerprint match returns correct entry |
| `test_base_registry_lookup_prefix` | Module 2 | Path-prefix match works for URL variants |
| `test_base_registry_lookup_domain` | Module 2 | Domain-only fallback match works |
| `test_extraction_registry_invalidation` | Module 3 | Plan invalidated after 3 consecutive failures |
| `test_extraction_registry_prebuilt_loading` | Module 3 | Pre-built plans loaded with source="developer" |
| `test_plan_generator_prompt_construction` | Module 4 | Prompt includes objective, URL, and ExtractionPlan schema |
| `test_plan_generator_parse_valid_json` | Module 4 | Valid LLM JSON response parsed into ExtractionPlan |
| `test_plan_generator_parse_code_fenced_json` | Module 4 | Code-fenced JSON response handled correctly |
| `test_plan_generator_content_cleaning` | Module 4 | HTML cleaning strips scripts, styles, extracts main content |
| `test_recall_processor_generates_rag_text` | Module 5 | rag_text generated for each entity |
| `test_recall_processor_fills_gaps` | Module 5 | Missing fields populated from page content |
| `test_entities_to_documents` | Module 6 | ExtractedEntity list converted to Document list with correct metadata |

### Integration Tests

| Test | Description |
|---|---|
| `test_extraction_plan_to_scraping_execution` | ExtractionPlan → ScrapingPlan → WebScrapingToolkit → ScrapingResult with extracted_data |
| `test_extract_documents_with_prebuilt_plan` | Full pipeline with pre-built ExtractionPlan (Path B: skip recon) |
| `test_extract_documents_full_pipeline` | Full pipeline with LLM recon + extraction + recall (Path A: mock LLM) |
| `test_extract_documents_cached_plan` | Second run uses cached plan from registry (Path D) |
| `test_extract_documents_cache_invalidation` | Failed extraction invalidates cache, triggers re-recon |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_telecom_html():
    """HTML simulating AT&T-style page with multiple plan cards."""
    return """
    <html><body>
    <nav>Menu items...</nav>
    <main>
      <div class="plan-card">
        <h3>5 GB Plan</h3>
        <span class="price">$30/mo</span>
        <ul><li>5GB Data</li><li>Unlimited Talk</li></ul>
      </div>
      <div class="plan-card">
        <h3>15 GB Plan</h3>
        <span class="price">$40/mo</span>
        <ul><li>15GB Data</li><li>Unlimited Talk</li><li>Hotspot</li></ul>
      </div>
    </main>
    <footer>Legal text...</footer>
    </body></html>
    """

@pytest.fixture
def sample_extraction_plan():
    """Pre-built ExtractionPlan for telecom plan cards."""
    return ExtractionPlan(
        url="https://example.com/plans",
        objective="Extract all prepaid plans",
        entities=[
            EntitySpec(
                entity_type="prepaid_plan",
                description="A prepaid mobile phone plan",
                fields=[
                    EntityFieldSpec(name="plan_name", description="Plan title", selector="h3"),
                    EntityFieldSpec(name="price", description="Monthly price", field_type="currency", selector=".price"),
                    EntityFieldSpec(name="features", description="Plan features", field_type="list", selector="ul li", extract_from="text"),
                ],
                container_selector=".plan-card",
            )
        ],
        page_category="telecom_prepaid_plans",
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `ExtractionPlan.to_scraping_plan()` produces valid ScrapingPlan that WebScrapingToolkit executes
- [ ] `ExtractionPlanRegistry` persists plans to disk and supports 3-tier lookup (exact, prefix, domain)
- [ ] Plans are invalidated after 3 consecutive extraction failures
- [ ] `ExtractionPlanGenerator` produces valid ExtractionPlan from HTML + objective via LLM
- [ ] HTML content cleaning strips `<script>`, `<style>`, `<noscript>`, extracts `<main>`
- [ ] `RecallProcessor` generates rag_text for all extracted entities in a single LLM call
- [ ] `ScrapingAgent.extract_documents()` returns `List[Document]` with entity-level granularity
- [ ] Each Document has `page_content=rag_text` and metadata with structured fields
- [ ] Pre-built JSON plans load into registry at initialization with `source="developer"`
- [ ] Cached plans are reused on subsequent calls to same URL/domain
- [ ] All unit tests pass (`pytest` on affected packages)
- [ ] All integration tests pass with mock LLM and local test HTML
- [ ] No breaking changes to existing ScrapingAgent, WebScrapingToolkit, or PlanRegistry APIs
- [ ] `BasePlanRegistry[T]` generic works for both ScrapingPlan and ExtractionPlan

---

## 6. Codebase Contract

> **CRITICAL -- Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# These imports have been confirmed to work (2026-04-13):
from parrot_tools.scraping.plan import ScrapingPlan, PlanRegistryEntry  # plan.py:59, :112
from parrot_tools.scraping.plan import _normalize_url, _compute_fingerprint, _sanitize_domain  # plan.py:18, :31, :47
from parrot_tools.scraping.registry import PlanRegistry                 # registry.py:23
from parrot_tools.scraping.plan_generator import PlanGenerator, PageSnapshot  # plan_generator.py:118, :44
from parrot_tools.scraping.models import ScrapingResult, ScrapingSelector     # models.py:622, :611
from parrot_tools.scraping.toolkit import WebScrapingToolkit            # toolkit.py:27
from parrot.stores.models import Document                               # stores/models.py:21
from parrot.bots.scraper.scraper import ScrapingAgent                   # scraper.py:30
from parrot.tools.toolkit import AbstractToolkit                        # tools/toolkit.py:140
```

### Existing Class Signatures

```python
# parrot_tools/scraping/plan.py
def _normalize_url(url: str) -> str:  # line 18
def _compute_fingerprint(normalized_url: str) -> str:  # line 31
def _sanitize_domain(domain: str) -> str:  # line 47

class ScrapingPlan(BaseModel):  # line 59
    name: Optional[str] = None                          # line 67
    version: str = "1.0"                                # line 68
    tags: List[str] = Field(default_factory=list)       # line 69
    url: str                                            # line 72
    domain: str = ""                                    # line 73
    objective: str                                      # line 74
    steps: List[Dict[str, Any]]                         # line 77
    selectors: Optional[List[Dict[str, Any]]] = None    # line 78
    browser_config: Optional[Dict[str, Any]] = None     # line 79
    follow_selector: Optional[str] = None               # line 82
    follow_pattern: Optional[str] = None                # line 83
    max_depth: Optional[int] = None                     # line 84
    created_at: datetime                                # line 87
    updated_at: Optional[datetime] = None               # line 88
    source: str = "llm"                                 # line 89
    fingerprint: str = ""                               # line 90
    def model_post_init(self, __context: Any) -> None:  # line 98

class PlanRegistryEntry(BaseModel):  # line 112
    name: str                                           # line 115
    plan_version: str                                   # line 116
    url: str                                            # line 117
    domain: str                                         # line 118
    fingerprint: str = ""                               # line 119
    path: str                                           # line 120
    created_at: datetime                                # line 121
    last_used_at: Optional[datetime] = None             # line 122
    use_count: int = 0                                  # line 123
    tags: List[str] = Field(default_factory=list)       # line 124

# parrot_tools/scraping/registry.py
class PlanRegistry:  # line 23
    def __init__(self, plans_dir: Optional[Path] = None) -> None:  # line 31
    async def load(self) -> None:                        # line 38
    def lookup(self, url: str) -> Optional[PlanRegistryEntry]:  # line 60
    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]:  # line 102
    def list_all(self) -> List[PlanRegistryEntry]:        # line 116
    async def register(self, plan: ScrapingPlan, relative_path: str) -> None:  # line 124
    async def touch(self, fingerprint: str) -> None:     # line 146
    async def remove(self, name: str) -> bool:           # line 161
    async def _save_index(self) -> None:                 # line 183

# parrot_tools/scraping/plan_generator.py
class PlanGenerator:  # line 118
    def __init__(self, llm_client: Any) -> None:  # line 127
    async def generate(self, url: str, objective: str, snapshot: Optional[PageSnapshot] = None, hints: Optional[Dict[str, Any]] = None) -> ScrapingPlan:  # line 131
    def _build_prompt(self, url: str, objective: str, snapshot=None, hints=None) -> str:  # line 158
    def _parse_response(self, raw: str, url: str, objective: str) -> ScrapingPlan:  # line 191

# parrot_tools/scraping/models.py
@dataclass
class ScrapingSelector:  # line 611
    name: str
    selector: str
    selector_type: Literal['css', 'xpath', 'tag'] = 'css'
    extract_type: Literal['text', 'html', 'attribute'] = 'text'
    attribute: Optional[str] = None
    multiple: bool = False

@dataclass
class ScrapingResult:  # line 622
    url: str
    content: str
    bs_soup: BeautifulSoup
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None

# parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):  # line 27
    async def plan_create(self, url, objective, ...) -> ScrapingPlan:  # line 188
    async def plan_save(self, plan, ...) -> PlanSaveResult:            # line 229
    async def plan_load(self, url_or_name: str) -> Optional[ScrapingPlan]:  # line 281
    async def scrape(self, url, plan=None, objective=None, steps=None, selectors=None, ...) -> ScrapingResult:  # line 370
    async def crawl(self, start_url, depth=1, ...) -> Any:             # line 436

# parrot/bots/scraper/scraper.py
class ScrapingAgent(BaseBot):  # line 30
    def __init__(self, name="WebScrapingAgent", browser=..., driver_type=..., headless=..., ...):  # line 40
    self.scraping_tool: WebScrapingTool  # line 72 — registered via tool_manager
    self.scraping_history: List[Dict[str, Any]]  # line 77
    self.site_knowledge: Dict[str, Dict[str, Any]]  # line 78
    async def analyze_scraping_request(self, request: Dict) -> Dict:  # line 214
    async def execute_intelligent_scraping(self, request: Dict, ...) -> List[ScrapingResult]:  # line 434

# parrot/stores/models.py
class Document(BaseModel):  # line 21
    page_content: str        # line 26
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 27
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ExtractionPlan.to_scraping_plan()` | `ScrapingPlan` | Creates instance with translated selectors | `plan.py:59` |
| `ExtractionPlanRegistry` | `BasePlanRegistry[T]` | Inherits generic base | `registry.py:23` |
| `ExtractionPlanGenerator` | LLM client | `llm_client.complete(prompt)` | `plan_generator.py:154` |
| `RecallProcessor` | LLM client | `llm_client.complete(prompt)` | Same pattern as PlanGenerator |
| `ScrapingAgent.extract_documents()` | `WebScrapingToolkit.scrape()` | Execute translated ScrapingPlan | `toolkit.py:370` |
| `ScrapingAgent._entities_to_documents()` | `Document` | Creates Document instances | `stores/models.py:21` |

### Does NOT Exist (Anti-Hallucination)

- ~~`ScrapingAgent.extract_documents()`~~ -- does not exist yet; this spec creates it
- ~~`ExtractionPlan`~~ -- does not exist; new model to be created in Module 1
- ~~`ExtractionPlanRegistry`~~ -- does not exist; new registry in Module 3
- ~~`ExtractionPlanGenerator`~~ -- does not exist; new generator in Module 4
- ~~`RecallProcessor`~~ -- does not exist; new component in Module 5
- ~~`BasePlanRegistry`~~ -- does not exist; PlanRegistry is not generic today; Module 2 extracts it
- ~~`ScrapingAgent._entities_to_documents()`~~ -- does not exist yet
- ~~`WebScrapingToolkit.extract_structured_data()`~~ -- does not exist
- ~~`WebScrapingToolkit.analyze_page_for_extraction()`~~ -- does not exist
- ~~`Document.entity_type`~~ -- Document has only `page_content` and `metadata`, nothing else
- ~~`PlanRegistry.invalidate()`~~ -- PlanRegistry has `remove()` but no `invalidate()` method
- ~~`ScrapingPlan.extraction_strategy`~~ -- not a field on ScrapingPlan
- ~~`ScrapingResult.entities`~~ -- ScrapingResult has `extracted_data` (Dict), not entities

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **PlanGenerator pattern**: `ExtractionPlanGenerator` must follow the exact same architecture
  as `PlanGenerator` — constructor takes `llm_client`, `generate()` builds prompt + calls
  `complete()` + parses response. Use `_strip_code_fences()` for JSON response cleaning.
- **PlanRegistry pattern**: `ExtractionPlanRegistry` follows `PlanRegistry` — disk-backed
  JSON index, 3-tier lookup, asyncio.Lock for concurrent writes.
- **Async-first**: All I/O operations must be async. Use `aiofiles` for disk operations.
- **Pydantic v2**: All data models use `BaseModel` with `Field`, `computed_field`, etc.
- **Logging**: Use `self.logger = logging.getLogger(__name__)` in all new classes.
- **Google-style docstrings**: All public methods must have complete docstrings.

### ExtractionPlan to ScrapingPlan Translation Rules

The `to_scraping_plan()` method must produce a valid `ScrapingPlan` where:
- `steps` contains a `navigate` action + `wait` for page load
- `selectors` is built from EntitySpec fields:
  - Each `EntityFieldSpec` with a `selector` becomes a `ScrapingSelector` dict
  - `name` maps to `EntityFieldSpec.name` (prefixed with `entity_type` for uniqueness)
  - `selector` maps to `EntityFieldSpec.selector`
  - `extract_type` maps to `EntityFieldSpec.extract_from`
  - `multiple: True` when `EntitySpec.repeating` is True
  - Container selectors are composed: `container_selector + " " + field_selector`
- `objective` is preserved from ExtractionPlan
- `source` is set to `"extraction_plan"`

### Cache Invalidation Policy (Resolved)

- **Failure-based only**: Invalidate after 3 consecutive failures
- No time-based invalidation
- On invalidation: remove from registry, fall back to full LLM reconnaissance

### Content Cleaning for LLM Recon (Resolved)

- Use **HTML** format (not markdown) — preserves CSS classes and DOM nesting
- Strip: `<script>`, `<style>`, `<noscript>`, `<link>`, `<meta>` tags
- Extract `<main>` or first `<article>` if available; fall back to `<body>`
- Truncate to ~8K tokens
- Include CSS class names — critical for selector generation accuracy

### Recall Prompt Content (Resolved)

- Include only HTML sections that matched selectors + 500-token context window
- Do NOT send the full page to the recall step

### Large Page Chunking (Resolved)

- For pages with 50+ entities, use CSS container selectors to split the page
- Batch entities per selector execution
- If no container selectors available, extract as single batch with truncation warning

### Known Risks / Gotchas

- **LLM JSON reliability**: LLM may produce malformed JSON. Must handle: code-fenced
  responses, trailing commas, missing required fields. PlanGenerator already has
  `_parse_response()` with these mitigations — reuse the pattern.
- **Selector fragility**: LLM-generated CSS selectors may not match on first try.
  The recall step helps catch missing data, but selectors may need refinement.
  Future: add selector validation before execution.
- **ScrapingAgent uses WebScrapingTool (deprecated)**: ScrapingAgent currently uses
  `WebScrapingTool` (line 72), not `WebScrapingToolkit`. The new `extract_documents()`
  should use `WebScrapingToolkit` for plan execution. Consider initializing a toolkit
  instance alongside the existing tool, or migrating to toolkit entirely.
- **Provider-specific LLM differences**: The recall and recon prompts return JSON.
  Gemini may struggle with structured output when tools are enabled. Use a separate
  non-tool LLM call (similar to PandasAgent dual-LLM pattern) if needed.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2.0` | Data models (already a dependency) |
| `beautifulsoup4` | `>=4.12` | HTML parsing and content cleaning (already a dependency) |
| `aiofiles` | `>=23.0` | Async file I/O for registry persistence (already a dependency) |

---

## 8. Open Questions

> All brainstorm open questions have been resolved. Remaining implementation questions:

- [ ] **WebScrapingTool vs WebScrapingToolkit in ScrapingAgent**: ScrapingAgent currently
  uses the deprecated `WebScrapingTool`. Should `extract_documents()` use `WebScrapingToolkit`
  instead, or work with the existing tool? — *Owner: Jesus*
- [ ] **LLM provider handling for recall/recon**: Should the recall and recon calls use
  a separate LLM client instance (non-tool mode) to avoid Gemini structured output
  limitations? — *Owner: Jesus*

---

## Worktree Strategy

**Default isolation**: `mixed` — some tasks are parallelizable.

**Parallel groups:**
- **Group A** (no cross-dependencies): Module 1 (models), Module 4 (plan generator), Module 5 (recall processor)
- **Group B** (depends on Module 1): Module 2 (base registry), Module 3 (extraction registry), Module 7 (pre-built plans)
- **Group C** (depends on all above): Module 6 (ScrapingAgent orchestration)

**Recommended execution order:**
1. Module 1 first (all others depend on data models)
2. Modules 2, 3, 4, 5, 7 can run in parallel after Module 1
3. Module 6 last (integrates everything)

**Cross-feature dependencies**: None. ScrapingAgent is extended (new methods only), no
modifications to existing methods.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-13 | Jesus + Claude | Initial draft from brainstorm |
