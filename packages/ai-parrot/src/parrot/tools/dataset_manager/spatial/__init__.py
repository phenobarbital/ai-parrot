"""Spatial filtering support for DatasetManager (FEAT-219).

Exposes the public surface:
- Pydantic contracts: SpatialFilterSpec, DatasetSpatialProfile, SpatialFeatureCollection
- Profile registry: SPATIAL_PROFILE_REGISTRY, register_spatial_profile, get_spatial_profile
- Compiler: SpatialCompiler, CompiledQuery
"""
from .contracts import SpatialFilterSpec, DatasetSpatialProfile, SpatialFeatureCollection
from .registry import SPATIAL_PROFILE_REGISTRY, register_spatial_profile, get_spatial_profile

__all__ = [
    "SpatialFilterSpec",
    "DatasetSpatialProfile",
    "SpatialFeatureCollection",
    "SPATIAL_PROFILE_REGISTRY",
    "register_spatial_profile",
    "get_spatial_profile",
]
