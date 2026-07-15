---
type: Concept
title: register_spatial_profile()
id: func:parrot.tools.dataset_manager.spatial.registry.register_spatial_profile
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register (or replace) a spatial profile for a dataset.
---

# register_spatial_profile

```python
def register_spatial_profile(profile: DatasetSpatialProfile) -> None
```

Register (or replace) a spatial profile for a dataset.

Args:
    profile: A validated DatasetSpatialProfile.  The profile's
        ``dataset`` field is used as the registry key.  If a profile
        for the same dataset already exists it is silently replaced.

Example::

    register_spatial_profile(DatasetSpatialProfile(
        dataset="schools",
        geom_col="geog",
        layer="schools",
        property_cols=["name", "type"],
        description_template="{name} ({type})",
    ))
