---
type: Wiki Entity
title: ProductCounter
id: class:parrot_pipelines.planogram.types.product_counter.ProductCounter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Planogram type for product-on-counter/podium displays.
relates_to:
- concept: class:parrot_pipelines.planogram.types.abstract.AbstractPlanogramType
  rel: extends
---

# ProductCounter

Defined in [`parrot_pipelines.planogram.types.product_counter`](../summaries/mod:parrot_pipelines.planogram.types.product_counter.md).

```python
class ProductCounter(AbstractPlanogramType)
```

Planogram type for product-on-counter/podium displays.

Validates compliance for a display consisting of:
- A single main product on a counter or podium.
- A promotional background (backdrop or side panel).
- An information label (price tag, spec card, or similar).

Compliance is scored by element presence with configurable weights.
Missing elements are penalised; a missing information label reduces the
score but does not zero it.

Args:
    pipeline: Parent PlanogramCompliance instance providing shared
        utilities (LLM clients, image helpers, config).
    config: The PlanogramConfig for this compliance run.

## Methods

- `async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[Any], Optional[Any], Optional[Any], List[Any]]` — Compute the region of interest by finding the counter/podium area.
- `async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]` — Detect macro elements within the counter ROI.
- `async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]` — Map detected macro elements to IdentifiedProduct instances.
- `def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]` — Score compliance based on the presence of expected counter elements.
