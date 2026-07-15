---
type: Wiki Entity
title: CellResultMerger
id: class:parrot_pipelines.planogram.grid.merger.CellResultMerger
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Merges per-cell detection results into a unified product list.
---

# CellResultMerger

Defined in [`parrot_pipelines.planogram.grid.merger`](../summaries/mod:parrot_pipelines.planogram.grid.merger.md).

```python
class CellResultMerger
```

Merges per-cell detection results into a unified product list.

Applies per-cell coordinate offsets to convert cell-relative detections
to absolute image coordinates. Deduplicates boundary objects using IoU.
Tags objects not in any cell's expected_products as out_of_place.

## Methods

- `def merge(self, cell_results: List[Tuple[GridCell, List[IdentifiedProduct]]], iou_threshold: float=0.5) -> List[IdentifiedProduct]` — Merge detection results from multiple grid cells.
