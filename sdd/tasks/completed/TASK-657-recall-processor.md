# TASK-657: RecallProcessor (Post-Extraction LLM)

**Feature**: intelligent-scraping-pipeline
**Spec**: `sdd/specs/intelligent-scraping-pipeline.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-653
**Assigned-to**: unassigned

---

## Context

> Implements Module 5 from the spec. After mechanical extraction via WebScrapingToolkit,
> this component makes a single LLM call to:
> 1. Generate `rag_text` (natural language sentences) for each extracted entity
> 2. Fill data gaps by reviewing the original page content
> 3. Flag potentially missed entities
> This is the quality-assurance step that bridges structured extraction and semantic search.

---

## Scope

- Implement `RecallProcessor` class with LLM client
- Implement `recall()` method: extracted entities + page HTML excerpt + ExtractionPlan -> enriched entities
- Implement `_build_recall_prompt()`: formats prompt with entities, HTML context, and entity definitions
- Implement `_prepare_html_context()`: extract only HTML sections matching selectors + 500-token context window
- Implement `_parse_recall_response()`: parse LLM JSON response, merge rag_text and filled gaps into entities
- Write unit tests with mock LLM responses

**NOT in scope**:
- ExtractionPlanGenerator (TASK-656)
- ScrapingAgent integration (TASK-659)
- Registry (TASK-655)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/recall_processor.py` | CREATE | Post-extraction LLM recall |
| `packages/ai-parrot-tools/tests/scraping/test_recall_processor.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py` | MODIFY | Export new processor |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.extraction_models import (
    ExtractionPlan, ExtractedEntity, EntitySpec  # created by TASK-653
)
from bs4 import BeautifulSoup  # already a dependency
```

### Existing Signatures to Use
```python
# Created by TASK-653 — ExtractedEntity
class ExtractedEntity(BaseModel):
    entity_type: str
    fields: Dict[str, Any]
    source_url: str
    confidence: float = 0.0
    raw_text: Optional[str] = None
    rag_text: str = ""  # THIS TASK fills this field

# Created by TASK-653 — ExtractionPlan
class ExtractionPlan(BaseModel):
    entities: List[EntitySpec]  # entity definitions for context
    # ...

# LLM client interface (same as PlanGenerator uses)
# llm_client.complete(prompt: str) -> str  (async)
```

### Does NOT Exist
- ~~`RecallProcessor`~~ -- does not exist yet; THIS TASK creates it
- ~~`ExtractedEntity.generate_rag_text()`~~ -- not a method; rag_text is set externally
- ~~`ExtractionPlan.get_context_html()`~~ -- not a method

---

## Implementation Notes

### Pattern to Follow
```python
class RecallProcessor:
    """Post-extraction LLM recall for rag_text generation and gap-filling.

    Makes a single LLM call after mechanical extraction to:
    1. Generate natural language rag_text for each entity
    2. Fill missing field values from original page content
    3. Flag potentially missed entities

    The LLM client must support ``async def complete(prompt: str) -> str``.
    """

    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client
        self.logger = logging.getLogger(__name__)

    async def recall(
        self,
        entities: List[ExtractedEntity],
        page_html: str,
        extraction_plan: ExtractionPlan,
        url: str,
    ) -> List[ExtractedEntity]:
        """Enrich extracted entities with rag_text and gap-filling."""
        context = self._prepare_html_context(page_html, extraction_plan)
        prompt = self._build_recall_prompt(entities, context, extraction_plan)
        raw = await self._client.complete(prompt)
        return self._parse_recall_response(raw, entities)
```

### Recall Prompt Design
The prompt must:
1. Present each extracted entity with its fields (JSON)
2. Include the relevant HTML context (sections matching selectors + 500-token window)
3. Include the ExtractionPlan entity definitions (what was expected)
4. Ask the LLM to:
   - Generate a `rag_text` sentence for each entity (information-dense, self-contained)
   - Fill any null fields if the data is visible in the HTML context
   - Flag any entities that appear to be missing from the extracted set
5. Return JSON with enriched entities

### HTML Context Preparation
```python
def _prepare_html_context(self, page_html: str, plan: ExtractionPlan) -> str:
    """Extract HTML sections matching plan selectors + context window."""
    soup = BeautifulSoup(page_html, "html.parser")
    sections = []
    for entity_spec in plan.entities:
        if entity_spec.container_selector:
            containers = soup.select(entity_spec.container_selector)
            for container in containers[:10]:  # limit to 10 containers
                sections.append(str(container))
    # If no selectors matched, fall back to main/article/body
    if not sections:
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            sections.append(str(main)[:4000])
    return "\n".join(sections)[:8000]  # ~500-token context * entities
```

### Key Constraints
- Single LLM call for ALL entities (batch, not per-entity)
- Use the same LLM client instance (resolved open question)
- Context window: include matched HTML sections + 500-token window around each
- Total context must not exceed ~8K tokens
- If recall fails (malformed response), return original entities unchanged (graceful degradation)

---

## Acceptance Criteria

- [ ] `RecallProcessor.recall()` enriches entities with rag_text
- [ ] Gap-filling populates null fields from page content
- [ ] HTML context preparation limits output to ~8K tokens
- [ ] Handles malformed LLM response gracefully (returns original entities)
- [ ] Single LLM call for all entities (not per-entity)
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_recall_processor.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_recall_processor.py
import pytest
from unittest.mock import AsyncMock
from parrot_tools.scraping.recall_processor import RecallProcessor
from parrot_tools.scraping.extraction_models import ExtractionPlan, ExtractedEntity, EntitySpec, EntityFieldSpec


@pytest.fixture
def mock_llm_recall():
    client = AsyncMock()
    client.complete = AsyncMock(return_value='{"entities": [{"index": 0, "rag_text": "5 GB Plan costs $30/month with unlimited talk.", "filled_fields": {}}]}')
    return client


class TestRecallProcessor:
    async def test_generates_rag_text(self, mock_llm_recall):
        processor = RecallProcessor(llm_client=mock_llm_recall)
        entities = [
            ExtractedEntity(entity_type="plan", fields={"name": "5 GB", "price": "$30"}, source_url="https://example.com")
        ]
        plan = ExtractionPlan(url="https://example.com", objective="Extract plans", entities=[])
        result = await processor.recall(entities, "<html><body>...</body></html>", plan, "https://example.com")
        assert result[0].rag_text != ""

    async def test_graceful_degradation_on_failure(self):
        bad_llm = AsyncMock()
        bad_llm.complete = AsyncMock(return_value="not valid json at all")
        processor = RecallProcessor(llm_client=bad_llm)
        entities = [ExtractedEntity(entity_type="plan", fields={}, source_url="https://example.com")]
        plan = ExtractionPlan(url="https://example.com", objective="test", entities=[])
        result = await processor.recall(entities, "<html></html>", plan, "https://example.com")
        assert len(result) == len(entities)  # returns original unchanged

    def test_prepare_html_context_limits_size(self):
        processor = RecallProcessor(llm_client=AsyncMock())
        long_html = "<html><body><main>" + "<div class='card'>x</div>" * 10000 + "</main></body></html>"
        plan = ExtractionPlan(url="https://example.com", objective="test", entities=[
            EntitySpec(entity_type="item", description="test", fields=[], container_selector=".card")
        ])
        context = processor._prepare_html_context(long_html, plan)
        assert len(context) <= 10000  # reasonable upper bound
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/intelligent-scraping-pipeline.spec.md`
2. **Check dependencies** -- verify TASK-653 is completed
3. **Read `plan_generator.py`** -- understand the LLM call + JSON parse pattern
4. **Implement** following the scope and contract
5. **Move to completed**, update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
