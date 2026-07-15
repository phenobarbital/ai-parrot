---
type: Wiki Entity
title: CoordinateValidator
id: class:parrot.outputs.formats.mixins.emaps.CoordinateValidator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validates and transforms geographic coordinates for ECharts
---

# CoordinateValidator

Defined in [`parrot.outputs.formats.mixins.emaps`](../summaries/mod:parrot.outputs.formats.mixins.emaps.md).

```python
class CoordinateValidator
```

Validates and transforms geographic coordinates for ECharts

## Methods

- `def is_valid_coordinate(lon: float, lat: float, region: str='world') -> bool` — Validate if coordinates are within acceptable ranges
- `def validate_coordinates(coordinates: List[Tuple[float, float]], region: str='world') -> List[Tuple[float, float]]` — Filter out invalid coordinates from a list
- `def calculate_center(coordinates: List[Tuple[float, float]]) -> Tuple[float, float]` — Calculate the center point of a set of coordinates
- `def suggest_zoom(coordinates: List[Tuple[float, float]]) -> float` — Suggest appropriate zoom level based on coordinate spread
