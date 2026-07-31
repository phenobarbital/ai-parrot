---
type: Wiki Summary
title: parrot.tools.dataset_manager.spatial.registry
id: mod:parrot.tools.dataset_manager.spatial.registry
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SPATIAL_PROFILE_REGISTRY — standalone profile store for DatasetManager spatial
  queries.
relates_to:
- concept: func:parrot.tools.dataset_manager.spatial.registry.get_spatial_profile
  rel: defines
- concept: func:parrot.tools.dataset_manager.spatial.registry.register_spatial_profile
  rel: defines
- concept: func:parrot.tools.dataset_manager.spatial.registry.validate_profiles_exist
  rel: defines
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: references
---

# `parrot.tools.dataset_manager.spatial.registry`

SPATIAL_PROFILE_REGISTRY — standalone profile store for DatasetManager spatial queries.

Implements brainstorm Option B: profiles live in a standalone registry keyed by dataset
name; no co-registration with the DatasetManager at construction time.

Validate-at-execute discipline mirrors CompositeDataSource.fetch (composite.py:161):
when the spatial_filter orchestration resolves a profile it validates that the referenced
dataset actually exists in the DatasetManager, raising a descriptive ValueError naming
the missing dataset.

Module-level objects:
    SPATIAL_PROFILE_REGISTRY: Dict[str, DatasetSpatialProfile]
        The global profile store.  Keyed by dataset name.

Functions:
    register_spatial_profile(profile): Add/replace a profile in the registry.
    get_spatial_profile(dataset_name): Look up a profile; raises ValueError if absent.

## Functions

- `def register_spatial_profile(profile: DatasetSpatialProfile) -> None` — Register (or replace) a spatial profile for a dataset.
- `def get_spatial_profile(dataset_name: str) -> DatasetSpatialProfile` — Look up a spatial profile by dataset name.
- `def validate_profiles_exist(dataset_names: List[str]) -> None` — Validate that every dataset name has a registered spatial profile.
