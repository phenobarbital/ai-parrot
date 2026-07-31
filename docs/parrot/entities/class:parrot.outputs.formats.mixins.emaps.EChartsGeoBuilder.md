---
type: Wiki Entity
title: EChartsGeoBuilder
id: class:parrot.outputs.formats.mixins.emaps.EChartsGeoBuilder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Helper class to build ECharts geo configurations programmatically
---

# EChartsGeoBuilder

Defined in [`parrot.outputs.formats.mixins.emaps`](../summaries/mod:parrot.outputs.formats.mixins.emaps.md).

```python
class EChartsGeoBuilder
```

Helper class to build ECharts geo configurations programmatically

## Methods

- `def set_title(self, text: str, **kwargs) -> 'EChartsGeoBuilder'` — Set chart title
- `def set_center(self, lon: float, lat: float) -> 'EChartsGeoBuilder'` — Set map center point
- `def set_zoom(self, zoom: float) -> 'EChartsGeoBuilder'` — Set map zoom level
- `def add_scatter_series(self, data: List[Dict[str, Any]], name: str='Points', symbol_size: Union[int, str]=10, color: str='#c23531', **kwargs) -> 'EChartsGeoBuilder'` — Add a scatter plot series to the map
- `def add_lines_series(self, data: List[Dict[str, Any]], name: str='Routes', line_color: str='#c23531', line_width: int=2, **kwargs) -> 'EChartsGeoBuilder'` — Add a lines series to show connections/routes
- `def add_heatmap_series(self, data: List[List[float]], name: str='Heatmap', color_range: Optional[List[str]]=None, **kwargs) -> 'EChartsGeoBuilder'` — Add a heatmap series
- `def add_choropleth_series(self, data: List[Dict[str, Any]], name: str='Regions', color_range: Optional[List[str]]=None, **kwargs) -> 'EChartsGeoBuilder'` — Add a choropleth map series (colored regions)
- `def auto_configure_from_data(self, coordinates: List[Tuple[float, float]], region: str='world') -> 'EChartsGeoBuilder'` — Automatically configure map center and zoom based on data
- `def build(self) -> Dict[str, Any]` — Build and return the complete configuration
- `def to_json(self, indent: int=2) -> str` — Export configuration as JSON string
