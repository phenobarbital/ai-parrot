---
id: F007
query_id: Q004
type: read
intent: Understand ExtractionPlan.to_scraping_plan() as the pattern to imitate in TemplatePlan.bind()
executed_at: 2026-06-04T00:00:00Z
duration_ms: 52786
parent_id: null
depth: 0
---

# F007 — ExtractionPlan.to_scraping_plan() transforms entity specs into steps + selectors

## Summary

`ExtractionPlan.to_scraping_plan()` (extraction_models.py:127-168) translates an entity-centric schema into an executable ScrapingPlan by: (1) creating `navigate` + `wait` steps, (2) deriving selector entries from EntityFieldSpec fields that have CSS selectors, (3) composing with container_selector if available, (4) returning a ScrapingPlan with `source="extraction_plan"`. This is the translation pattern TemplatePlan.bind() should follow.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py`
  lines: 127-168
  symbol: `ExtractionPlan.to_scraping_plan`
  excerpt: |
    def to_scraping_plan(self) -> ScrapingPlan:
        steps = [
            {"action": "navigate", "url": self.url},
            {"action": "wait", "condition": "body", "condition_type": "selector"},
        ]
        selectors = []
        for entity in self.entities:
            for field in entity.fields:
                if field.selector:
                    sel = f"{entity.container_selector} {field.selector}" if entity.container_selector else field.selector
                    selectors.append({...})
        return ScrapingPlan(name=self.name, url=self.url, objective=self.objective, steps=steps, selectors=selectors, source="extraction_plan")

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py`
  lines: 193-220
  symbol: `ExtractionResult`
  excerpt: |
    class ExtractionResult(BaseModel):
        url: str
        objective: str
        entities: List[ExtractedEntity]
        plan_used: ExtractionPlan
        success: bool = True
        error_message: Optional[str] = None
        elapsed_seconds: float = 0.0

## Notes

TemplatePlan.bind() follows this pattern: receive parameters, render placeholders in url_template/objective_template/steps_template, and produce a ScrapingPlan. The key difference is bind() also needs to produce a unique fingerprint incorporating param values.
