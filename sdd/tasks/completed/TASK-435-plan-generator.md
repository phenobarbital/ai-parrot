# TASK-435: LLM Plan Generator

**Feature**: FEAT-014 — WebScrapingToolkit
**Spec**: `sdd/specs/scraping-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-038
**Assigned-to**: claude-session

---

## Context

> This task implements Module 5 from the spec: the `PlanGenerator` class that
> encapsulates LLM-based scraping plan generation. It builds a prompt from a page
> snapshot, calls the LLM client, and parses the JSON response into a `ScrapingPlan`.

---

## Scope

- Implement `PlanGenerator` class with prompt template and response parsing
- `generate()` method: takes URL, objective, hints, page snapshot → returns `ScrapingPlan`
- Prompt template includes URL, objective, hints, page snapshot, and ScrapingPlan JSON schema
- Handle invalid LLM JSON responses gracefully (retry or raise clear error)
- Write unit tests with mock LLM client

**NOT in scope**: Page snapshot extraction (that happens in the toolkit), WebScrapingToolkit (TASK-053)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/plan_generator.py` | CREATE | PlanGenerator class |
| `tests/tools/scraping/test_plan_generator.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
import json
import logging
from typing import Any, Dict, Optional

from .plan import ScrapingPlan

logger = logging.getLogger(__name__)

# See spec §4.1.1 for the full prompt template
PLAN_GENERATION_PROMPT = """You are a web scraping expert. Given the following page snapshot, generate
a scraping plan to achieve the stated objective.

URL: {url}
OBJECTIVE: {objective}
HINTS: {hints}

PAGE SNAPSHOT:
Title: {title}
Text excerpt: {text_excerpt}
Element hints: {element_hints}
Available links: {links}

Respond ONLY with a valid JSON object matching this schema:
{schema_json}

Rules:
- Use CSS selectors unless an XPath is clearly more reliable.
- Prefer data-* attributes and IDs over class names.
- Include a wait step after every navigation.
- If pagination is needed, include a loop action.
- Set browser_config only if non-default settings are required.
"""


class PageSnapshot:
    """Lightweight page data for LLM prompt building."""
    def __init__(self, title: str = "", text_excerpt: str = "",
                 element_hints: str = "", links: str = ""):
        self.title = title
        self.text_excerpt = text_excerpt
        self.element_hints = element_hints
        self.links = links


class PlanGenerator:
    """Generates ScrapingPlan from URL + objective using an LLM client."""

    def __init__(self, llm_client: Any):
        self._client = llm_client
        self.logger = logging.getLogger(__name__)

    async def generate(
        self,
        url: str,
        objective: str,
        snapshot: Optional[PageSnapshot] = None,
        hints: Optional[Dict[str, Any]] = None,
    ) -> ScrapingPlan:
        """Generate a scraping plan via LLM inference."""
        ...

    def _build_prompt(self, url, objective, snapshot, hints) -> str:
        """Build the LLM prompt from inputs."""
        ...

    def _parse_response(self, raw: str, url: str, objective: str) -> ScrapingPlan:
        """Parse LLM JSON response into a ScrapingPlan."""
        ...
```

### Key Constraints
- LLM client only needs `async def complete(prompt: str) -> str` interface
- Inject `ScrapingPlan.model_json_schema()` into the prompt for structured output
- Parse JSON response, handling common LLM quirks (markdown code fences, extra text)
- On parse failure, raise `ValueError` with the raw response for debugging
- Do NOT retry LLM calls — that's the toolkit's responsibility
- Page snapshot is optional (caller provides it); if missing, use empty values

### References in Codebase
- `parrot/tools/scraping/plan.py` — `ScrapingPlan` model and its JSON schema
- `parrot/clients/abstract_client.py` — `AbstractClient` interface pattern
- `parrot/tools/scraping/tool.py` — existing plan generation logic to reference

---

## Acceptance Criteria

- [ ] `PlanGenerator.generate()` produces a valid `ScrapingPlan` from mock LLM response
- [ ] Prompt includes URL, objective, hints, snapshot, and ScrapingPlan JSON schema
- [ ] Response parsing handles JSON wrapped in markdown code fences
- [ ] Invalid JSON raises `ValueError` with raw response included
- [ ] Works with any LLM client that has `async def complete(prompt) -> str`
- [ ] All tests pass: `pytest tests/tools/scraping/test_plan_generator.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/plan_generator.py`
- [ ] Import works: `from parrot.tools.scraping.plan_generator import PlanGenerator`

---

## Test Specification

```python
# tests/tools/scraping/test_plan_generator.py
import json
import pytest
from unittest.mock import AsyncMock
from parrot.tools.scraping.plan_generator import PlanGenerator, PageSnapshot
from parrot.tools.scraping.plan import ScrapingPlan


@pytest.fixture
def valid_plan_json():
    return json.dumps({
        "url": "https://example.com/products",
        "objective": "Extract products",
        "steps": [
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".products", "condition_type": "selector"},
        ],
    })


@pytest.fixture
def mock_client(valid_plan_json):
    client = AsyncMock()
    client.complete = AsyncMock(return_value=valid_plan_json)
    return client


class TestPlanGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_plan(self, mock_client):
        gen = PlanGenerator(mock_client)
        plan = await gen.generate("https://example.com/products", "Extract products")
        assert isinstance(plan, ScrapingPlan)
        assert plan.url == "https://example.com/products"

    @pytest.mark.asyncio
    async def test_prompt_includes_schema(self, mock_client):
        gen = PlanGenerator(mock_client)
        await gen.generate("https://example.com", "test")
        prompt = mock_client.complete.call_args[0][0]
        assert "properties" in prompt  # JSON schema present

    @pytest.mark.asyncio
    async def test_handles_markdown_code_fence(self, mock_client, valid_plan_json):
        mock_client.complete.return_value = f"```json\n{valid_plan_json}\n```"
        gen = PlanGenerator(mock_client)
        plan = await gen.generate("https://example.com/products", "Extract products")
        assert isinstance(plan, ScrapingPlan)

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self, mock_client):
        mock_client.complete.return_value = "This is not JSON at all"
        gen = PlanGenerator(mock_client)
        with pytest.raises(ValueError):
            await gen.generate("https://example.com", "test")

    def test_prompt_includes_url_and_objective(self, mock_client):
        gen = PlanGenerator(mock_client)
        prompt = gen._build_prompt(
            "https://example.com", "Extract data",
            PageSnapshot(title="Example"), None
        )
        assert "https://example.com" in prompt
        assert "Extract data" in prompt
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-toolkit.spec.md` §4.1 and §4.1.1
2. **Check dependencies** — verify TASK-038 is in `sdd/tasks/completed/`
3. **Read** `parrot/tools/scraping/plan.py` — understand ScrapingPlan model
4. **Read** `parrot/tools/scraping/tool.py` — reference existing plan generation logic
5. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-435-plan-generator.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `PlanGenerator` class in `parrot/tools/scraping/plan_generator.py` with `generate()`, `_build_prompt()`, and `_parse_response()` methods. Also implemented `PageSnapshot` data class and two helper functions: `_strip_code_fences()` for handling markdown-wrapped LLM responses, and `_extract_json_object()` for finding JSON in mixed text. The prompt template injects the ScrapingPlan JSON schema for structured output. Response parsing handles code fences, extra text around JSON, missing url/objective fields (filled from caller args), and raises `ValueError` with diagnostic info on failures. 21 unit tests pass.

**Deviations from spec**: none
