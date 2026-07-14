---
type: Wiki Entity
title: ProductOnShelves
id: class:parrot_pipelines.planogram.types.product_on_shelves.ProductOnShelves
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Planogram type for product-on-shelves displays.
relates_to:
- concept: class:parrot_pipelines.planogram.types.abstract.AbstractPlanogramType
  rel: extends
---

# ProductOnShelves

Defined in [`parrot_pipelines.planogram.types.product_on_shelves`](../summaries/mod:parrot_pipelines.planogram.types.product_on_shelves.md).

```python
class ProductOnShelves(AbstractPlanogramType)
```

Planogram type for product-on-shelves displays.

Implements ROI detection via poster/endcap finding, product detection,
and compliance checking for displays with a header panel and shelved
products below.

Args:
    pipeline: Parent PlanogramCompliance instance.
    config: The PlanogramConfig for this compliance run.

## Methods

- `async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[Any], Optional[Any], Optional[Any], List[Any]]` — Compute the region of interest by finding the poster/endcap.
- `async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]` — Detect macro objects within the ROI.
- `def get_grid_strategy(self) -> AbstractGridStrategy` — Return the appropriate grid strategy for this planogram type.
- `async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]` — Detect and identify all products within the ROI.
- `def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]` — Check compliance of identified products against the planogram.
