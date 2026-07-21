---
type: Wiki Entity
title: GridDetector
id: class:parrot_pipelines.planogram.grid.detector.GridDetector
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Orchestrates parallel per-cell LLM detection calls.
---

# GridDetector

Defined in [`parrot_pipelines.planogram.grid.detector`](../summaries/mod:parrot_pipelines.planogram.grid.detector.md).

```python
class GridDetector
```

Orchestrates parallel per-cell LLM detection calls.

Takes a list of GridCells, crops images, builds per-cell prompts with
filtered hints and reference images, executes calls in parallel, and
returns a merged, deduplicated product list.

Args:
    llm: LLM client with an async detect_objects() method.
    reference_images: Dict mapping product keys to image paths/objects.
        Values may be a single image (str/Path/Image) or a list of images.
    logger: Logger instance for debug/error output.

## Methods

- `async def detect_cells(self, cells: List[GridCell], image: Image.Image, grid_config: DetectionGridConfig) -> List[IdentifiedProduct]` — Detect products in all cells in parallel.
