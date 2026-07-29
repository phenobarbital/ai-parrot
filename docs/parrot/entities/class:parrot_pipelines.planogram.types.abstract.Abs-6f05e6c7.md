---
type: Wiki Entity
title: AbstractPlanogramType
id: class:parrot_pipelines.planogram.types.abstract.AbstractPlanogramType
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Contract for planogram type composables.
---

# AbstractPlanogramType

Defined in [`parrot_pipelines.planogram.types.abstract`](../summaries/mod:parrot_pipelines.planogram.types.abstract.md).

```python
class AbstractPlanogramType(ABC)
```

Contract for planogram type composables.

Each composable receives a reference to the parent PlanogramCompliance
pipeline for access to shared utilities (LLM, image helpers, config).

Concrete implementations handle the type-specific logic for:
- ROI computation (how to find the region of interest)
- Macro object detection (poster, logo, backlit, etc.)
- Product detection and identification
- Planogram compliance checking

Args:
    pipeline: Parent PlanogramCompliance instance providing shared
        utilities (LLM clients, image processing, config).
    config: The PlanogramConfig for this compliance run.

## Methods

- `async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[Any], Optional[Any], Optional[Any], List[Any]]` — Compute the region of interest for this planogram type.
- `async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]` — Detect macro objects within the ROI.
- `async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]` — Detect and identify all products within the ROI.
- `def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]` — Compare detected products against the expected planogram.
- `def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]` — Return color scheme for rendering compliance overlays.
- `def get_grid_strategy(self) -> 'AbstractGridStrategy'` — Return the grid decomposition strategy for this planogram type.
