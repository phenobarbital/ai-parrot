# TASK-659: ScrapingAgent.extract_documents() Orchestration

**Feature**: intelligent-scraping-pipeline
**Spec**: `sdd/specs/intelligent-scraping-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-653, TASK-654, TASK-655, TASK-656, TASK-657, TASK-658
**Assigned-to**: unassigned

---

## Context

> Implements Module 6 from the spec. This is the capstone task that wires together all
> previous modules into `ScrapingAgent.extract_documents()` — the high-level entry point
> for the intelligent extraction pipeline. Implements the full 5-phase pipeline: plan
> resolution, navigate & download, LLM reconnaissance, mechanical extraction, LLM recall,
> and document assembly.

---

## Scope

- Add `extract_documents()` method to `ScrapingAgent`
- Implement plan resolution chain: explicit -> cached (ExtractionPlanRegistry) -> pre-built -> LLM recon
- Implement navigate & download phase using `WebScrapingToolkit`
- Integrate `ExtractionPlanGenerator` for LLM reconnaissance (Phase 3)
- Implement ExtractionPlan -> ScrapingPlan translation + mechanical extraction (Phase 4)
- Integrate `RecallProcessor` for post-extraction recall (Phase 5)
- Implement `_entities_to_documents()`: convert `List[ExtractedEntity]` to `List[Document]`
- Implement `_extracted_data_to_entities()`: convert `ScrapingResult.extracted_data` to `List[ExtractedEntity]` using ExtractionPlan entity definitions
- Auto-save successful ExtractionPlans to registry (fire-and-forget)
- Cache invalidation on extraction failure (3 failures)
- Support `crawl=True` for multi-page extraction
- Initialize `WebScrapingToolkit` and `ExtractionPlanRegistry` on ScrapingAgent
- Write integration tests

**NOT in scope**:
- Modifying existing ScrapingAgent methods (analyze_scraping_request, execute_intelligent_scraping)
- Modifying WebScrapingToolkit
- Modifying PlanRegistry or PlanGenerator

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/scraper/scraper.py` | MODIFY | Add extract_documents() and helper methods |
| `packages/ai-parrot/tests/scraping/test_extract_documents.py` | CREATE | Integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Existing (verified 2026-04-13):
from parrot_tools.scraping.toolkit import WebScrapingToolkit  # toolkit.py:27
from parrot_tools.scraping.plan import ScrapingPlan  # plan.py:59
from parrot_tools.scraping.models import ScrapingResult  # models.py:622
from parrot.stores.models import Document  # stores/models.py:21
from parrot.bots.scraper.scraper import ScrapingAgent  # scraper.py:30

# Created by prior tasks (verify they exist when starting):
from parrot_tools.scraping.extraction_models import (
    ExtractionPlan, ExtractedEntity, ExtractionResult, EntitySpec, EntityFieldSpec  # TASK-653
)
from parrot_tools.scraping.extraction_registry import ExtractionPlanRegistry  # TASK-655
from parrot_tools.scraping.extraction_plan_generator import ExtractionPlanGenerator  # TASK-656
from parrot_tools.scraping.recall_processor import RecallProcessor  # TASK-657
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/scraper/scraper.py
class ScrapingAgent(BaseBot):  # line 30
    def __init__(self, name="WebScrapingAgent", browser=..., driver_type=...,
                 headless=..., mobile=..., mobile_device=..., auto_install=..., **kwargs):  # line 40
        self.browser_config: Dict[str, Any]  # line 61
        self.scraping_tool: WebScrapingTool  # line 72 — NOTE: deprecated, use WebScrapingToolkit
        self.scraping_history: List[Dict[str, Any]]  # line 77
        self.site_knowledge: Dict[str, Dict[str, Any]]  # line 78

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):  # line 27
    async def scrape(self, url, plan=None, objective=None, steps=None,
                     selectors=None, ...) -> ScrapingResult:  # line 370
    async def crawl(self, start_url, depth=1, ...) -> Any:  # line 436

# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
@dataclass
class ScrapingResult:  # line 622
    url: str
    content: str
    bs_soup: BeautifulSoup
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None

# packages/ai-parrot/src/parrot/stores/models.py
class Document(BaseModel):  # line 21
    page_content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### Does NOT Exist
- ~~`ScrapingAgent.extract_documents()`~~ -- does not exist yet; THIS TASK creates it
- ~~`ScrapingAgent._entities_to_documents()`~~ -- does not exist yet; THIS TASK creates it
- ~~`ScrapingAgent._extracted_data_to_entities()`~~ -- does not exist yet; THIS TASK creates it
- ~~`ScrapingAgent.extraction_registry`~~ -- does not exist yet; THIS TASK initializes it
- ~~`ScrapingAgent.extraction_toolkit`~~ -- does not exist yet; THIS TASK initializes it
- ~~`WebScrapingToolkit.extract_structured_data()`~~ -- does not exist
- ~~`Document.entity_type`~~ -- Document has only `page_content` and `metadata`
- ~~`ScrapingResult.entities`~~ -- has `extracted_data` (Dict), not entities

---

## Implementation Notes

### extract_documents() Flow
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
    # Phase 1: Plan Resolution
    plan = extraction_plan or await self._resolve_extraction_plan(url, objective)

    # Phase 2: Navigate & Download
    if crawl:
        results = await self._toolkit.crawl(url, depth=depth, max_pages=max_pages, ...)
    else:
        result = await self._toolkit.scrape(url, plan=scraping_plan)
        results = [result]

    all_documents = []
    for result in results:
        if not result.success:
            continue

        # Phase 3: LLM Recon (if no plan yet)
        if plan is None:
            plan = await self._extraction_generator.generate(
                url=result.url,
                objective=objective,
                content=result.content,
            )

        # Phase 3b: Translate to ScrapingPlan
        sp = plan.to_scraping_plan()

        # Phase 4: Mechanical extraction with selectors
        extraction_result = await self._toolkit.scrape(
            url=result.url,
            selectors=[s for s in sp.selectors] if sp.selectors else None,
        )

        # Convert extracted_data to entities
        entities = self._extracted_data_to_entities(extraction_result, plan)

        # Phase 5: LLM Recall
        entities = await self._recall_processor.recall(
            entities=entities,
            page_html=result.content,
            extraction_plan=plan,
            url=result.url,
        )

        # Phase 6: Document Assembly
        documents = self._entities_to_documents(entities, result.url, plan)
        all_documents.extend(documents)

    # Plan caching (fire-and-forget)
    if save_plan and plan and all_documents:
        await self._save_extraction_plan(plan)

    return all_documents
```

### _entities_to_documents() Pattern
```python
def _entities_to_documents(
    self,
    entities: List[ExtractedEntity],
    url: str,
    extraction_plan: ExtractionPlan,
) -> List[Document]:
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
            "document_meta": {
                "extraction_strategy": extraction_plan.extraction_strategy,
                "plan_source": extraction_plan.source,
                **entity.fields,
            },
        }
        documents.append(Document(
            page_content=entity.rag_text,
            metadata=metadata,
        ))
    return documents
```

### WebScrapingToolkit Initialization
ScrapingAgent currently uses `WebScrapingTool` (deprecated). For `extract_documents()`,
initialize a `WebScrapingToolkit` instance. Add to `__init__()`:

```python
# In __init__, alongside existing self.scraping_tool:
self._toolkit = WebScrapingToolkit(
    driver_type=driver_type,
    browser=browser,
    headless=headless,
    mobile=mobile,
    mobile_device=mobile_device,
    auto_install=auto_install,
    llm_client=kwargs.get('llm_client'),
)
self._extraction_registry = ExtractionPlanRegistry(
    plans_dir=kwargs.get('extraction_plans_dir'),
)
self._extraction_generator = ExtractionPlanGenerator(
    llm_client=self._llm,  # from BaseBot
)
self._recall_processor = RecallProcessor(
    llm_client=self._llm,  # from BaseBot
)
```

### Key Constraints
- Use `WebScrapingToolkit` for extraction (not the deprecated WebScrapingTool)
- Use `self._llm` from BaseBot for LLM calls (same client instance, resolved open question)
- Fire-and-forget plan saving: use `asyncio.create_task()` or try/except to avoid blocking
- On extraction failure with cached plan: call `registry.record_failure()` and retry with fresh recon
- Multi-page crawl: optimistic plan reuse (same plan for same path prefix); re-recon if 0 entities

---

## Acceptance Criteria

- [ ] `ScrapingAgent.extract_documents()` returns `List[Document]` with entity-level granularity
- [ ] Plan resolution chain works: explicit -> cached -> pre-built -> LLM recon
- [ ] Each Document has `page_content=rag_text` and metadata with structured fields
- [ ] Successful plans are auto-saved to ExtractionPlanRegistry
- [ ] Failed extraction with cached plan triggers re-reconnaissance after 3 failures
- [ ] Crawl mode applies ExtractionPlan across multiple pages
- [ ] Integration tests pass with mock LLM
- [ ] No breaking changes to existing ScrapingAgent methods

---

## Test Specification

```python
# packages/ai-parrot/tests/scraping/test_extract_documents.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.bots.scraper.scraper import ScrapingAgent
from parrot_tools.scraping.extraction_models import ExtractionPlan, EntitySpec, EntityFieldSpec


class TestExtractDocuments:
    @pytest.fixture
    def agent(self):
        # Create agent with mocked LLM and toolkit
        ...

    async def test_with_prebuilt_plan(self, agent):
        """Full pipeline with pre-built ExtractionPlan skips recon."""
        plan = ExtractionPlan(...)
        docs = await agent.extract_documents(
            url="https://example.com/plans",
            objective="Extract plans",
            extraction_plan=plan,
        )
        assert len(docs) > 0
        assert all(d.page_content for d in docs)
        assert all("entity_type" in d.metadata for d in docs)

    async def test_full_pipeline_with_recon(self, agent):
        """Full pipeline with LLM recon generates plan and extracts."""
        docs = await agent.extract_documents(
            url="https://example.com/plans",
            objective="Extract all plans",
        )
        assert len(docs) > 0

    async def test_entities_to_documents(self, agent):
        """ExtractedEntity list converts to Document list correctly."""
        ...

    async def test_plan_cached_on_success(self, agent):
        """Successful extraction saves plan to registry."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/intelligent-scraping-pipeline.spec.md`
2. **Check ALL dependencies** -- verify TASK-653 through TASK-658 are completed
3. **Read the completed task outputs** to understand the actual interfaces created
4. **Read `scraper.py` in full** before modifying
5. **Verify all imports** from prior tasks exist in the codebase
6. **Implement** following the scope, contract, and flow described above
7. **Run integration tests** to verify the full pipeline
8. **Move to completed**, update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
