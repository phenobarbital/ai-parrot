---
id: F009
query_id: Q005
type: git_log
intent: Understand recent development activity and test coverage
executed_at: 2026-06-04T00:00:00Z
duration_ms: 53520
parent_id: null
depth: 0
---

# F009 — Active development (20 commits/60d); 43 test files; no existing template/flow patterns

## Summary

20 commits in 60 days. Recent focus: JSON-LD extraction (FEAT-154), driver parity, executor refinements. Earlier: ExtractionPlanRegistry, BasePlanRegistry generics, RecallProcessor, pre-built plans. 43 test files under `packages/ai-parrot-tools/tests/scraping/`. Key test areas: drivers (7 files), extraction/planning (9 files), execution (6 files), crawling (5 files). grep for "template|Template|flow|Flow|ParamSpec" in scraping source found NO existing patterns beyond the Loop action's template vars.

## Citations

- path: `packages/ai-parrot-tools/tests/scraping/`
  lines: N/A
  symbol: (directory)
  excerpt: |
    43 test files total:
    - test_executor.py (16KB), test_plan_model.py (6.4KB), test_plan_registry.py (5.5KB)
    - test_base_registry.py (11KB), test_extraction_registry.py (7.5KB)
    - test_crawler.py (6.5KB), test_crawl_strategy.py (4.2KB)
    - test_playwright_driver.py (18.9KB), test_driver_factory.py
    - test_toolkit.py (20.5KB), test_toolkit_integration.py (20.2KB)

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/`
  lines: N/A
  symbol: (grep result)
  excerpt: |
    grep -r "template|Template|flow|Flow|ParamSpec" → NO matches outside Loop action context

## Notes

No existing TemplatePlan/ScrapingFlow/FlowExecutor code — all three are net-new. The test infrastructure is mature (43 files), so new code should follow the existing test patterns (pytest with mocks for drivers, async tests).
