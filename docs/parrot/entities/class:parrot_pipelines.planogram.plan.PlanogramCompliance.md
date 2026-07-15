---
type: Wiki Entity
title: PlanogramCompliance
id: class:parrot_pipelines.planogram.plan.PlanogramCompliance
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pure-LLM Planogram Compliance Pipeline with Composable Delegation.
relates_to:
- concept: class:parrot_pipelines.abstract.AbstractPipeline
  rel: extends
---

# PlanogramCompliance

Defined in [`parrot_pipelines.planogram.plan`](../summaries/mod:parrot_pipelines.planogram.plan.md).

```python
class PlanogramCompliance(AbstractPipeline)
```

Pure-LLM Planogram Compliance Pipeline with Composable Delegation.

Uses the Composable Pattern: PlanogramCompliance remains the single public
entry point. Internally it resolves a type-specific composable class
(e.g. ProductOnShelves, InkWall) from planogram_type in the config and
delegates all type-specific steps to it.

The handler always calls:
    pipeline = PlanogramCompliance(planogram_config=config, llm=llm)
    results = await pipeline.run(image)

## Methods

- `async def run(self, image: Union[str, Path, Image.Image], output_dir: Optional[Union[str, Path]]=None, image_id: Optional[str]=None, **kwargs) -> Dict[str, Any]` — Run the planogram compliance pipeline.
- `def render_evaluated_image(self, image: Union[str, Path, Image.Image], *, shelf_regions: Optional[List[ShelfRegion]]=None, detections: Optional[List[DetectionBox]]=None, identified_products: Optional[List[IdentifiedProduct]]=None, mode: str='identified', show_shelves: bool=True, save_to: Optional[Union[str, Path]]=None) -> Image.Image` — Render compliance evaluation overlay on the image.
