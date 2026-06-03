---
id: F008
query_id: Q004
type: read
intent: Map public exports from scraping __init__.py
executed_at: 2026-06-04T00:00:00Z
duration_ms: 52786
parent_id: null
depth: 0
---

# F008 — __init__.py exports 29 symbols; new types will need addition

## Summary

`__init__.py` (lines 1-69) exports 29 symbols in `__all__`. Categories: legacy tools (WebScrapingTool), toolkit (WebScrapingToolkit, DriverConfig), plan/registry (ScrapingPlan, PlanRegistry), crawl (CrawlEngine, CrawlResult, strategies), drivers (DriverFactory, AbstractDriver, PlaywrightDriver, SeleniumDriver, PlaywrightConfig), extraction (ExtractionPlan, ExtractedEntity, ExtractionResult, EntityFieldSpec, EntitySpec), registries (BasePlanRegistry, ExtractionPlanRegistry), generators (ExtractionPlanGenerator, RecallProcessor). Note: `EntitySpec` is imported but missing from `__all__`.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/__init__.py`
  lines: 1-69
  symbol: `__all__`
  excerpt: |
    __all__ = [
        "WebScrapingTool", "WebScrapingToolArgs", "ScrapingResult",
        "WebScrapingToolkit", "DriverConfig", "PlanSummary", "PlanSaveResult",
        "ScrapingPlan", "PlanRegistry",
        "CrawlEngine", "CrawlResult", "CrawlNode", "BFSStrategy", "DFSStrategy", "CrawlStrategy", "LinkDiscoverer", "normalize_url",
        "DriverFactory", "AbstractDriver", "PlaywrightConfig", "PlaywrightDriver", "SeleniumDriver",
        "EntityFieldSpec", "EntitySpec", "ExtractionPlan", "ExtractedEntity", "ExtractionResult",
        "BasePlanRegistry", "ExtractionPlanRegistry",
        "ExtractionPlanGenerator", "RecallProcessor",
    ]

## Notes

New exports needed for FEAT-222: TemplatePlan, ParamSpec, ScrapingFlow, FlowNode, FlowExecutor, FlowResult, and potentially TemplatePlanRegistry.
