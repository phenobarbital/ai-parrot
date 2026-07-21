---
type: Wiki Summary
title: parrot.tools.dataset_manager.spatial
id: mod:parrot.tools.dataset_manager.spatial
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spatial filtering support for DatasetManager (FEAT-219).
relates_to:
- concept: mod:parrot.tools.dataset_manager
  rel: references
---

# `parrot.tools.dataset_manager.spatial`

Spatial filtering support for DatasetManager (FEAT-219).

Exposes the public surface:
- Pydantic contracts: SpatialFilterSpec, DatasetSpatialProfile, SpatialFeatureCollection
- Per-dataset result models (FEAT-221): SpatialLayerResult, SpatialResult
- Profile registry: SPATIAL_PROFILE_REGISTRY, register_spatial_profile, get_spatial_profile
- Compiler: SpatialCompiler, CompiledQuery
