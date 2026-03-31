# Feature Specification: Advisor Ontologic RAG Agent (Gorilla Sheds Example)

**Feature ID**: FEAT-071
**Date**: 2026-03-31
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot now has an Intent Router (FEAT-070) and an Ontology RAG pipeline, but there
is no end-to-end example that wires them together into a real-world product advisor
agent. The existing `examples/advisors/product_advisor_basebot.py` demonstrates the
`ProductAdvisorMixin` with `BaseBot` but does **not** use:

- `OntologyRAGMixin` for ontology-enriched retrieval
- `EpisodicMemoryMixin` for conversational memory across sessions
- `WorkingMemoryToolkit` for intermediate analytics
- `PageIndexRetriever` for tree-structured product navigation
- `IntentRouterMixin` for pre-RAG query routing

We need a **complete, standalone example** — `examples/shoply/sample.py` — that sells
**Gorilla Sheds** products using all of the above, backed by a vectorised product
catalog in `gorillashed.products` (PgVector).

### Goals

1. **Scrape & index** Gorilla Sheds data (about page, FAQ, installation process,
   product listings) into a `PageIndex` tree:
   `Company Info → Product Type (Sheds) → Individual Products`.
2. **Vectorise** scraped product data into `gorillashed.products` via `PgVectorStore`
   and `ProductCatalog` (is not required because gorillashed.products is already filled with products vectorized).
3. **Build a product advisor agent** that composes:
   - `ProductAdvisorMixin` — guided selection tools
   - `OntologyRAGMixin` — ontology-enriched retrieval
   - `EpisodicMemoryMixin` — session memory
   - `WorkingMemoryToolkit` — intermediate result store
   - `PageIndexRetriever` — tree-navigable product index
   - `IntentRouterMixin` — pre-RAG routing
4. **Standalone execution**: `python examples/shoply/sample.py` starts an interactive
   chat (like `product_advisor_basebot.py`).

### Non-Goals (explicitly out of scope)

- Building a production web UI or API server for the agent
- Implementing a new scraping framework (use `aiohttp` + `BeautifulSoup`)
- Modifying core parrot library code (this is an example/demo)
- Real-time product price sync or inventory management
- A2A or MCP integration for this example

---

## 2. Architectural Design

### Overview

The example consists of three logical phases:

1. **Scrape & Build PageIndex** — fetch Gorilla Sheds pages, parse product data,
   build a hierarchical `PageIndex` JSON tree, persist to disk.
2. **Vectorise Products** — load scraped products into `ProductCatalog` →
   `PgVectorStore` in `gorillashed.products`.
3. **Run Agent** — instantiate a multi-mixin bot that combines all capabilities,
   start an interactive chat loop.

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    examples/shoply/                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  scraper.py ──► PageIndex JSON ──► page_index.json              │
│       │                                                          │
│       └──► ProductSpec list ──► load_catalog.py ──► PgVector    │
│                                    (gorillashed.products)        │
│                                                                  │
│  sample.py                                                       │
│    ├── GorillaAdvisorBot                                        │
│    │     ├── ProductAdvisorMixin   (guided selection)           │
│    │     ├── OntologyRAGMixin      (graph + vector RAG)         │
│    │     ├── EpisodicMemoryMixin   (session memory)             │
│    │     ├── IntentRouterMixin     (pre-RAG routing)            │
│    │     └── BaseBot               (LLM conversation)           │
│    │                                                             │
│    ├── WorkingMemoryToolkit        (registered as tool)         │
│    ├── PageIndexRetriever          (tree context injection)     │
│    └── ProductCatalog              (hybrid product search)      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component       | Integration Type | Notes |
|--------------------------|-----------------|-------|
| `ProductAdvisorMixin`    | mixin           | Guided selection tools (start, filter, compare, recommend) |
| `OntologyRAGMixin`       | mixin           | Ontology-enriched retrieval via `ontology_process()` |
| `EpisodicMemoryMixin`    | mixin           | Auto-records tool executions and conversations |
| `IntentRouterMixin`      | mixin           | Routes queries to graph/vector/tool/free strategies |
| `BaseBot`                | base class      | LLM conversation, tool management |
| `ProductCatalog`         | composition     | Wraps `PgVectorStore` for hybrid product search |
| `PgVectorStore`          | composition     | Vector storage in `gorillashed.products` |
| `PageIndexRetriever`     | composition     | Tree-structured product navigation |
| `WorkingMemoryToolkit`   | tool            | Registered with tool manager for intermediate results |

### Data Models

```python
# PageIndex tree structure (persisted as JSON)
PageIndexTree = {
    "title": "Gorilla Sheds",
    "children": [
        {
            "node_id": "company-info",
            "title": "About Gorilla Sheds",
            "summary": "Company background, values, mission",
            "text": "<scraped about page content>",
        },
        {
            "node_id": "faq",
            "title": "Frequently Asked Questions",
            "summary": "Common questions about sheds",
            "text": "<scraped FAQ content>",
        },
        {
            "node_id": "installation",
            "title": "Shed Installation Process",
            "summary": "Post-sale installation service details",
            "text": "<scraped installation page content>",
        },
        {
            "node_id": "products",
            "title": "Sheds Collection",
            "summary": "All available shed products",
            "children": [
                {
                    "node_id": "product-<slug>",
                    "title": "<Product Name>",
                    "summary": "<brief description>",
                    "text": "<full product details>",
                }
                # ... one per product
            ]
        }
    ]
}
```

```python
# ProductSpec (existing model, populated from scrape)
ProductSpec(
    product_id="gorillashed-<slug>",
    name="<Product Name>",
    description="<description>",
    category="sheds",
    features=["feature1", "feature2"],
    specs={"width": ..., "depth": ..., "height": ...},
    metadata={"url": "https://gorillashed.com/products/<slug>"},
)
```

### New Public Interfaces

```python
# No new library interfaces — this is an example/demo.
# The following are example-local:

class GorillaAdvisorBot(
    IntentRouterMixin,
    OntologyRAGMixin,
    EpisodicMemoryMixin,
    ProductAdvisorMixin,
    BaseBot,
):
    """Multi-mixin advisor bot for Gorilla Sheds."""
    pass

async def scrape_gorillasheds() -> tuple[dict, list[ProductSpec]]:
    """Scrape Gorilla Sheds site, return (page_index_tree, products)."""

async def load_products(products: list[ProductSpec]) -> ProductCatalog:
    """Load products into PgVectorStore and return configured catalog."""
```

---

## 3. Module Breakdown

### Module 1: Gorilla Sheds Scraper

- **Path**: `examples/shoply/scraper.py`
- **Responsibility**:
  - Fetch and parse Gorilla Sheds pages (about, FAQ, installation, collections/sheds)
  - Extract individual product data (name, description, features, dimensions, price, images)
  - Build a hierarchical `PageIndex` JSON tree
  - Generate a list of `ProductSpec` objects
  - Persist `page_index.json` and `products.json` to `examples/shoply/data/`
- **Depends on**: `aiohttp`, `beautifulsoup4`, `parrot.advisors.catalog.ProductSpec`

### Module 2: Catalog Loader

- **Path**: `examples/shoply/load_catalog.py`
- **Responsibility**:
  - Read `products.json` from disk (or accept list from scraper)
  - Initialize `ProductCatalog` pointing to `gorillashed.products`
  - Insert all products with embeddings into PgVector
  - Verify insertion count
  - Standalone: `python examples/shoply/load_catalog.py`
- **Depends on**: Module 1 (products data), `ProductCatalog`, `PgVectorStore`

### Module 3: Advisor Agent (Main Example)

- **Path**: `examples/shoply/sample.py`
- **Responsibility**:
  - Define `GorillaAdvisorBot` with all mixins
  - Configure `ProductCatalog`, `PageIndexRetriever`, `WorkingMemoryToolkit`
  - Configure `OntologyRAGMixin` with graph store and vector store
  - Configure `EpisodicMemoryMixin` for session persistence
  - Configure `IntentRouterMixin` with capability registry
  - Run interactive chat loop (stdin/stdout)
  - Standalone: `python examples/shoply/sample.py`
- **Depends on**: Module 1, Module 2, all parrot mixins

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|------|--------|-------------|
| `test_scraper_parse_product` | Module 1 | Parses a sample product HTML into `ProductSpec` |
| `test_page_index_structure` | Module 1 | Validates tree has company, FAQ, install, products nodes |
| `test_catalog_load` | Module 2 | Products loaded into catalog with correct count |
| `test_bot_mixin_composition` | Module 3 | `GorillaAdvisorBot` instantiates with all mixins |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_scrape_and_load` | Scrape → parse → load into PgVector → search returns results |
| `test_advisor_conversation` | Bot handles greeting → question → filter → recommend flow |
| `test_pageindex_retrieval` | PageIndexRetriever navigates tree to find product by query |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_product_html():
    """Single product page HTML from Gorilla Sheds."""
    return Path("examples/shoply/tests/fixtures/sample_product.html").read_text()

@pytest.fixture
def sample_page_index():
    """Pre-built page index for testing."""
    return json.loads(Path("examples/shoply/data/page_index.json").read_text())
```

---

## 5. Acceptance Criteria

- [ ] `python examples/shoply/scraper.py` scrapes Gorilla Sheds and produces
      `data/page_index.json` + `data/products.json`
- [ ] `python examples/shoply/load_catalog.py` loads products into
      `gorillashed.products` table
- [ ] `python examples/shoply/sample.py` starts interactive chat with working
      product advisor
- [ ] Agent uses `PageIndexRetriever` to answer company/FAQ/installation questions
- [ ] Agent uses `ProductCatalog` for hybrid product search
- [ ] Agent uses `OntologyRAGMixin` for ontology-enriched retrieval
- [ ] Agent uses `EpisodicMemoryMixin` for session memory
- [ ] Agent uses `WorkingMemoryToolkit` for intermediate analytics
- [ ] Agent handles: product search, comparison, recommendation, FAQ, installation info
- [ ] No modifications to core parrot library code
- [ ] Example runs standalone with clear setup instructions in docstring/comments

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Mirror the structure of `examples/advisors/product_advisor_basebot.py`
- Use `async/await` throughout — all scrapers and bot methods are async
- Use `aiohttp.ClientSession` for HTTP requests (never `requests`)
- Use `BeautifulSoup` for HTML parsing
- Pydantic models for structured data
- Logger instead of print for operational messages (print OK for user-facing chat)

### Known Risks / Gotchas

- **Website structure changes**: Gorilla Sheds HTML may change; scraper should be
  resilient with fallbacks for missing fields.
- **Rate limiting**: Add polite delays between requests to avoid being blocked.
- **PgVector availability**: Example requires PostgreSQL + pgvector + `gorillashed`
  schema pre-created.
- **Redis availability**: `EpisodicMemoryMixin` and `SelectionStateManager` require Redis.
- **Ontology graph store**: `OntologyRAGMixin` requires ArangoDB; should gracefully
  degrade to vector-only if unavailable.

### External Dependencies

| Package | Version | Reason |
|---------|---------|--------|
| `beautifulsoup4` | `>=4.12` | HTML parsing for scraper |
| `aiohttp` | `>=3.9` | Async HTTP client (already in project) |
| `lxml` | `>=5.0` | Fast HTML parser backend for BS4 |

---

## 7. Open Questions

- [x] Should the scraper run as part of `sample.py` setup or always as a separate
      step? — *Owner: Jesus Lara*: a separate step is better for modularity.
- [x] Does the `gorillashed` schema need to be created by the example or assumed
      pre-existing? — *Owner: Jesus Lara*: exists and table is ready to use (with products vectorized).
- [x] Should the example include an ArangoDB ontology graph setup script, or rely
      solely on vector-only degradation? — *Owner: Jesus Lara*: rely on vector-only degradation.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` (sequential tasks)
- All three modules are sequential: scraper → loader → agent
- **Cross-feature dependencies**: FEAT-070 (Intent Router) must be merged first

---

## Revision History

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 0.1 | 2026-03-31 | Jesus Lara | Initial draft |
