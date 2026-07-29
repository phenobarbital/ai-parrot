---
type: Wiki Entity
title: EChartsMapsMixin
id: class:parrot.outputs.formats.mixins.emaps.EChartsMapsMixin
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin class to add geo/map capabilities to EChartsRenderer
---

# EChartsMapsMixin

Defined in [`parrot.outputs.formats.mixins.emaps`](../summaries/mod:parrot.outputs.formats.mixins.emaps.md).

```python
class EChartsMapsMixin
```

Mixin class to add geo/map capabilities to EChartsRenderer

This mixin adds methods for creating and validating geographic visualizations
to the existing EChartsRenderer without breaking existing functionality.

Usage in echarts.py:
    from ._echarts_geo_ext import EChartsMapsMixin

    @register_renderer(OutputMode.ECHARTS, system_prompt=ECHARTS_SYSTEM_PROMPT)
    class EChartsRenderer(EChartsMapsMixin, BaseChart):
        # ... existing methods ...

## Methods

- `def create_geo_builder(self, map_type: str='USA') -> EChartsGeoBuilder` — Factory method to create a geo builder
- `def validate_geo_config(self, config: Dict[str, Any]) -> Tuple[bool, Optional[str]]` — Validate a geo configuration
- `def render_geo_map(self, map_type: str='USA', title: Optional[str]=None, scatter_data: Optional[list]=None, choropleth_data: Optional[list]=None, auto_center: bool=True, **kwargs) -> Dict[str, Any]` — Convenience method to quickly create a geo map
