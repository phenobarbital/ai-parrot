# TASK-048: WebScrapingToolkit Crawl Integration

**Feature**: FEAT-013 — CrawlEngine
**Spec**: `sdd/specs/scrapingplan-crawlengine.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-047, TASK-038
**Assigned-to**: unassigned

---

## Context

This task wires the `CrawlEngine` into the existing `WebScrapingTool` / scraping
toolkit, adding a public `crawl()` method. This is the user-facing integration
point — agents and users call `crawl()` instead of constructing the engine directly.

Implements spec Module 6.

---

## Scope

- Add `crawl()` method to `WebScrapingTool` (or a new toolkit wrapper):
  - Accepts `start_url`, `plan` (or generates one), `depth`, `max_pages`, `strategy`
  - Instantiates `CrawlEngine` with the tool's `scrape_fn`
  - Returns `CrawlResult`
- Update `parrot/tools/scraping/__init__.py` to export:
  - `CrawlEngine`, `CrawlResult`, `CrawlNode`
  - `BFSStrategy`, `DFSStrategy`
  - `LinkDiscoverer`
  - `normalize_url`
- Write integration tests

**NOT in scope**: Modifying the single-page scrape flow, plan registry integration (FEAT-012).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/tool.py` | MODIFY | Add `crawl()` method |
| `parrot/tools/scraping/__init__.py` | MODIFY | Export new components |
| `tests/tools/scraping/test_crawl_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### Pattern to Follow
```python
# In WebScrapingTool or as a mixin
async def crawl(
    self,
    start_url: str,
    plan: Optional[ScrapingPlan] = None,
    depth: int = 1,
    max_pages: Optional[int] = None,
    strategy: Optional[CrawlStrategy] = None,
) -> CrawlResult:
    """Multi-page crawl starting from start_url."""
    engine = CrawlEngine(
        scrape_fn=self._scrape_single_page,
        strategy=strategy,
        follow_selector=plan.follow_selector if plan else "a[href]",
        follow_pattern=plan.follow_pattern if plan else None,
        concurrency=1,
        logger=self.logger,
    )
    return await engine.run(start_url, plan, depth=depth, max_pages=max_pages)
```

### Key Constraints
- Must not break existing `WebScrapingTool` public API
- The `scrape_fn` passed to the engine must wrap the existing single-page scrape logic
- Default strategy is BFS with `concurrency=1` (safe for Selenium)

### References in Codebase
- `parrot/tools/scraping/tool.py` — existing `WebScrapingTool` class
- `parrot/tools/scraping/crawler.py` (TASK-047) — `CrawlEngine`
- `parrot/tools/scraping/__init__.py` — current exports

---

## Acceptance Criteria

- [ ] `WebScrapingTool` has a `crawl()` method that returns `CrawlResult`
- [ ] `__init__.py` exports all new public components
- [ ] Existing single-page scrape API unchanged
- [ ] Integration test verifies end-to-end crawl with mocked browser
- [ ] All tests pass: `pytest tests/tools/scraping/test_crawl_integration.py -v`

---

## Test Specification

```python
# tests/tools/scraping/test_crawl_integration.py
import pytest
from parrot.tools.scraping import CrawlEngine, CrawlResult
from parrot.tools.scraping.crawl_strategy import BFSStrategy, DFSStrategy
from parrot.tools.scraping.link_discoverer import LinkDiscoverer
from parrot.tools.scraping.url_utils import normalize_url


class TestImports:
    def test_crawl_engine_importable(self):
        assert CrawlEngine is not None

    def test_crawl_result_importable(self):
        assert CrawlResult is not None

    def test_strategies_importable(self):
        assert BFSStrategy is not None
        assert DFSStrategy is not None

    def test_link_discoverer_importable(self):
        assert LinkDiscoverer is not None

    def test_normalize_url_importable(self):
        assert normalize_url is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-crawlengine.spec.md` for full context
2. **Check dependencies** — verify TASK-047 and TASK-038 are in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-048-crawl-integration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Added `crawl()` method to `WebScrapingTool` that instantiates a `CrawlEngine` with a `_scrape_single` closure wrapping the tool's browser navigation + `_extract_full_content()`. Added `_NullPlan` sentinel for when no plan is provided. Updated `__init__.py` to export `CrawlEngine`, `CrawlResult`, `CrawlNode`, `BFSStrategy`, `DFSStrategy`, `CrawlStrategy`, `LinkDiscoverer`, and `normalize_url`. 16 integration tests covering imports, BFS/DFS crawls, plan hints, pattern filtering, concurrent mode, and max_pages. All 148 tests in `tests/tools/scraping/` pass with no regressions.

**Deviations from spec**: none
