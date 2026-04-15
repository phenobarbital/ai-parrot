# FEAT: Intelligent Extraction Pipeline for ScrapingAgent

## Brainstorm Document — FEAT-XXX (Pending Assignment)

**Author:** Jesus (architect) + Claude (design partner)
**Date:** 2026-04-13
**Status:** Brainstorm — Ready for SDD spec
**Packages affected:** `ai-parrot-tools` (scraping), `ai-parrot` (ScrapingAgent)

---

## 1. Problem Statement

The current `WebScrapingLoader` extracts web page content as flat text/markdown
and produces Documents via tag-based fragmentation, CSS selectors, or full-page
markdown. This approach fails for **structured commercial pages** (e.g.,
`att.com/prepaid/`, Amazon product listings, telecom plan catalogs) because:

1. **Context collapse**: Stripping tags from the full body produces text where
   "$30/mo" loses its association with "AT&T Prepaid 5 GB plan".
2. **Noise pollution**: Navigation menus, footers, legal disclaimers, banners,
   and cookie consent text contaminate RAG chunks.
3. **No semantic structure**: A RAG chatbot cannot answer "Which plan has the
   most data for under $50?" because plans aren't represented as discrete
   entities with comparable attributes.
4. **Per-site developer effort**: Writing CSS selectors for each client's
   website doesn't scale — every new URL requires manual analysis.

### What we need

An **LLM-driven extraction pipeline** where the AI analyzes the page, decides
what entities exist, builds an extraction schema, and produces structured
Documents — all triggered by a natural-language objective from the user or
the loader handler.

---

## 2. Design Principles

- **The ScrapingAgent is the orchestrator.** It already has LLM access,
  tool-calling capability, plan generation, and site-specific templates.
  The new extraction intelligence lives here, NOT inside a Loader.
- **Loaders stay dumb.** `WebScrapingLoader` remains useful for simple
  scraping (docs sites, blogs, static pages). For intelligent extraction,
  the handler invokes the ScrapingAgent directly.
- **ExtractionPlan ≠ ScrapingPlan.** A `ScrapingPlan` describes *how to
  navigate* (click, scroll, fill). An `ExtractionPlan` describes *what data
  to extract* (entities, fields, selectors, context hints). They are
  complementary and composable.
- **Plans are cacheable and reusable.** Successful ExtractionPlans are
  persisted to disk (JSON) via a registry analogous to `PlanRegistry`.
  Subsequent runs for the same URL/domain skip the reconnaissance phase.
- **Pre-built plans are first-class citizens.** Developers can provide
  ExtractionPlans for known sites (Amazon, AT&T, BestBuy) to bypass LLM
  reconnaissance entirely.
- **Output is `List[Document]`.** The ScrapingAgent's new `extract_documents()`
  method returns Parrot Documents ready for vectorization. No intermediate
  Loader needed.

---

## 3. Architecture Overview

```
User / Handler
    │
    │  "Extract prepaid plans from att.com/prepaid/"
    ▼
┌─────────────────────────────────────────────────────────┐
│                    ScrapingAgent                         │
│               (BasicAgent + LLM + Tools)                │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │          Plan Resolution Chain                   │    │
│  │                                                  │    │
│  │  1. Explicit ExtractionPlan provided?  ──► USE   │    │
│  │  2. Cached plan in ExtractionRegistry? ──► USE   │    │
│  │  3. None available? ──► Run LLM Recon phase      │    │
│  └──────────────────────┬──────────────────────────┘    │
│                         │                               │
│                         ▼                               │
│  ┌──────────────────────────────────────────────┐       │
│  │  Phase 1: RECONNAISSANCE (tool call)          │       │
│  │  ─────────────────────────────────────────    │       │
│  │  Input:  page content (HTML/markdown)         │       │
│  │        + user objective                       │       │
│  │  Output: ExtractionPlan                       │       │
│  │        {entities, fields, selectors, hints}   │       │
│  └──────────────────────┬───────────────────────┘       │
│                         │                               │
│                         ▼                               │
│  ┌──────────────────────────────────────────────┐       │
│  │  Phase 2: EXTRACTION (tool call)              │       │
│  │  ─────────────────────────────────────────    │       │
│  │  Input:  page content + ExtractionPlan        │       │
│  │  Output: List[ExtractedEntity]                │       │
│  │        structured data per entity             │       │
│  └──────────────────────┬───────────────────────┘       │
│                         │                               │
│                         ▼                               │
│  ┌──────────────────────────────────────────────┐       │
│  │  Phase 3: DOCUMENT ASSEMBLY                   │       │
│  │  ─────────────────────────────────────────    │       │
│  │  Input:  List[ExtractedEntity] + metadata     │       │
│  │  Output: List[Document]                       │       │
│  │        (ready for vector store)               │       │
│  └──────────────────────────────────────────────┘       │
│                                                         │
│  ┌──────────────────────────────────────────────┐       │
│  │  Phase 4: PLAN CACHING (async, fire-and-forget)│      │
│  │  ─────────────────────────────────────────    │       │
│  │  Save ExtractionPlan to ExtractionRegistry    │       │
│  │  if extraction was successful                 │       │
│  └──────────────────────────────────────────────┘       │
│                                                         │
└─────────────────────────────────────────────────────────┘
         │
         ▼
   List[Document]  ──►  VectorStore / KnowledgeBase
```

---

## 4. Execution Paths (A/B/C/D)

### Path A — Full Autonomy (no plan)
```
User gives: URL + objective
Agent does:  scrape page → LLM recon → ExtractionPlan → LLM extract → Documents
Use case:   First-time scraping of unknown site
```

### Path B — Pre-built Plan (developer-provided)
```
User gives: URL + objective + ExtractionPlan
Agent does:  scrape page → skip recon → LLM extract with schema → Documents
Use case:   Known sites (Amazon, BestBuy, AT&T) with curated plans
```

### Path C — Hybrid (partial plan)
```
User gives: URL + objective + partial ExtractionPlan (e.g., only ScrapingPlan for navigation)
Agent does:  scrape with navigation plan → LLM recon for extraction schema → extract → Documents
Use case:   Developer knows HOW to navigate but not WHAT to extract
```

### Path D — Cached Plan (learned)
```
User gives: URL + objective
Agent does:  check ExtractionRegistry → cache hit → scrape → extract with cached plan → Documents
             If extraction succeeds → touch cache (update last_used)
             If extraction fails → invalidate cache → fallback to Path A
Use case:   Repeated scraping of same site/URL pattern
```

---

## 5. Data Models

### 5.1 ExtractionPlan (NEW — Pydantic)

```python
class EntityFieldSpec(BaseModel):
    """Specification for a single field within an entity."""
    name: str                           # e.g. "price_monthly"
    description: str                    # Hint for the LLM extractor
    field_type: str = "text"            # text | number | currency | url | boolean | list
    required: bool = True
    selector: Optional[str] = None      # CSS selector hint (optional)
    selector_type: str = "css"          # css | xpath
    extract_from: str = "text"          # text | attribute | html
    attribute: Optional[str] = None     # For extract_from="attribute"

class EntitySpec(BaseModel):
    """Specification for one type of entity to extract."""
    entity_type: str                    # e.g. "prepaid_plan"
    description: str                    # What this entity represents
    fields: List[EntityFieldSpec]
    repeating: bool = True              # Multiple instances on page?
    container_selector: Optional[str] = None  # CSS selector for the repeating container
    container_selector_type: str = "css"

class ExtractionPlan(BaseModel):
    """Schema describing WHAT to extract from a page (not HOW to navigate)."""
    url: str                            # Target URL (or URL pattern)
    domain: str = ""                    # Auto-derived from url
    objective: str                      # Original user objective
    entities: List[EntitySpec]
    ignore_sections: List[str] = []     # Sections to skip (nav, footer, etc.)
    page_category: str = ""             # e.g. "telecom_prepaid_plans"
    extraction_strategy: str = "llm"    # llm | css | hybrid
    #   llm:    Full LLM extraction pass (most flexible, higher cost)
    #   css:    Pure BeautifulSoup with selectors (fastest, needs good selectors)
    #   hybrid: CSS extraction with LLM fallback for missing fields
    confidence: float = 0.0             # Recon confidence (0-1)
    source: str = "llm"                 # llm | developer | cache
    version: int = 1
    fingerprint: str = ""               # URL-based fingerprint for cache lookup

    # Metadata for cache management
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    success_count: int = 0
    failure_count: int = 0
```

### 5.2 ExtractedEntity (NEW — Pydantic)

```python
class ExtractedEntity(BaseModel):
    """A single structured entity extracted from a page."""
    entity_type: str                    # Matches EntitySpec.entity_type
    fields: Dict[str, Any]             # Extracted field values
    source_url: str
    confidence: float = 0.0             # Extraction confidence
    raw_text: Optional[str] = None      # Original text block (for debugging)
    rag_text: str = ""                  # Natural language text for vectorization
    #
    # Example rag_text:
    #   "AT&T Prepaid 5 GB plan costs $30/month. Includes 5GB of data,
    #    unlimited talk and text in the US, SD streaming. No hotspot."
```

### 5.3 ExtractionResult (NEW — Pydantic)

```python
class ExtractionResult(BaseModel):
    """Complete result from an extraction run."""
    url: str
    objective: str
    entities: List[ExtractedEntity]
    plan_used: ExtractionPlan
    extraction_strategy: str            # Which strategy was actually used
    total_entities: int = 0
    success: bool = True
    error_message: Optional[str] = None
    elapsed_seconds: float = 0.0
    llm_calls: int = 0                  # How many LLM calls were needed
```

---

## 6. New Components

### 6.1 ExtractionPlanRegistry

Analogous to `PlanRegistry` for `ScrapingPlan`, but for `ExtractionPlan`.

```
extraction_plans/
├── registry.json                          # URL fingerprint → plan file mapping
├── att.com/
│   ├── prepaid_plans_v1_abc123.json
│   └── phone_deals_v1_def456.json
├── amazon.com/
│   └── product_listing_v1_ghi789.json
└── bestbuy.com/
    └── product_detail_v1_jkl012.json
```

**Lookup tiers** (same as PlanRegistry):
1. Exact URL fingerprint match
2. Path-prefix match (e.g., `att.com/prepaid/*`)
3. Domain match (e.g., any `att.com` page)

**Cache lifecycle:**
- On successful extraction: `success_count += 1`, `last_used_at = now()`
- On failed extraction: `failure_count += 1`
- If `failure_count > threshold`: invalidate (delete or mark stale)
- Invalidated plans trigger Path A (full recon) on next run

**Question:** Should ExtractionPlanRegistry be a separate class or reuse
PlanRegistry with a type discriminator? Given that the data models are
different (ExtractionPlan vs ScrapingPlan), a separate registry is cleaner
but shares 90% of the code. Options:
- (a) Separate `ExtractionPlanRegistry` class (code duplication but clear)
- (b) Generic `PlanRegistry[T]` parameterized by plan type
- (c) Shared `PlanRegistry` with `plan_type` discriminator field

**Recommendation:** Option (b) — extract a generic `BasePlanRegistry[T]` and
have both `ScrapingPlanRegistry` and `ExtractionPlanRegistry` inherit from it.
This also opens the door for other plan types in the future.

### 6.2 New Tools on WebScrapingToolkit

Two new public async methods (auto-discovered as tools):

```python
# Tool 1: Reconnaissance
async def analyze_page_for_extraction(
    self,
    url: str,
    objective: str,
    content: Optional[str] = None,
    extraction_schema: Optional[Type[BaseModel]] = None,
) -> ExtractionPlan:
    """
    LLM analyzes the page content and generates an ExtractionPlan.

    If content is None, scrapes the page first.
    If extraction_schema is provided (Pydantic model), uses it as
    the target schema instead of discovering entities.

    This is auto-discovered as a tool by AbstractToolkit.
    The ScrapingAgent's LLM can call this tool during reasoning.
    """

# Tool 2: Structured extraction
async def extract_structured_data(
    self,
    url: str,
    plan: ExtractionPlan,
    content: Optional[str] = None,
) -> ExtractionResult:
    """
    Execute extraction using the provided plan.

    Depending on plan.extraction_strategy:
    - "llm":    Pass content + schema to LLM, get structured output
    - "css":    Use BeautifulSoup with plan selectors
    - "hybrid": CSS first, LLM fills gaps

    This is auto-discovered as a tool by AbstractToolkit.
    """
```

### 6.3 New Method on ScrapingAgent

```python
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
    """
    High-level entry point: scrape + extract + return Documents.

    This is what the loader handler calls instead of WebScrapingLoader.

    Resolution chain:
    1. Check ExtractionRegistry for cached ExtractionPlan (Path D)
    2. Use provided extraction_plan if given (Path B)
    3. Run LLM reconnaissance to generate ExtractionPlan (Path A)

    If scraping_plan is provided, uses it for navigation (Path C).
    Otherwise uses ScrapingPlan resolution (existing behavior).

    If crawl=True, applies extraction to each crawled page.

    On success with save_plan=True, caches the ExtractionPlan.

    Returns:
        List[Document] ready for vector store ingestion.
    """
```

### 6.4 Entity → Document Conversion

```python
def _entities_to_documents(
    self,
    entities: List[ExtractedEntity],
    url: str,
    extraction_plan: ExtractionPlan,
) -> List[Document]:
    """
    Convert extracted entities to Parrot Documents.

    Each entity becomes one Document where:
    - page_content = entity.rag_text (natural language for vectorization)
    - metadata includes:
        - entity_type, source_url, extracted_at
        - All entity fields (for structured filtering)
        - extraction_plan reference (for provenance)
        - page_category from the plan
    """
    documents = []
    for entity in entities:
        metadata = {
            "source": url,
            "url": url,
            "source_type": "webpage_structured",
            "type": entity.entity_type,
            "category": extraction_plan.page_category,
            "entity_type": entity.entity_type,
            "extraction_confidence": entity.confidence,
            "created_at": datetime.now().strftime("%Y-%m-%d, %H:%M:%S"),
            "document_meta": {
                "extraction_strategy": extraction_plan.extraction_strategy,
                "plan_source": extraction_plan.source,
                "plan_version": extraction_plan.version,
                **entity.fields,  # All structured fields as metadata
            },
        }
        documents.append(Document(
            page_content=entity.rag_text,
            metadata=metadata,
        ))
    return documents
```

---

## 7. LLM Prompts

### 7.1 Reconnaissance Prompt

```
You are a web content analysis expert. Analyze the following web page content
and identify all extractable entities based on the user's objective.

OBJECTIVE: {objective}
URL: {url}

PAGE CONTENT (first {max_tokens} tokens):
{content}

Generate an extraction plan as JSON matching this schema:
{ExtractionPlan.model_json_schema()}

Rules:
- Identify ALL distinct entity types visible on the page
- For each entity, list ALL fields that can be extracted
- Provide CSS selectors when the HTML structure is clear
- Set extraction_strategy to "hybrid" if selectors are uncertain
- Set extraction_strategy to "css" only if selectors are highly reliable
- Include descriptive field names (snake_case)
- Set repeating=True if multiple instances of the entity exist
- List sections to ignore (navigation, footer, cookie banners, etc.)
- Be specific about field_type (currency for prices, url for links, etc.)

Respond ONLY with valid JSON. No explanations.
```

### 7.2 Extraction Prompt (LLM strategy)

```
You are a data extraction expert. Extract structured data from the following
web page content according to the provided schema.

EXTRACTION SCHEMA:
{extraction_plan_json}

PAGE CONTENT:
{content}

For each entity type in the schema, extract ALL instances found on the page.
For each instance, extract ALL fields defined in the schema.

Additionally, for each extracted entity, generate a "rag_text" field containing
a natural language sentence that describes the entity with all its key attributes.
This text will be used for semantic search, so it should be information-dense
and self-contained.

Example rag_text for a telecom plan:
"AT&T Prepaid 5 GB plan costs $30/month. Includes 5GB of data, unlimited
talk and text in the US, SD streaming. No hotspot included."

Respond with JSON:
{
  "entities": [
    {
      "entity_type": "...",
      "fields": { ... },
      "rag_text": "...",
      "confidence": 0.95
    },
    ...
  ]
}

Rules:
- Extract EVERY instance, not just the first one
- Use null for fields that cannot be determined
- Set confidence lower (0.5-0.7) for inferred/uncertain values
- rag_text must be a complete, standalone sentence
- Do NOT invent data that isn't on the page
```

---

## 8. Integration with Loader Handler

Current flow (unchanged for simple sites):
```python
# Handler receives URL → picks loader → gets documents
loader = WebScrapingLoader(url=url, ...)
docs = await loader.load()
await knowledge_base.ingest(docs)
```

New flow for intelligent extraction:
```python
# Handler receives URL + objective → uses ScrapingAgent
agent = await agent_registry.get_instance("ScrapingAgent")
docs = await agent.extract_documents(
    url=url,
    objective=user_objective,
    # Optional: pre-built plan for known sites
    extraction_plan=site_plans.get(domain),
)
await knowledge_base.ingest(docs)
```

The handler needs a decision point: **when to use ScrapingAgent vs WebScrapingLoader?**

Options:
- (a) Always use ScrapingAgent (simplest, but overkill for docs/blogs)
- (b) User/config flag: `extraction_mode: "simple" | "intelligent"`
- (c) Heuristic: if `objective` is provided → ScrapingAgent; otherwise → WebScrapingLoader

**Recommendation:** Option (c) — the presence of an `objective` string is the
natural trigger. Simple URL-only requests go through WebScrapingLoader.
Requests with an extraction objective go through ScrapingAgent.

---

## 9. Pre-built Plans (Developer-Provided)

Pre-built plans live in a well-known directory (configurable):

```
extraction_plans/
├── _prebuilt/
│   ├── att_prepaid.json
│   ├── amazon_product.json
│   ├── bestbuy_product.json
│   └── generic_ecommerce.json
```

These are loaded into the ExtractionRegistry at startup with
`source="developer"` and high priority. They can be overridden by
cached (learned) plans but are always available as fallback.

Connection to existing `_initialize_templates()` in ScrapingAgent:
the current templates define **navigation** (ScrapingPlan). Pre-built
ExtractionPlans are the complementary piece — they define **what to extract**.
A complete pre-built configuration for a site has both:

```python
# Existing: navigation template (how to get to the content)
BESTBUY_TEMPLATE = {
    'search_steps': [...],
    'product_selectors': [...],
}

# New: extraction plan (what data to pull out)
BESTBUY_EXTRACTION = ExtractionPlan(
    url="https://www.bestbuy.com/*",
    entities=[
        EntitySpec(
            entity_type="product",
            fields=[
                EntityFieldSpec(name="name", selector=".sku-title h1"),
                EntityFieldSpec(name="price", field_type="currency", selector=".priceView-customer-price span"),
                EntityFieldSpec(name="rating", field_type="number", selector=".c-ratings-reviews-v4 .c-stars"),
                ...
            ]
        )
    ],
    extraction_strategy="hybrid",  # CSS with LLM fallback
    source="developer",
)
```

---

## 10. Multi-Page / Crawl Extraction

When `crawl=True`, the agent applies the ExtractionPlan to each page:

```
att.com/prepaid/           → ExtractionPlan recon (or cache hit)
att.com/prepaid/5gb-plan   → Same ExtractionPlan (path-prefix match)
att.com/prepaid/phones     → May need different ExtractionPlan (different entity types)
```

**Question:** Should the agent run recon once for the first page and assume
the plan applies to all crawled pages? Or should it detect when a crawled page
has a different structure and trigger a new recon?

**Recommendation:** Optimistic approach — run recon on the first page, apply
to all pages with the same path prefix. If extraction returns 0 entities for
a page, flag it and optionally re-run recon for that specific page. This avoids
expensive LLM calls for every page while handling structural differences.

---

## 11. Open Questions

1. **Content truncation for LLM:** Pages like AT&T can have 50K+ tokens of
   HTML. The recon prompt needs truncated content. Strategy:
   - Strip `<script>`, `<style>`, `<noscript>`, `<link>`, `<meta>` tags
   - Extract only `<main>` or first `<article>` if available
   - Convert to markdown (compact representation)
   - Truncate to ~8K tokens
   - Alternatively: send raw HTML of the `<main>` container (LLM can read
     CSS classes and DOM structure better from HTML than markdown)
   **Decision needed:** Markdown vs HTML for the recon prompt?

2. **Structured output provider differences:** Google Gemini doesn't support
   native structured output when tools are present (known AI-Parrot limitation).
   The extraction prompt returns JSON, so we need:
   - Anthropic/OpenAI: Use `structured_output=ExtractionResult`
   - Gemini: Use JSON-mode prompt + manual parsing
   - Groq: Use permissive Pydantic schema (`extra='allow'`)
   **Can we use a second non-tool LLM call for extraction?** Yes — similar to
   PandasAgent's dual-LLM architecture.

3. **ExtractionPlan versioning:** When should a cached plan be invalidated?
   - Time-based: plans older than N days trigger re-validation
   - Failure-based: N consecutive failures invalidate
   - Content-hash: page content hash changed significantly
   **Recommendation:** Failure-based as primary, time-based as secondary
   (e.g., invalidate after 30 days even if still working).

4. **rag_text generation:** Should the LLM generate rag_text during extraction,
   or should we generate it programmatically from structured fields?
   - LLM-generated: More natural, better for semantic search
   - Programmatic: Deterministic, cheaper, consistent format
   - Hybrid: LLM generates for complex entities, template for simple ones
   **Recommendation:** LLM-generated during extraction phase (one LLM call
   handles both extraction and rag_text generation).

5. **Token budget:** The extraction prompt with full page content + schema
   can be large. For pages with many entities (50+ products), should we:
   - Extract all in one call (risk: output truncation)
   - Chunk the page and extract per-chunk (risk: entity split across chunks)
   - Use CSS selectors to isolate entity containers, then LLM per-container
   **Recommendation:** Hybrid — use CSS container selectors (if available in
   the ExtractionPlan) to split the page into per-entity chunks, then batch
   multiple entities per LLM call. If no selectors, let the LLM handle the
   full page with a warning about potential truncation.

---

## 12. Sequenced Tasks

### Task 1: ExtractionPlan & ExtractedEntity Models
**Package:** `ai-parrot-tools/src/parrot_tools/scraping/`
**Dependencies:** None
- Create `extraction_models.py` with Pydantic models:
  `EntityFieldSpec`, `EntitySpec`, `ExtractionPlan`, `ExtractedEntity`,
  `ExtractionResult`
- Include `_normalize_url()` and `_compute_fingerprint()` (reuse from plan.py
  or extract to shared utility)
- Include `model_json_schema()` for prompt generation
- Write unit tests for model validation and serialization

### Task 2: ExtractionPlanRegistry
**Package:** `ai-parrot-tools/src/parrot_tools/scraping/`
**Dependencies:** Task 1
- Option: Extract `BasePlanRegistry[T]` from existing `PlanRegistry`
  OR create `ExtractionPlanRegistry` as separate class (decide during SDD)
- Disk-backed with `extraction_registry.json`
- Three-tier lookup: exact → path-prefix → domain
- `register()`, `lookup()`, `touch()`, `invalidate()`, `list_all()`
- Cache lifecycle: success/failure counting, time-based invalidation
- Async lock for concurrent writes
- Write tests

### Task 3: ExtractionPlanGenerator (LLM Reconnaissance)
**Package:** `ai-parrot-tools/src/parrot_tools/scraping/`
**Dependencies:** Task 1
- Create `extraction_plan_generator.py` analogous to `plan_generator.py`
- `generate()` method: content + objective → ExtractionPlan
- Prompt template for reconnaissance (Section 7.1)
- Content preparation: strip noise tags, truncate, format for LLM
- JSON response parsing with code-fence stripping (reuse `_strip_code_fences`)
- Support for `extraction_schema` parameter (Pydantic model → EntitySpec mapping)
- Write tests with mock LLM responses

### Task 4: Structured Data Extractor
**Package:** `ai-parrot-tools/src/parrot_tools/scraping/`
**Dependencies:** Task 1, Task 3
- Create `structured_extractor.py`
- Three strategies:
  - `LLMExtractor`: Send content + schema → LLM → parsed entities
  - `CSSExtractor`: BeautifulSoup with selectors from ExtractionPlan
  - `HybridExtractor`: CSS first, LLM fills missing fields
- `extract()` method: content + ExtractionPlan → ExtractionResult
- Extraction prompt template (Section 7.2)
- Handle provider-specific structured output differences
- `rag_text` generation (LLM or template-based)
- Write tests for each strategy

### Task 5: New Tools on WebScrapingToolkit
**Package:** `ai-parrot-tools/src/parrot_tools/scraping/toolkit.py`
**Dependencies:** Task 2, Task 3, Task 4
- Add `analyze_page_for_extraction()` public async method
- Add `extract_structured_data()` public async method
- Both auto-discovered as tools by AbstractToolkit
- Wire up ExtractionPlanRegistry for cache lookup/save
- Wire up ExtractionPlanGenerator for recon
- Wire up StructuredExtractor for extraction
- Write integration tests

### Task 6: ScrapingAgent.extract_documents()
**Package:** `ai-parrot/src/parrot/bots/scraper/scraper.py`
**Dependencies:** Task 5
- Add `extract_documents()` method with full resolution chain
- Entity → Document conversion (`_entities_to_documents()`)
- Path A/B/C/D flow control
- Auto-save successful ExtractionPlans (fire-and-forget)
- Crawl mode: apply ExtractionPlan across multiple pages
- Integration with existing `generate_scraping_plan()` for navigation
- Write integration tests

### Task 7: Pre-built ExtractionPlans
**Package:** `ai-parrot-tools/src/parrot_tools/scraping/`
**Dependencies:** Task 1, Task 2
- Create `extraction_plans/_prebuilt/` directory
- Define 2-3 example plans: `generic_ecommerce.json`, `generic_telecom.json`
- Load pre-built plans into ExtractionRegistry at toolkit init
- Connect with existing `_initialize_templates()` templates
- Write tests for pre-built plan loading and lookup

### Task 8: Handler Integration
**Package:** `ai-parrot` (loader handler)
**Dependencies:** Task 6
- Add decision logic: `objective` present → ScrapingAgent; else → WebScrapingLoader
- Wire `extract_documents()` into the handler pipeline
- Ensure Documents flow correctly to `knowledge_base.ingest()`
- Write end-to-end test: URL + objective → Documents in vector store

---

## 13. Testing Strategy

- **Unit tests** for models, registry, generators (mock LLM)
- **Integration tests** with a local test HTML page simulating AT&T-style
  structure (multiple plan cards with prices, features, etc.)
- **Snapshot tests** for LLM prompts (ensure prompt changes are intentional)
- **Cache tests**: verify lookup tiers, invalidation, success/failure counting
- **Multi-page test**: crawl + extraction across 2-3 linked test pages

---

## 14. Future Enhancements (Out of Scope for This FEAT)

- **Delta extraction**: Compare new extraction with previous run, only update
  changed entities in the vector store
- **Extraction validation**: Post-extraction LLM call to verify data quality
  (e.g., "does this price look reasonable for a prepaid plan?")
- **Visual extraction**: Send page screenshot to multimodal LLM for entities
  that are rendered visually (images, charts) rather than in DOM text
- **Cross-page entity merging**: Entities that span multiple pages (e.g., plan
  overview on listing page + full details on detail page) merged into single
  Document
- **Extraction analytics**: Dashboard showing extraction success rates per
  domain, plan cache hit rates, LLM cost per extraction