---
id: F011
query_id: Q011
type: read
intent: Understand WebScrapingToolkit vs legacy WebScrapingTool and Loop/Conditional dispatch paths
executed_at: 2026-06-04T00:15:00Z
duration_ms: 45000
parent_id: F001
depth: 1
---

# F011 — WebScrapingToolkit delegates to execute_plan_steps which stubs Loop/Conditional; legacy WebScrapingTool has full implementations

## Summary

`WebScrapingToolkit` (toolkit.py:274-942) is the modern tool with LLM plan generation, caching, and refinement. Its `scrape()` method (line 698) delegates ALL step execution to `execute_plan_steps()`. Since the executor stubs Loop/Conditional (F001), **WebScrapingToolkit already cannot execute Loop/Conditional steps** — this is an existing gap, not just a FlowExecutor concern.

The full Loop/Conditional implementations live ONLY in the legacy `WebScrapingTool` (tool.py):
- `_exec_loop()` at tool.py:2582-2664
- `_exec_conditional()` at tool.py:2456-2580
- `_substitute_template_vars()` at tool.py:3271-3338

Extracting these into a reusable module fixes THREE consumers at once: WebScrapingToolkit (existing gap), FlowExecutor (new), and the executor standalone path.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py`
  lines: 274-942
  symbol: `WebScrapingToolkit`
  excerpt: |
    class WebScrapingToolkit(AbstractToolkit):
        # scrape() delegates to execute_plan_steps()
        # No Loop/Conditional handling

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py`
  lines: 698-708
  symbol: `WebScrapingToolkit.scrape`
  excerpt: |
    async def scrape(self, url, plan=None, objective=None, steps=None,
                     selectors=None, save_plan=False, browser_config_override=None,
                     max_refinement_attempts=1) -> ScrapingResult:

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py`
  lines: 2582-2664
  symbol: `WebScrapingTool._exec_loop`

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py`
  lines: 2456-2580
  symbol: `WebScrapingTool._exec_conditional`

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py`
  lines: 3271-3338
  symbol: `WebScrapingTool._substitute_template_vars`

## Notes

The extraction resolves an existing limitation in WebScrapingToolkit and prevents the legacy tool from being the only path for advanced actions. The extracted module becomes a shared dependency for all execution paths.
