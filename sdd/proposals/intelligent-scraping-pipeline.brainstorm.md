# Brainstorm: Intelligent Extraction Pipeline for ScrapingAgent

**Date**: 2026-04-13
**Author**: Jesus (architect) + Claude (design partner)
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

The current `WebScrapingLoader` extracts web page content as flat text/markdown,
producing Documents via tag-based fragmentation or full-page markdown. This fails
for **structured commercial pages** (e.g., att.com/prepaid/, Amazon product listings)
because:

1. **Context collapse**: "$30/mo" loses its association with "AT&T Prepaid 5 GB plan"
   when tags are stripped from the full body.
2. **Noise pollution**: Navigation menus, footers, legal text, banners contaminate
   RAG chunks.
3. **No semantic structure**: A RAG chatbot cannot answer "Which plan has the most
   data under $50?" because plans aren't discrete entities with comparable attributes.
4. **Per-site developer effort**: Writing CSS selectors per client site doesn't scale.

**Who is affected**: Developers building RAG pipelines over structured commercial
content; end-users querying product/plan data through chatbots.

**Why now**: ScrapingAgent already has LLM access, plan generation (`PlanGenerator`),
and plan persistence (`PlanRegistry`). The infrastructure for "intelligent plan
design" exists — we need to extend it to handle extraction-specific planning.

## Constraints & Requirements

- LLM is ONLY used for plan generation (reconnaissance) and post-extraction recall — NOT for extraction itself
- Extraction is mechanical: WebScrapingToolkit executes JSON plans via Selenium
- The LLM recon artifact is a JSON plan compatible with or translatable to `ScrapingPlan`
- Pre-built plans are hand-authored JSON files stored in a well-known directory
- LLM-generated plans can be saved and reused (cache/registry)
- Must work with existing `PlanRegistry` three-tier lookup (exact → path-prefix → domain)
- Async-first, Pydantic models, Google-style docstrings
- Output is `List[Document]` (from `parrot.stores.models`) ready for vector store ingestion
- Post-extraction LLM "recall" step generates rag_text and catches missed data
- Monorepo: changes may span `ai-parrot` (ScrapingAgent) and `ai-parrot-tools` (toolkit/models)

---

## Options Explored

### Option A: Extend Existing PlanGenerator with Extraction Awareness

Add extraction capabilities directly to the existing `PlanGenerator` class. Extend
`ScrapingPlan` with optional extraction metadata fields (entity definitions, field
specs, selector mappings). The same `PlanRegistry` stores both navigation-only and
extraction-enriched plans.

The LLM recon phase uses the existing `PlanGenerator.generate()` flow but with an
enriched prompt that asks the LLM to include extraction selectors and entity
definitions alongside navigation steps. The result is a single `ScrapingPlan` with
extra fields.

Post-extraction, a new `RecallProcessor` on ScrapingAgent calls the LLM once to
generate rag_text for all extracted entities and flag missed data.

Pros:
- Minimal new classes — reuses PlanGenerator, PlanRegistry, ScrapingPlan
- Single plan model simplifies serialization and caching
- Less code to maintain; lower cognitive overhead

Cons:
- Muddies the ScrapingPlan model with optional extraction fields (nullable sprawl)
- Navigation-only plans and extraction plans share a model but serve different purposes
- Harder to validate extraction-specific constraints (e.g., "must have at least one entity")
- PlanGenerator prompt becomes overloaded with dual responsibilities
- ExtractionPlan rationale/annotations don't fit cleanly into ScrapingPlan's flat structure

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Extended ScrapingPlan model | Already in use |
| `beautifulsoup4` | Post-scrape entity splitting | Already in use via ScrapingResult |

Existing Code to Reuse:
- `parrot_tools/scraping/plan_generator.py` — extend `generate()` and `_build_prompt()`
- `parrot_tools/scraping/registry.py` — reuse PlanRegistry as-is
- `parrot_tools/scraping/plan.py` — extend ScrapingPlan with optional extraction fields
- `parrot/bots/scraper/scraper.py` — add `extract_documents()` to ScrapingAgent

---

### Option B: Dual-Model Pipeline (ExtractionPlan → ScrapingPlan Translation)

Introduce a new `ExtractionPlan` model that is **richer than ScrapingPlan** — it
includes entity definitions, field specifications, extraction rationale, and
strategy hints. The LLM recon phase produces an `ExtractionPlan`. A translator
method (`ExtractionPlan.to_scraping_plan()`) converts it into the `ScrapingPlan`
format that WebScrapingToolkit already understands.

Key components:
- **ExtractionPlan** (new Pydantic model): Rich schema with entities, fields,
  rationale, ignore sections, page category. Source of truth for "what to extract."
- **ExtractionPlanGenerator** (new class): Specialized LLM prompt for
  reconnaissance. Input: page content + objective. Output: ExtractionPlan.
- **ExtractionPlanRegistry** (new or generic): Stores ExtractionPlans with the
  same three-tier lookup. Either a separate registry or a generic
  `BasePlanRegistry[T]` extracted from PlanRegistry.
- **RecallProcessor** (new): Post-extraction LLM call. Receives raw extracted
  data + full page content. Generates rag_text, fills gaps, flags missed entities.
- **ScrapingAgent.extract_documents()**: Orchestrates the full pipeline.

The two-phase flow:
1. **Phase 1 — Navigate & Download**: Use existing ScrapingPlan (or a navigation
   sub-plan from ExtractionPlan) to load the page → ScrapingResult with HTML + BS4.
2. **Phase 2 — Reconnaissance**: LLM analyzes the downloaded page content against
   the objective → produces ExtractionPlan with entity/field definitions and CSS
   selectors. ExtractionPlan is translated to ScrapingPlan selectors for mechanical
   extraction.
3. **Phase 3 — Extract**: WebScrapingToolkit executes the translated ScrapingPlan.
   Selectors pull structured data into ScrapingResult.extracted_data.
4. **Phase 4 — Recall**: Single LLM call post-processes extracted entities.
   Generates rag_text, catches missed fields, validates data quality.
5. **Phase 5 — Assemble**: ScrapingAgent converts ExtractedEntities → Documents.

Pros:
- Clean separation: ExtractionPlan captures intent/rationale; ScrapingPlan captures execution
- ExtractionPlan can be validated independently (e.g., "must define entities")
- Pre-built plans benefit from the richer ExtractionPlan format (developer annotations, rationale)
- Translation layer isolates ScrapingPlan schema from extraction concerns
- ExtractionPlanRegistry can track extraction-specific metrics (entity count, field coverage)
- Future-proof: ExtractionPlan can evolve without touching ScrapingPlan

Cons:
- More classes and files to create and maintain
- Translation step adds complexity (must keep ExtractionPlan and ScrapingPlan schemas in sync)
- Two registries (or a generic base) adds infrastructure
- Higher initial effort

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | ExtractionPlan, EntitySpec, ExtractedEntity models | Already in use |
| `beautifulsoup4` | Entity container splitting in extraction phase | Already in use |

Existing Code to Reuse:
- `parrot_tools/scraping/plan_generator.py` — pattern for ExtractionPlanGenerator
- `parrot_tools/scraping/registry.py` — pattern for ExtractionPlanRegistry (or extract generic base)
- `parrot_tools/scraping/plan.py` — ScrapingPlan as translation target
- `parrot_tools/scraping/models.py` — ScrapingSelector, ScrapingResult
- `parrot/bots/scraper/scraper.py` — ScrapingAgent orchestration
- `parrot/stores/models.py` — Document model for output

---

### Option C: ExtractionPlan as ScrapingPlan Wrapper (Composition)

Instead of translation, `ExtractionPlan` **wraps** a `ScrapingPlan` via composition.
The ExtractionPlan contains:
- A `navigation_plan: Optional[ScrapingPlan]` for how to reach the page
- An `extraction_plan: ScrapingPlan` whose `selectors` define what to extract
- Rich metadata (entities, rationale, page category) as annotations

The LLM recon phase produces the ExtractionPlan which internally constructs the
ScrapingPlan(s). No translation step — the ScrapingPlan is embedded directly.

The flow is similar to Option B but the ExtractionPlan "owns" its ScrapingPlan
rather than translating to one.

Pros:
- No translation layer — ExtractionPlan directly contains the executable plan
- Single source of truth: modifying the ExtractionPlan's selectors immediately
  affects the embedded ScrapingPlan
- Cleaner than Option A (extraction metadata is separate from ScrapingPlan)
- Less code than Option B (no translator method)

Cons:
- Tighter coupling: ExtractionPlan must understand ScrapingPlan internals
- LLM must generate valid ScrapingPlan JSON embedded within ExtractionPlan JSON
  (more complex prompt, higher chance of malformed output)
- Pre-built plans require writing both the wrapper and the embedded ScrapingPlan
- Serialization is nested (ExtractionPlan → ScrapingPlan → steps/selectors)
- Harder for the LLM to produce correctly in one shot (nested structures)

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Composed ExtractionPlan model | Already in use |
| `beautifulsoup4` | Entity splitting | Already in use |

Existing Code to Reuse:
- `parrot_tools/scraping/plan.py` — ScrapingPlan embedded as field
- `parrot_tools/scraping/plan_generator.py` — prompt pattern
- `parrot_tools/scraping/registry.py` — registry pattern
- `parrot/bots/scraper/scraper.py` — ScrapingAgent

---

### Option D: Two-Pass Scraping (Navigate-then-Analyze)

Instead of a rich ExtractionPlan model, use a simpler two-pass approach:
1. **Pass 1 — Blind scrape**: Navigate to the URL and download the full page
   body using a minimal ScrapingPlan (just `navigate` + `wait`). Return the HTML.
2. **Pass 2 — LLM analysis**: Send the HTML to the LLM with the objective. The
   LLM returns a standard `ScrapingPlan` with precise selectors for the entities.
   This plan is saved to the existing PlanRegistry.
3. **Pass 3 — Targeted scrape**: Re-execute the page (or reuse the BS4 object)
   with the LLM-generated selectors. Extract structured data.
4. **Pass 4 — Recall**: LLM post-processing for rag_text and gap-filling.

No new model types beyond a lightweight `ExtractionMetadata` dict attached to
the ScrapingPlan via its existing `Dict` fields. Entity definitions live as
comments/annotations in the plan's step descriptions.

Pros:
- Minimal new abstractions — relies on existing ScrapingPlan entirely
- LLM prompt is simpler (just generate a ScrapingPlan, which it already knows)
- No translation layer, no new registry
- Fastest path to a working prototype

Cons:
- No structured entity definitions — extraction knowledge is implicit in selectors
- Pre-built plans can't express entity semantics (which selector maps to which entity field)
- Recall step has less context about what was expected vs. what was extracted
- Entity-to-Document mapping is ad-hoc (no formal EntitySpec to guide it)
- Plan reuse is weaker: saved plans lack the "why" behind each selector
- Harder to validate extraction quality without entity specs

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Minimal ExtractionMetadata | Already in use |
| `beautifulsoup4` | Entity splitting from selectors | Already in use |

Existing Code to Reuse:
- `parrot_tools/scraping/plan_generator.py` — use as-is for pass 2
- `parrot_tools/scraping/registry.py` — use as-is
- `parrot_tools/scraping/plan.py` — ScrapingPlan as-is
- `parrot/bots/scraper/scraper.py` — ScrapingAgent

---

## Recommendation

**Option B** is recommended because:

1. **Clean separation of concerns**: The distinction between "what to extract and why"
   (ExtractionPlan) and "how to mechanically execute" (ScrapingPlan) is fundamental to
   the feature's value. Collapsing them (Options A/D) loses the rationale and entity
   semantics that make plans reusable and debuggable.

2. **Pre-built plan authoring**: Developers writing JSON plans for known sites benefit
   enormously from the richer ExtractionPlan format. An ExtractionPlan with entity
   definitions, field descriptions, and rationale is self-documenting. A raw ScrapingPlan
   with selectors is opaque.

3. **LLM prompt quality**: Having the LLM produce an ExtractionPlan (entities + fields +
   selectors) and then translating to ScrapingPlan is more reliable than asking the LLM
   to produce a nested structure (Option C) or to embed entity semantics in plan
   step descriptions (Option D).

4. **Recall quality**: The post-extraction recall step works best when it has the
   ExtractionPlan's entity definitions as context — it knows what was expected, what
   was found, and what might be missing. Options A/D lack this structured context.

**Tradeoff accepted**: Higher initial effort and more files. This is justified because
the feature is foundational — extraction intelligence will be reused across many sites
and extended with visual extraction, delta detection, and cross-page merging in the
future.

---

## Feature Description

### User-Facing Behavior

**For developers (handler/API level):**
```python
agent = ScrapingAgent(...)
docs = await agent.extract_documents(
    url="https://www.att.com/prepaid/",
    objective="Extract all prepaid plans with prices, data, and features",
    # Optional: pre-built plan for known site
    extraction_plan=load_plan("att_prepaid"),
)
# docs: List[Document], each representing one plan entity
await knowledge_base.ingest(docs)
```

**For end-users (RAG chatbot):**
- Query: "Which AT&T prepaid plan has the most data under $50?"
- Response: Accurate answer referencing specific plan entities with prices and features,
  because each plan is a separate Document with structured metadata.

### Internal Behavior

**Pipeline flow (5 phases):**

1. **Plan Resolution**: Check for explicit ExtractionPlan → check ExtractionPlanRegistry
   (cached) → if none found, proceed to reconnaissance.

2. **Navigate & Download**: Use existing ScrapingPlan/WebScrapingToolkit to load the
   target page. If no navigation plan exists, use a simple `[{action: "navigate", url: ...},
   {action: "wait", ...}]` plan. Result: `ScrapingResult` with HTML + BeautifulSoup.

3. **LLM Reconnaissance** (only if no ExtractionPlan available): Send page content
   (cleaned HTML or markdown excerpt) + objective to `ExtractionPlanGenerator`. LLM
   analyzes the page structure and produces an `ExtractionPlan` with entity definitions,
   field specs, and CSS selectors. The ExtractionPlan is translated to a `ScrapingPlan`
   via `extraction_plan.to_scraping_plan()`.

4. **Mechanical Extraction**: Execute the translated ScrapingPlan via
   WebScrapingToolkit. Selectors extract structured data into
   `ScrapingResult.extracted_data`. ScrapingAgent splits extracted data into
   per-entity dicts based on ExtractionPlan's entity definitions.

5. **LLM Recall**: Single LLM call receives: (a) extracted entities, (b) original
   page content excerpt, (c) ExtractionPlan entity definitions. LLM generates
   `rag_text` for each entity, flags missed entities, fills data gaps. This is the
   "quality assurance" step.

6. **Document Assembly**: ScrapingAgent converts recalled entities into
   `List[Document]` where each Document has `page_content=rag_text` and
   `metadata` containing all structured fields + provenance.

**Plan caching**: On successful extraction, the ExtractionPlan is saved to
ExtractionPlanRegistry. Subsequent requests for the same URL/domain skip
reconnaissance (Phase 3).

### Edge Cases & Error Handling

- **Empty extraction**: If selectors return no data, invalidate cached plan and
  fall back to full reconnaissance (re-run Phase 3).
- **Partial extraction**: If some entity fields are null, the recall step attempts
  to fill them from page content. Remaining nulls are preserved in metadata.
- **Page structure change**: Cached plan produces 0 entities → cache invalidation →
  automatic re-reconnaissance.
- **LLM recon failure**: If the LLM returns malformed JSON, retry once with a
  simplified prompt. If still fails, return error with raw HTML as fallback Document.
- **Large pages (50K+ tokens)**: Strip `<script>`, `<style>`, `<noscript>`, extract
  `<main>` or `<article>`, truncate to ~8K tokens for LLM. Use HTML (not markdown)
  for recon — LLM needs DOM structure to generate accurate selectors.
- **Pre-built plan mismatch**: If a pre-built plan's selectors fail on the actual
  page, fall back to LLM reconnaissance and log a warning.
- **Multi-page crawl**: Apply ExtractionPlan to each crawled page. If a page yields
  0 entities with the shared plan, run per-page reconnaissance.

---

## Capabilities

### New Capabilities
- `extraction-plan-model`: Pydantic models for ExtractionPlan, EntitySpec, EntityFieldSpec, ExtractedEntity, ExtractionResult
- `extraction-plan-generator`: LLM-driven reconnaissance that analyzes page content and produces ExtractionPlan
- `extraction-plan-registry`: Disk-backed registry with three-tier lookup for ExtractionPlans
- `extraction-plan-translator`: Converts ExtractionPlan to ScrapingPlan for mechanical execution
- `recall-processor`: Post-extraction LLM call for rag_text generation and gap-filling
- `extract-documents`: High-level ScrapingAgent method orchestrating the full pipeline
- `prebuilt-extraction-plans`: Directory of hand-authored ExtractionPlan JSON files

### Modified Capabilities
- `scraping-agent`: Add `extract_documents()` method and entity-to-Document conversion
- `web-scraping-toolkit`: May need new tool methods for extraction-specific operations (TBD during spec)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/scraper/scraper.py` | extends | Add `extract_documents()`, `_entities_to_documents()`, recall integration |
| `parrot_tools/scraping/plan.py` | depends on | ExtractionPlan references ScrapingPlan for translation |
| `parrot_tools/scraping/registry.py` | extends or pattern-reuse | Extract `BasePlanRegistry[T]` or create parallel ExtractionPlanRegistry |
| `parrot_tools/scraping/plan_generator.py` | pattern-reuse | ExtractionPlanGenerator follows same architecture |
| `parrot_tools/scraping/models.py` | depends on | Uses ScrapingSelector, ScrapingResult |
| `parrot/stores/models.py` | depends on | Uses Document model for output |
| `parrot_tools/scraping/toolkit.py` | may extend | Potential new tool methods for extraction pipeline |

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (Round 2 answer)
# ScrapingResult dataclass — confirmed at parrot_tools/scraping/models.py:622
@dataclass
class ScrapingResult:
    """Stores results from a single page scrape"""
    url: str
    content: str  # Raw HTML content
    bs_soup: BeautifulSoup  # Parsed BeautifulSoup object
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None
```

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot_tools/scraping/plan.py:59
class ScrapingPlan(BaseModel):
    name: Optional[str] = None                  # line 67
    version: str = "1.0"                        # line 68
    tags: List[str] = Field(default_factory=list)  # line 69
    url: str                                     # line 72
    domain: str = ""                             # line 73
    objective: str                               # line 74
    steps: List[Dict[str, Any]]                  # line 77
    selectors: Optional[List[Dict[str, Any]]] = None  # line 78
    browser_config: Optional[Dict[str, Any]] = None   # line 79
    follow_selector: Optional[str] = None        # line 82
    follow_pattern: Optional[str] = None         # line 83
    max_depth: Optional[int] = None              # line 84
    created_at: datetime = ...                   # line 87
    updated_at: Optional[datetime] = None        # line 88
    source: str = "llm"                          # line 89
    fingerprint: str = ""                        # line 90

# From parrot_tools/scraping/plan.py:112
class PlanRegistryEntry(BaseModel):
    name: str                                    # line 115
    plan_version: str                            # line 116
    url: str                                     # line 117
    domain: str                                  # line 118
    fingerprint: str = ""                        # line 119
    path: str                                    # line 120
    created_at: datetime                         # line 121
    last_used_at: Optional[datetime] = None      # line 122
    use_count: int = 0                           # line 123
    tags: List[str] = Field(default_factory=list)  # line 124

# From parrot_tools/scraping/registry.py:23
class PlanRegistry:
    def __init__(self, plans_dir: Optional[Path] = None) -> None:  # line 31
    async def load(self) -> None:                # line 38
    def lookup(self, url: str) -> Optional[PlanRegistryEntry]:  # line 60
    def get_by_name(self, name: str) -> Optional[PlanRegistryEntry]:  # line 102
    def list_all(self) -> List[PlanRegistryEntry]:  # line 116
    async def register(self, plan: ScrapingPlan, relative_path: str) -> None:  # line 124
    async def touch(self, fingerprint: str) -> None:  # line 146
    async def remove(self, name: str) -> bool:   # line 161

# From parrot_tools/scraping/plan_generator.py:118
class PlanGenerator:
    def __init__(self, llm_client: Any) -> None:  # line 127
    async def generate(self, url, objective, snapshot=None, hints=None) -> ScrapingPlan:  # line 131
    def _build_prompt(self, url, objective, snapshot=None, hints=None) -> str:  # line 158
    def _parse_response(self, raw, url, objective) -> ScrapingPlan:  # line 191

# From parrot_tools/scraping/models.py:611
@dataclass
class ScrapingSelector:
    name: str
    selector: str
    selector_type: Literal['css', 'xpath', 'tag'] = 'css'
    extract_type: Literal['text', 'html', 'attribute'] = 'text'
    attribute: Optional[str] = None
    multiple: bool = False

# From parrot/bots/scraper/scraper.py:30
class ScrapingAgent(BaseBot):
    def __init__(self, name="WebScrapingAgent", browser=..., ...):  # line 40
    async def analyze_scraping_request(self, request: Dict) -> Dict:  # line 214
    async def execute_intelligent_scraping(self, request: Dict, ...) -> List[ScrapingResult]:  # line 434

# From parrot/stores/models.py:21
class Document(BaseModel):
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

# From parrot_tools/scraping/toolkit.py:27
class WebScrapingToolkit(AbstractToolkit):
    async def plan_create(self, url, objective, ...) -> ScrapingPlan:  # line 188
    async def plan_save(self, plan, ...) -> PlanSaveResult:  # line 229
    async def plan_load(self, url_or_name: str) -> Optional[ScrapingPlan]:  # line 281
    async def scrape(self, url, plan=None, objective=None, ...) -> ScrapingResult:  # line 370
    async def crawl(self, start_url, depth=1, ...) -> Any:  # line 436
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot_tools.scraping.plan import ScrapingPlan, PlanRegistryEntry  # plan.py
from parrot_tools.scraping.registry import PlanRegistry                 # registry.py
from parrot_tools.scraping.plan_generator import PlanGenerator, PageSnapshot  # plan_generator.py
from parrot_tools.scraping.models import ScrapingResult, ScrapingSelector     # models.py
from parrot_tools.scraping.toolkit import WebScrapingToolkit            # toolkit.py
from parrot.stores.models import Document                               # stores/models.py
from parrot.bots.scraper.scraper import ScrapingAgent                   # scraper.py
from parrot.tools.toolkit import AbstractToolkit                        # tools/toolkit.py
```

#### Key Attributes & Constants
- `ScrapingPlan.steps` → `List[Dict[str, Any]]` — action dicts like `{"action": "navigate", "url": "..."}`
- `ScrapingPlan.selectors` → `Optional[List[Dict]]` — extraction selectors like `{"name": "title", "selector": "h1", "extract_type": "text"}`
- `ScrapingResult.extracted_data` → `Dict[str, Any]` — keyed by selector name
- `ScrapingResult.bs_soup` → `BeautifulSoup` — parsed HTML for post-processing
- `PlanRegistry._entries` → `dict[str, PlanRegistryEntry]` — keyed by fingerprint
- `PlanGenerator._client` → LLM client with `complete(prompt)` method

### Does NOT Exist (Anti-Hallucination)
- ~~`ScrapingAgent.extract_documents()`~~ — does not exist yet; this is what we're building
- ~~`ExtractionPlan`~~ — does not exist; new model to be created
- ~~`ExtractionPlanRegistry`~~ — does not exist; new registry to be created
- ~~`ExtractionPlanGenerator`~~ — does not exist; new generator to be created
- ~~`RecallProcessor`~~ — does not exist; new component to be created
- ~~`BasePlanRegistry`~~ — does not exist; PlanRegistry is not generic today
- ~~`ScrapingAgent._entities_to_documents()`~~ — does not exist yet
- ~~`WebScrapingToolkit.extract_structured_data()`~~ — does not exist
- ~~`WebScrapingToolkit.analyze_page_for_extraction()`~~ — does not exist
- ~~`Document.entity_type`~~ — Document has only `page_content` and `metadata`

---

## Parallelism Assessment

**Internal parallelism:** Yes — this feature decomposes into independent units:
- **Models** (ExtractionPlan, EntitySpec, etc.) — no dependencies on other new code
- **ExtractionPlanGenerator** — depends only on models
- **ExtractionPlanRegistry** — depends only on models; independent from generator
- **RecallProcessor** — depends only on models; independent from generator/registry
- **Pre-built plans** — depends only on models
- **ScrapingAgent.extract_documents()** — depends on ALL of the above (must be last)

Tasks 1-4 (models, generator, registry, recall) can run in parallel worktrees.
Task 5 (orchestration in ScrapingAgent) must wait for all prior tasks.

**Cross-feature independence:** No known conflicts with in-flight specs. ScrapingAgent
is touched but only by adding new methods (no modifications to existing methods).

**Recommended isolation:** `mixed` — models/generator/registry/recall can use
individual worktrees; orchestration task must be sequential after all dependencies.

**Rationale:** The new components are self-contained modules with well-defined interfaces.
Only the final orchestration task (ScrapingAgent.extract_documents) needs all pieces
assembled. This enables 3-4 parallel development streams.

---

## Open Questions

- [ ] **HTML vs markdown for LLM recon prompt**: HTML preserves CSS classes and DOM nesting (better for selector generation), but is noisier. Leaning toward cleaned HTML (`<main>` content, stripped scripts/styles). — *Owner: Jesus*
- [ ] **ExtractionPlanRegistry: separate class or generic base?** Options: (a) separate ExtractionPlanRegistry, (b) extract `BasePlanRegistry[T]` from PlanRegistry, (c) shared PlanRegistry with type discriminator. Proposal recommends (b). — *Owner: Jesus*
- [ ] **Token budget for large pages**: For pages with 50+ entities, should extraction be chunked? Proposed: use CSS container selectors to split page, batch entities per selector execution. — *Owner: Jesus*
- [ ] **Plan versioning/invalidation policy**: Failure-based (N failures → invalidate) as primary, time-based (30 days) as secondary. Exact thresholds TBD. — *Owner: Jesus*
- [ ] **Recall prompt design**: How much page content to include in the recall step? Full page is expensive. Proposed: include only the HTML sections that matched selectors + a 500-token context window around each. — *Owner: Jesus*
