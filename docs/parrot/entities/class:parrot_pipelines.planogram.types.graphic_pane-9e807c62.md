---
type: Wiki Entity
title: GraphicPanelDisplay
id: class:parrot_pipelines.planogram.types.graphic_panel_display.GraphicPanelDisplay
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Composable type for graphic-panel / signage endcap compliance.
relates_to:
- concept: class:parrot_pipelines.planogram.types.abstract.AbstractPlanogramType
  rel: extends
---

# GraphicPanelDisplay

Defined in [`parrot_pipelines.planogram.types.graphic_panel_display`](../summaries/mod:parrot_pipelines.planogram.types.graphic_panel_display.md).

```python
class GraphicPanelDisplay(AbstractPlanogramType)
```

Composable type for graphic-panel / signage endcap compliance.

Handles displays where compliance is based on the presence, text
content, and illumination state of named graphic zones — not on
physical product counting or fact-tag detection.

Each shelf level in the planogram config maps to one named graphic
zone (e.g., header → top graphic, middle → comparison table,
bottom → special offer panel).  The LLM is asked to detect those
zones via the ``roi_detection_prompt`` defined in the DB config, so
no changes to the DB schema are needed.

Args:
    pipeline: Parent PlanogramCompliance instance.
    config: The PlanogramConfig for this compliance run.

## Methods

- `async def compute_roi(self, img: Image.Image) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[Any], Optional[Any], Optional[Any], List[Any]]` — Compute the region of interest by locating the graphic endcap boundary.
- `async def detect_objects_roi(self, img: Image.Image, roi: Any) -> List[Detection]` — Detect named graphic zones within the endcap ROI.
- `async def detect_objects(self, img: Image.Image, roi: Any, macro_objects: Any) -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]` — OCR + visual feature verification for each detected graphic zone.
- `def check_planogram_compliance(self, identified_products: List[IdentifiedProduct], planogram_description: Any) -> List[ComplianceResult]` — Compare detected graphic zones against the expected planogram layout.
