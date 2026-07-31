---
type: Wiki Entity
title: PlanogramConfigBuilder
id: class:parrot.models.detections.PlanogramConfigBuilder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Builder class for easier construction of planogram configurations
---

# PlanogramConfigBuilder

Defined in [`parrot.models.detections`](../summaries/mod:parrot.models.detections.md).

```python
class PlanogramConfigBuilder
```

Builder class for easier construction of planogram configurations

## Methods

- `def set_basic_info(self, brand: str, category: str, aisle: str) -> 'PlanogramConfigBuilder'` — Set basic planogram information
- `def add_shelf(self, level: str, products: List[Dict[str, Any]], compliance_threshold: float=0.8) -> 'PlanogramConfigBuilder'` — Add a shelf configuration
- `def add_product_to_shelf(self, shelf_level: str, name: str, product_type: str, quantity_range: tuple=(1, 1), mandatory: bool=True) -> 'PlanogramConfigBuilder'` — Add a product to an existing shelf
- `def set_advertisement_endcap(self, promotional_type: str, position: str='header', brand_requirements: List[str]=None, text_requirements: List[Dict[str, Any]]=None) -> 'PlanogramConfigBuilder'` — Configure advertisement endcap
- `def set_brand_detection(self, target_brands: List[str], confidence_threshold: float=0.7) -> 'PlanogramConfigBuilder'` — Configure brand detection
- `def build(self) -> Dict[str, Any]` — Build the final configuration dictionary
