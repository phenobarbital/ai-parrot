---
type: Wiki Summary
title: parrot.tools.dataset_manager.spatial.contracts
id: mod:parrot.tools.dataset_manager.spatial.contracts
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pure Pydantic contracts for spatial filtering (FEAT-219 Module 1).
relates_to:
- concept: class:parrot.tools.dataset_manager.spatial.contracts.DatasetSpatialProfile
  rel: defines
- concept: class:parrot.tools.dataset_manager.spatial.contracts.SpatialFeatureCollection
  rel: defines
- concept: class:parrot.tools.dataset_manager.spatial.contracts.SpatialFilterSpec
  rel: defines
- concept: class:parrot.tools.dataset_manager.spatial.contracts.SpatialLayerResult
  rel: defines
- concept: class:parrot.tools.dataset_manager.spatial.contracts.SpatialResult
  rel: defines
---

# `parrot.tools.dataset_manager.spatial.contracts`

Pure Pydantic contracts for spatial filtering (FEAT-219 Module 1).

These are I/O-free data models.  They carry no driver or DSN information —
the SpatialCompiler and DatasetManager.spatial_filter consume them.

Classes:
    SpatialFilterSpec: Describes a spatial radius query (point + radius + datasets).
    DatasetSpatialProfile: Describes how a dataset exposes its geometry.
    SpatialFeatureCollection: GeoJSON FeatureCollection with capping metadata.

Note: ``from __future__ import annotations`` is intentionally omitted here to
ensure Pydantic v2 can resolve the ``Tuple[float, float]`` annotation at class
definition time without requiring a manual ``model_rebuild()`` call.

## Classes

- **`SpatialFilterSpec(BaseModel)`** — Describes a spatial radius filter request.
- **`DatasetSpatialProfile(BaseModel)`** — Describes how a specific dataset exposes its geometry.
- **`SpatialLayerResult(BaseModel)`** — Per-dataset slice of a spatial filter result (FEAT-221 G4).
- **`SpatialResult(BaseModel)`** — Versioned per-dataset result returned by spatial_filter (FEAT-221 G4).
- **`SpatialFeatureCollection(BaseModel)`** — GeoJSON FeatureCollection returned by DatasetManager.spatial_filter.
