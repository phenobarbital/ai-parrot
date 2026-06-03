"""SPATIAL_PROFILE_REGISTRY — standalone profile store for DatasetManager spatial queries.

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
"""
from __future__ import annotations

import logging
from typing import Dict, List

from .contracts import DatasetSpatialProfile

logger = logging.getLogger(__name__)

# The global profile registry — keyed by dataset name.
SPATIAL_PROFILE_REGISTRY: Dict[str, DatasetSpatialProfile] = {}


def register_spatial_profile(profile: DatasetSpatialProfile) -> None:
    """Register (or replace) a spatial profile for a dataset.

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
    """
    SPATIAL_PROFILE_REGISTRY[profile.dataset] = profile
    logger.debug("Registered spatial profile for dataset '%s'.", profile.dataset)


def get_spatial_profile(dataset_name: str) -> DatasetSpatialProfile:
    """Look up a spatial profile by dataset name.

    Args:
        dataset_name: The dataset name (canonical, not an alias).

    Returns:
        The registered DatasetSpatialProfile.

    Raises:
        ValueError: If no profile is registered for ``dataset_name``.
            The error message names the missing dataset so the caller can
            surface a useful diagnostic (mirrors CompositeDataSource.fetch
            discipline).
    """
    profile = SPATIAL_PROFILE_REGISTRY.get(dataset_name)
    if profile is None:
        registered = sorted(SPATIAL_PROFILE_REGISTRY.keys())
        raise ValueError(
            f"No spatial profile registered for dataset '{dataset_name}'. "
            f"Registered spatial datasets: {registered}"
        )
    return profile


def validate_profiles_exist(dataset_names: List[str]) -> None:
    """Validate that every dataset name has a registered spatial profile.

    Iterates all names and raises a single descriptive ValueError listing
    every missing profile — mirrors CompositeDataSource.fetch validation.

    Args:
        dataset_names: List of canonical dataset names to check.

    Raises:
        ValueError: If any dataset name lacks a registered profile.
    """
    missing = [n for n in dataset_names if n not in SPATIAL_PROFILE_REGISTRY]
    if missing:
        registered = sorted(SPATIAL_PROFILE_REGISTRY.keys())
        raise ValueError(
            f"No spatial profile registered for dataset(s): {missing}. "
            f"Registered spatial datasets: {registered}"
        )
