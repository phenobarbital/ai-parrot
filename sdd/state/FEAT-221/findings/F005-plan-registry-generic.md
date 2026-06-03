---
id: F005
query_id: Q003
type: read
intent: Understand PlanRegistry storage model and extensibility for templates/flows
executed_at: 2026-06-04T00:00:00Z
duration_ms: 50946
parent_id: null
depth: 0
---

# F005 — BasePlanRegistry[T] is generic; ExtractionPlanRegistry demonstrates the extension pattern

## Summary

`PlanRegistry` (registry.py:20-61) extends `BasePlanRegistry[ScrapingPlan]`. The base class (base_registry.py) is generic over plan type T, keyed by fingerprint (16-char SHA-256), with 3-tier lookup (exact fingerprint → path-prefix → domain fallback). `ExtractionPlanRegistry` (extraction_registry.py) demonstrates the extension pattern: separate index file (`extraction_registry.json`), per-fingerprint JSON file storage, failure tracking, and pre-built plan loading. All mutations guarded by `asyncio.Lock`. Persistence via aiofiles JSON write.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/registry.py`
  lines: 20-61
  symbol: `PlanRegistry`
  excerpt: |
    class PlanRegistry(BasePlanRegistry[ScrapingPlan]):
        def __init__(self, plans_dir=None):
            super().__init__(plans_dir=plans_dir, index_filename="registry.json")

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/base_registry.py`
  lines: 93-149
  symbol: `BasePlanRegistry.lookup`
  excerpt: |
    def lookup(self, url, *, allow_domain_fallback=True) -> Optional[PlanRegistryEntry]:
        fingerprint = _compute_fingerprint(_normalize_url(url))
        if fingerprint in self._entries: return self._entries[fingerprint]
        # tier 2: path-prefix, tier 3: domain fallback

- path: `packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_registry.py`
  lines: 1-251
  symbol: `ExtractionPlanRegistry`
  excerpt: |
    class ExtractionPlanRegistry(BasePlanRegistry[ExtractionPlan]):
        # Separate index, per-fingerprint file storage, failure tracking

## Notes

For FEAT-221, the recommended pattern is: create a `TemplatePlanRegistry(BasePlanRegistry[TemplatePlan])` with `index_filename="template_registry.json"`. Flow checkpoints could be a separate registry or a simple JSON file per flow execution run. The fingerprint scheme needs adjustment for templates: `template_name + param_hash` instead of URL-only.
