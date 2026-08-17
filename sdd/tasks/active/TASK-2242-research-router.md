# TASK-2242: ResearchRouter — cross-category dispatch tool

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2237, TASK-2241
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Unlike the toolkits, this is a standalone `AbstractTool`,
which means two framework rules bite here and **both were live defects caught
in spec review** — read them carefully:

1. `AbstractTool` does **not** infer an args schema from `_execute`. Without an
   explicit `args_schema`, the framework **silently discards every parameter**
   and `_execute` runs on defaults. Empirically confirmed: a router without a
   schema received `{'query': 'MISSING', 'max_results': -1}`.
2. Tools have **no back-reference to the calling agent's LLM** — this is a
   documented framework invariant (`abstract.py:265`). The classifier client
   must be injected through the constructor.

---

## Scope

- Create `parrot_tools/research/router.py`.
- Implement `ResearchRouterArgs(AbstractToolArgsSchema)` with `query`,
  `categories`, `max_results`.
- Implement `ResearchRouter(AbstractTool)` with `name`, `description`,
  `args_schema`, and a constructor taking `open_data`, `academic`, and `llm`.
- LLM-based category classification with a **keyword-heuristic fallback** when
  `llm is None` or classification fails.
- Concurrent dispatch to the selected toolkits; merge results; return a
  **successful** `ToolResult` even on partial failure.
- Unit tests, including the parameter-delivery regression test.

**NOT in scope**: toolkit internals, exports / `TOOL_REGISTRY` (TASK-2243),
documentation (TASK-2244).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/research/router.py` | CREATE | `ResearchRouterArgs` + `ResearchRouter` |
| `packages/ai-parrot-tools/tests/research/test_router.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Dict, List, Optional, Type, Union
from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.clients.base import AbstractClient       # verified: db.py:29
from parrot.clients.factory import LLMFactory        # verified: db.py:30

from parrot_tools.research.models import ResearchResult
from parrot_tools.research.open_data import OpenDataToolkit          # TASK-2235-2237
from parrot_tools.research.academic import AcademicResearchToolkit   # TASK-2238-2241
import asyncio
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool:
    name: str
    description: str
    args_schema: Type[BaseModel] = AbstractToolArgsSchema   # line ~249
    async def execute(self, *args, **kwargs) -> ToolResult  # line 778
    async def _execute(self, **kwargs) -> Any               # subclass implements
    # line 265 (comment): "tools have no bot back-reference by design"
    # line 629 — THE TRAP:
    #   if not self.args_schema or self.args_schema == AbstractToolArgsSchema:
    #       return AbstractToolArgsSchema()      ← ALL kwargs DISCARDED

class ToolResult(BaseModel):        # line 199
    success: bool = True            # line 201 — independent of `status`
    status: str = "success"         # line 202
    result: Any                     # line 203
    error: Optional[str] = None     # line 204
    metadata: Dict[str, Any] = {}   # line 205

# packages/ai-parrot/src/parrot/tools/manager.py
#   line 1594:  if result.status == "error":
#   line 1614:      raise ValueError(result.error)   ← RAISES into the agent loop

# packages/ai-parrot-tools/src/parrot_tools/db.py — the LLM-injection pattern
    llm: Optional[Union[AbstractClient, str]] = None            # line 177
    self.llm = LLMFactory.create(llm) if isinstance(llm, str) else llm   # 196-199
    response = await self.llm.ask(prompt)                       # line 826
```

### Verified Framework Behaviour **[probe]**

```text
WITH explicit args_schema:
  execute(query="renewables", categories=["open_data"], max_results=3)
  -> _execute receives {'query':'renewables','categories':['open_data'],'max_results':3}

WITHOUT args_schema (the defect this task must avoid):
  execute(query="renewables", max_results=3)
  -> _execute receives {'query':'MISSING','max_results':-1}    ← params dropped
```

### Does NOT Exist

- ~~Automatic `args_schema` inference from `_execute`~~ — **does not happen**
  for `AbstractTool`. (`ToolkitTool` infers from method signatures — that is
  why the toolkits need no schema, and why this class does.)
- ~~`self.bot` / `self.agent` / `self.client` on a tool~~ — no bot
  back-reference exists by design (`abstract.py:265`)
- ~~Returning `ToolResult(status="error")` as a safe error path~~ — it makes
  `ToolManager` raise (`manager.py:1614`)
- ~~`ToolResult(status="error")` implying `success=False`~~ — it does not
- ~~`MarketResearchToolkit` / a `market` category~~ — **dropped from v1**;
  valid categories are exactly `open_data` and `academic`

---

## Implementation Notes

### The schema is mandatory

```python
class ResearchRouterArgs(AbstractToolArgsSchema):
    query: str = Field(description="Natural-language research question")
    categories: Optional[List[str]] = Field(
        default=None, description="Restrict to: open_data, academic")
    max_results: int = Field(default=10, ge=1, le=50)


class ResearchRouter(AbstractTool):
    name: str = "research"
    description: str = (
        "Answer a research question using authoritative sources: World Bank, "
        "EU Open Data, OECD (economic/statistical indicators) and Crossref, "
        "PubMed, Semantic Scholar, arXiv (academic literature). Returns "
        "structured results with citations."
    )
    args_schema: Type[BaseModel] = ResearchRouterArgs
```

### Constructor injection

```python
def __init__(self, open_data=None, academic=None, llm=None, **kwargs):
    super().__init__(**kwargs)
    self.open_data = open_data or OpenDataToolkit()
    self.academic = academic or AcademicResearchToolkit()
    self.llm = LLMFactory.create(llm) if isinstance(llm, str) else llm
```
`llm=None` is a supported mode — the router then uses heuristics only. Do not
attempt to discover an LLM from the calling agent.

### Classification

Keep the prompt small and provider-neutral; ask for a JSON array of category
names and parse defensively. Any failure (no LLM, malformed output, transport
error) falls back to keyword heuristics — e.g. indicator/GDP/population/
country/statistics terms → `open_data`; paper/study/DOI/author/journal terms →
`academic`; ambiguous → **both**.

Explicit `categories` short-circuits classification entirely (no LLM call).
Validate against `{"open_data", "academic"}` and report unknown values.

### Dispatch and merge

Run the selected toolkit calls concurrently with
`asyncio.gather(..., return_exceptions=True)`. For each category record either
its `ResearchResult` payload or a failure entry. **A raised exception from one
toolkit must not fail the router** — capture it and continue.

### Return shape — must stay successful

```python
return ToolResult(
    success=True, status="success",
    result={"query": query, "categories": selected,
            "classification": "llm" | "heuristic" | "explicit",
            "results": {...}, "failures": {...}},
    metadata={"max_results": max_results},
)
```
Only a genuinely unrecoverable condition may use
`ToolResult(success=False, status="error", ...)` — and then `success=False`
must be passed explicitly.

### Key Constraints

- Async throughout; `self.logger` at classification and dispatch boundaries.
- Google-style docstrings; the class `description` is what the LLM reads.
- No new external dependencies.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/db.py:177,196-199,826` — LLM injection + `ask()`
- `packages/ai-parrot-tools/src/parrot_tools/arxiv_tool.py:59` — an `AbstractTool`
  that correctly declares `args_schema`

---

## Acceptance Criteria

- [ ] `ResearchRouter` declares `name`, `description` **and** an explicit
      `args_schema`.
- [ ] **Regression test**: `await ResearchRouter().execute(query="x",
      categories=["academic"], max_results=3)` delivers all three values into
      `_execute` — no defaults, no dropped params.
- [ ] Constructor accepts `llm` as an `AbstractClient` instance **or** a string
      resolved via `LLMFactory.create()`.
- [ ] With `llm=None` the router classifies heuristically and still returns
      results — no crash, no LLM call attempted.
- [ ] The router never reads a bot/agent back-reference.
- [ ] Explicit `categories` bypasses classification entirely (no LLM call) —
      asserted by test.
- [ ] Invalid category value is reported in the payload, listing valid options.
- [ ] One toolkit raising still yields `ToolResult.success is True` and
      `status == "success"`, with the failure recorded in the payload.
- [ ] Any `ToolResult` built with `status="error"` also passes `success=False`.
- [ ] Dispatch to multiple categories runs concurrently (`asyncio.gather`).
- [ ] `pytest packages/ai-parrot-tools/tests/research/test_router.py -v` passes offline.
- [ ] `ruff check` clean.

---

## Test Specification

```python
import pytest
from parrot_tools.research.router import ResearchRouter, ResearchRouterArgs


class TestResearchRouter:
    async def test_params_reach_execute(self, stub_toolkits):
        """REGRESSION — without an explicit args_schema these are dropped."""
        r = await ResearchRouter(**stub_toolkits).execute(
            query="renewables", categories=["open_data"], max_results=3)
        assert r.result["query"] == "renewables"
        assert r.result["categories"] == ["open_data"]
        assert r.metadata["max_results"] == 3

    async def test_heuristic_fallback_without_llm(self, stub_toolkits):
        r = await ResearchRouter(**stub_toolkits, llm=None).execute(query="GDP of Brazil")
        assert r.success is True
        assert r.result["classification"] == "heuristic"

    async def test_explicit_categories_skip_llm(self, stub_toolkits, spy_llm):
        await ResearchRouter(**stub_toolkits, llm=spy_llm).execute(
            query="x", categories=["academic"])
        assert spy_llm.called is False

    async def test_llm_classification_used(self, stub_toolkits, fake_llm_returns_academic):
        r = await ResearchRouter(**stub_toolkits, llm=fake_llm_returns_academic).execute(
            query="recent papers on CRISPR")
        assert r.result["categories"] == ["academic"]
        assert r.result["classification"] == "llm"

    async def test_malformed_llm_output_falls_back(self, stub_toolkits, fake_llm_garbage):
        r = await ResearchRouter(**stub_toolkits, llm=fake_llm_garbage).execute(query="x")
        assert r.success is True and r.result["classification"] == "heuristic"

    async def test_partial_failure_still_successful(self, stub_toolkits_one_raising):
        r = await ResearchRouter(**stub_toolkits_one_raising).execute(
            query="x", categories=["open_data", "academic"])
        assert r.success is True and r.status == "success"
        assert r.result["failures"]

    async def test_invalid_category_reported(self, stub_toolkits):
        r = await ResearchRouter(**stub_toolkits).execute(query="x", categories=["bogus"])
        assert "bogus" in str(r.result)

    def test_no_bot_backreference(self):
        router = ResearchRouter()
        assert not any(hasattr(router, a) for a in ("bot", "agent", "_bot"))
```

---

## Agent Instructions

1. **Read the spec** — §2 Error Contract and §2 New Public Interfaces
   (`ResearchRouterArgs`), plus §9 Review Log items B1, B2, B3, B4.
2. **Check** TASK-2237 and TASK-2241 are both in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `abstract.py:629` before writing
   the class; the args-schema trap is the single most important detail here.
4. Update the index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
