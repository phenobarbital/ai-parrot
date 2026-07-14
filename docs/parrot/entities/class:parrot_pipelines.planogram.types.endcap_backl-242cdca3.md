---
type: Wiki Entity
title: EndcapBacklitMultitier
id: class:parrot_pipelines.planogram.types.endcap_backlit_multitier.EndcapBacklitMultitier
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Planogram type for backlit multi-tier endcap displays.
relates_to:
- concept: class:parrot_pipelines.planogram.types.abstract.AbstractPlanogramType
  rel: extends
---

# EndcapBacklitMultitier

Defined in [`parrot_pipelines.planogram.types.endcap_backlit_multitier`](../summaries/mod:parrot_pipelines.planogram.types.endcap_backlit-f08fa3da.md).

```python
class EndcapBacklitMultitier(AbstractPlanogramType)
```

Planogram type for backlit multi-tier endcap displays.

Validates compliance for a display that combines:
- A retro-illuminated header panel (backlit lightbox).
- One or more product shelves, each optionally sub-divided into named
  ``ShelfSection`` regions that are detected IN PARALLEL via
  ``asyncio.gather()``.

For shelves with ``sections`` defined, one LLM detection call is launched
per section concurrently.  Flat shelves (``sections=None``) use a single
full-shelf LLM call.  Section-local bounding boxes are remapped to
full-image normalized coordinates before being stored on each
``IdentifiedProduct``.

Args:
    pipeline: Parent PlanogramCompliance instance providing shared
        utilities (LLM clients, image helpers, config).
    config: The PlanogramConfig for this compliance run.

## Methods

- `async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Any], Optional[Any], Optional[Any], Optional[Any], List[Any]]` — Detect endcap ROI, promotional graphic, and brand logo via LLM.
- `async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]` — Detect structural zones (backlit panel, logo area) within the ROI.
- `async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]` — Detect products per shelf using parallel section detection when configured.
- `def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]` — Score compliance per shelf by comparing detected vs. expected products.
