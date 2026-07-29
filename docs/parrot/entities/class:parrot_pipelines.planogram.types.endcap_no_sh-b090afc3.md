---
type: Wiki Entity
title: EndcapNoShelvesPromotional
id: class:parrot_pipelines.planogram.types.endcap_no_shelves_promotional.EndcapNoShelvesPromotional
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Planogram type for shelf-less promotional endcap displays.
relates_to:
- concept: class:parrot_pipelines.planogram.types.abstract.AbstractPlanogramType
  rel: extends
---

# EndcapNoShelvesPromotional

Defined in [`parrot_pipelines.planogram.types.endcap_no_shelves_promotional`](../summaries/mod:parrot_pipelines.planogram.types.endcap_no_shel-f74e2433.md).

```python
class EndcapNoShelvesPromotional(AbstractPlanogramType)
```

Planogram type for shelf-less promotional endcap displays.

Validates compliance for a display consisting of:
- A retro-illuminated upper panel (backlit_panel) showing brand / promo graphics.
- A lower poster (lower_poster) showing promotional content.

There are no physical products.  Compliance is scored by zone presence
and illumination state of the backlit panel.

Args:
    pipeline: Parent PlanogramCompliance instance providing shared
        utilities (LLM clients, image helpers, config).
    config: The PlanogramConfig for this compliance run.

## Methods

- `async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[Any], Optional[Any], Optional[Any], List[Any]]` — Compute the region of interest by locating the promotional endcap.
- `async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]` — Detect the backlit panel and lower poster zones within the endcap ROI.
- `async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]` — Detect zone presence and illumination state from config-defined zones.
- `def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]` — Score compliance per config-defined zone.
