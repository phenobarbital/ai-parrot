# TASK-656: ExtractionPlanGenerator (LLM Reconnaissance)

**Feature**: intelligent-scraping-pipeline
**Spec**: `sdd/specs/intelligent-scraping-pipeline.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-653
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 from the spec. Creates an LLM-driven reconnaissance component
> that analyzes downloaded page content and produces an `ExtractionPlan`. This is the
> "intelligence" of the pipeline — the LLM decides what entities exist on the page
> and how to extract them. Follows the exact architecture of the existing `PlanGenerator`.

---

## Scope

- Implement `ExtractionPlanGenerator` class following `PlanGenerator` architecture
- Implement `generate()` method: cleaned HTML + objective -> ExtractionPlan
- Implement `_build_prompt()`: formats reconnaissance prompt with page content, objective, and ExtractionPlan JSON schema
- Implement `_parse_response()`: parse LLM JSON response, handle code fences, validate into ExtractionPlan
- Implement `_clean_html_content()`: content preparation for LLM
  - Strip `<script>`, `<style>`, `<noscript>`, `<link>`, `<meta>` tags
  - Extract `<main>` or first `<article>` if available; fall back to `<body>`
  - Preserve CSS class names (critical for selector generation)
  - Truncate to ~8K tokens
  - Use **HTML** format (not markdown)
- Write the reconnaissance prompt template
- Write unit tests with mock LLM responses

**NOT in scope**:
- Recall processing (TASK-657)
- Registry integration (TASK-655)
- ScrapingAgent integration (TASK-659)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_plan_generator.py` | CREATE | LLM reconnaissance |
| `packages/ai-parrot-tools/tests/scraping/test_extraction_plan_generator.py` | CREATE | Unit tests |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py` | MODIFY | Export new generator |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.extraction_models import ExtractionPlan  # created by TASK-653
from parrot_tools.scraping.plan_generator import PlanGenerator, PageSnapshot  # plan_generator.py:118, :44
from parrot_tools.scraping.plan_generator import _strip_code_fences  # verify exists; if not, implement locally
from beautifulsoup4 import BeautifulSoup  # NOTE: import is `from bs4 import BeautifulSoup`
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/plan_generator.py
class PlanGenerator:  # line 118
    def __init__(self, llm_client: Any) -> None:  # line 127
        self._client = llm_client
        self.logger = logging.getLogger(__name__)

    async def generate(self, url: str, objective: str,
                       snapshot: Optional[PageSnapshot] = None,
                       hints: Optional[Dict[str, Any]] = None) -> ScrapingPlan:  # line 131
        prompt = self._build_prompt(url, objective, snapshot, hints)
        raw_response = await self._client.complete(prompt)
        return self._parse_response(raw_response, url, objective)

    def _build_prompt(self, url, objective, snapshot=None, hints=None) -> str:  # line 158
    def _parse_response(self, raw, url, objective) -> ScrapingPlan:  # line 191

# Created by TASK-653 — ExtractionPlan
class ExtractionPlan(BaseModel):
    url: str
    objective: str
    entities: List[EntitySpec]
    # ... (see TASK-653 for full model)
    @classmethod
    def model_json_schema(cls) -> dict: ...  # Pydantic v2 built-in
```

### Does NOT Exist
- ~~`ExtractionPlanGenerator`~~ -- does not exist yet; THIS TASK creates it
- ~~`PlanGenerator.generate_extraction_plan()`~~ -- not a real method
- ~~`WebScrapingToolkit.analyze_page_for_extraction()`~~ -- does not exist
- ~~`_strip_code_fences`~~ as a module-level export -- verify; may be inline in `_parse_response`

---

## Implementation Notes

### Pattern to Follow
```python
# Follow PlanGenerator exactly:
class ExtractionPlanGenerator:
    """Generates ExtractionPlan from HTML content + objective using LLM.

    The LLM client must support ``async def complete(prompt: str) -> str``.
    """

    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client
        self.logger = logging.getLogger(__name__)

    async def generate(
        self,
        url: str,
        objective: str,
        content: str,  # HTML content (cleaned)
        hints: Optional[Dict[str, Any]] = None,
    ) -> ExtractionPlan:
        cleaned = self._clean_html_content(content)
        prompt = self._build_prompt(url, objective, cleaned, hints)
        raw_response = await self._client.complete(prompt)
        return self._parse_response(raw_response, url, objective)
```

### Reconnaissance Prompt Template
The prompt must:
1. Tell the LLM it's a web content analysis expert
2. Include the objective and URL
3. Include the cleaned HTML content (truncated)
4. Include `ExtractionPlan.model_json_schema()` as the target schema
5. Ask for JSON output matching the schema
6. Include rules about entity discovery, field naming, selector generation

### HTML Cleaning Rules
```python
def _clean_html_content(self, html: str, max_tokens: int = 8000) -> str:
    """Clean HTML for LLM input. Preserves structure and CSS classes."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove noise tags
    for tag in soup.find_all(["script", "style", "noscript", "link", "meta"]):
        tag.decompose()
    # Try to extract main content
    main = soup.find("main") or soup.find("article") or soup.find("body")
    # Return HTML string, truncated
    ...
```

### Key Constraints
- Use the **same LLM client** instance (resolved open question)
- LLM client has `async complete(prompt: str) -> str` interface
- JSON response parsing must handle: code fences, trailing commas, partial JSON
- Content format: HTML (not markdown) -- CSS classes needed for accurate selectors
- Truncation: ~8K tokens maximum for content in prompt

---

## Acceptance Criteria

- [ ] `ExtractionPlanGenerator` produces valid `ExtractionPlan` from HTML + objective
- [ ] HTML cleaning strips noise tags, extracts main content, truncates to ~8K tokens
- [ ] CSS class names are preserved in cleaned HTML
- [ ] Code-fenced JSON responses handled correctly
- [ ] Malformed JSON triggers retry or clear error
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_extraction_plan_generator.py -v`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_extraction_plan_generator.py
import pytest
from unittest.mock import AsyncMock
from parrot_tools.scraping.extraction_plan_generator import ExtractionPlanGenerator
from parrot_tools.scraping.extraction_models import ExtractionPlan


@pytest.fixture
def mock_llm():
    client = AsyncMock()
    client.complete = AsyncMock(return_value='```json\n{"url": "https://example.com", "objective": "test", "entities": [{"entity_type": "product", "description": "A product", "fields": [{"name": "title", "description": "Product title", "selector": "h1"}]}]}\n```')
    return client


class TestExtractionPlanGenerator:
    async def test_generate_produces_valid_plan(self, mock_llm):
        gen = ExtractionPlanGenerator(llm_client=mock_llm)
        plan = await gen.generate(
            url="https://example.com",
            objective="Extract products",
            content="<html><body><h1>Product</h1></body></html>",
        )
        assert isinstance(plan, ExtractionPlan)
        assert len(plan.entities) > 0

    def test_clean_html_strips_scripts(self):
        gen = ExtractionPlanGenerator(llm_client=AsyncMock())
        html = "<html><head><script>alert(1)</script><style>.x{}</style></head><body><main><h1>Title</h1></main></body></html>"
        cleaned = gen._clean_html_content(html)
        assert "<script>" not in cleaned
        assert "<style>" not in cleaned
        assert "<h1>" in cleaned

    def test_clean_html_extracts_main(self):
        gen = ExtractionPlanGenerator(llm_client=AsyncMock())
        html = "<html><body><nav>Menu</nav><main><div class='product'>Item</div></main><footer>Legal</footer></body></html>"
        cleaned = gen._clean_html_content(html)
        assert "product" in cleaned  # CSS class preserved
        assert "Menu" not in cleaned or "Legal" not in cleaned  # nav/footer excluded when main exists

    async def test_handles_code_fenced_response(self, mock_llm):
        gen = ExtractionPlanGenerator(llm_client=mock_llm)
        plan = await gen.generate(
            url="https://example.com",
            objective="test",
            content="<html><body>content</body></html>",
        )
        assert plan.url == "https://example.com"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/intelligent-scraping-pipeline.spec.md`
2. **Check dependencies** -- verify TASK-653 is completed
3. **Read `plan_generator.py` in full** -- understand the exact pattern to follow
4. **Verify** that `_strip_code_fences` or equivalent JSON cleaning exists in plan_generator.py
5. **Implement** following the scope and contract
6. **Move to completed**, update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
