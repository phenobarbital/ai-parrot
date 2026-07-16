---
type: Concept
title: get_spatial_profile()
id: func:parrot.tools.dataset_manager.spatial.registry.get_spatial_profile
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Look up a spatial profile by dataset name.
---

# get_spatial_profile

```python
def get_spatial_profile(dataset_name: str) -> DatasetSpatialProfile
```

Look up a spatial profile by dataset name.

Args:
    dataset_name: The dataset name (canonical, not an alias).

Returns:
    The registered DatasetSpatialProfile.

Raises:
    ValueError: If no profile is registered for ``dataset_name``.
        The error message names the missing dataset so the caller can
        surface a useful diagnostic (mirrors CompositeDataSource.fetch
        discipline).
