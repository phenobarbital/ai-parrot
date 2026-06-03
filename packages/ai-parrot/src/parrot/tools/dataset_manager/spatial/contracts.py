"""Pure Pydantic contracts for spatial filtering (FEAT-219 Module 1).

These are I/O-free data models.  They carry no driver or DSN information —
the SpatialCompiler and DatasetManager.spatial_filter consume them.

Classes:
    SpatialFilterSpec: Describes a spatial radius query (point + radius + datasets).
    DatasetSpatialProfile: Describes how a dataset exposes its geometry.
    SpatialFeatureCollection: GeoJSON FeatureCollection with capping metadata.

Note: ``from __future__ import annotations`` is intentionally omitted here to
ensure Pydantic v2 can resolve the ``Tuple[float, float]`` annotation at class
definition time without requiring a manual ``model_rebuild()`` call.
"""
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator


class SpatialFilterSpec(BaseModel):
    """Describes a spatial radius filter request.

    Backend-agnostic: carries no driver, DSN, or SQL.  Emitted identically
    by the LLM (NL→spec mode) and the frontend (deterministic mode).

    Attributes:
        point: (lat, lng) in decimal degrees.
        radius: Search radius in the specified unit.
        unit: Distance unit — "mi", "km", or "m".
        datasets: Dataset names to query (resolved via DatasetManager._resolve_name).
    """

    point: Tuple[float, float] = Field(
        ...,
        description="(lat, lng) in decimal degrees.",
    )
    radius: float = Field(
        ...,
        gt=0,
        description="Search radius in the specified unit.",
    )
    unit: Literal["mi", "km", "m"] = Field(
        default="mi",
        description="Distance unit: mi, km, or m.",
    )
    datasets: List[str] = Field(
        ...,
        min_length=1,
        description="Dataset names to query.",
    )

    @field_validator("point", mode="before")
    @classmethod
    def _validate_point(cls, v: object) -> Tuple[float, float]:
        """Validate that point is a 2-tuple of floats with valid coordinate bounds.

        Args:
            v: Raw value for point.

        Returns:
            Validated (lat, lng) tuple.

        Raises:
            ValueError: If value is not a 2-element sequence, or if latitude is
                outside [-90, 90], or if longitude is outside [-180, 180].
        """
        try:
            seq = tuple(v)  # type: ignore[arg-type]
        except TypeError:
            raise ValueError("point must be a sequence of two floats (lat, lng)")
        if len(seq) != 2:
            raise ValueError(
                f"point must be exactly 2 elements (lat, lng); got {len(seq)}"
            )
        lat, lng = float(seq[0]), float(seq[1])
        if not (-90.0 <= lat <= 90.0):
            raise ValueError(
                f"latitude must be in [-90, 90]; got {lat}"
            )
        if not (-180.0 <= lng <= 180.0):
            raise ValueError(
                f"longitude must be in [-180, 180]; got {lng}"
            )
        return (lat, lng)

    @field_validator("datasets", mode="before")
    @classmethod
    def _validate_datasets_not_empty(cls, v: object) -> List[str]:
        """Validate that at least one dataset is requested.

        Args:
            v: Raw datasets value.

        Returns:
            Validated list of dataset names.

        Raises:
            ValueError: If the list is empty.
        """
        lst = list(v)  # type: ignore[arg-type]
        if not lst:
            raise ValueError("datasets must contain at least one dataset name")
        return lst


class DatasetSpatialProfile(BaseModel):
    """Describes how a specific dataset exposes its geometry.

    Each dataset that participates in spatial queries must have a profile
    registered in SPATIAL_PROFILE_REGISTRY.  Profiles are I/O-free; they
    carry only structural metadata.

    Attributes:
        dataset: FK to a registered dataset name (must exist at execute time).
        lat_col: Latitude column name (naive lat/lng pair).
        lng_col: Longitude column name (naive lat/lng pair).
        geom_col: Native geometry or geography column.  Mutually exclusive with
            lat_col/lng_col when used for push-down — the compiler picks the
            appropriate path.
        layer: Leaflet layer id / GeoJSON ``source`` discriminator.
        property_cols: Column names to include in GeoJSON feature.properties.
        description_template: Python ``str.format_map`` template, e.g. ``"{name} ({type})"``.
        geodesic: Declared hint.  True = profile expects geodesic (native geography)
            precision; the compiler verifies this against the actual column type.
    """

    dataset: str = Field(..., description="FK to registered dataset name.")
    lat_col: Optional[str] = Field(default=None, description="Latitude column (naive pair).")
    lng_col: Optional[str] = Field(default=None, description="Longitude column (naive pair).")
    geom_col: Optional[str] = Field(
        default=None,
        description="Native geometry/geography column.",
    )
    layer: str = Field(..., description="Leaflet layer id / GeoJSON source discriminator.")
    property_cols: List[str] = Field(
        default_factory=list,
        description="Column names for GeoJSON feature.properties.",
    )
    description_template: str = Field(
        default="",
        description="Python str.format_map template for feature description.",
    )
    geodesic: bool = Field(
        default=True,
        description="Declared hint: True = native geography precision expected.",
    )

    @model_validator(mode="after")
    def _validate_geometry_source(self) -> "DatasetSpatialProfile":  # noqa: F821
        """Validate that at least one geometry source is provided.

        Returns:
            Self after validation.

        Raises:
            ValueError: If neither (lat_col+lng_col) nor geom_col is set.
        """
        has_latlon = bool(self.lat_col and self.lng_col)
        has_geom = bool(self.geom_col)
        if not has_latlon and not has_geom:
            raise ValueError(
                f"DatasetSpatialProfile for dataset '{self.dataset}' must specify either "
                "geom_col or both lat_col and lng_col."
            )
        return self


class SpatialFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection returned by DatasetManager.spatial_filter.

    The shape is identical regardless of whether the query came from the LLM
    (NL→spec) or the frontend (deterministic).  Frontend builds the map;
    this model carries data only.

    Attributes:
        type: GeoJSON type discriminator — always "FeatureCollection".
        features: List of GeoJSON Feature dicts.  Each feature has at least
            ``geometry``, ``properties`` (with data + ``description`` + ``source``),
            and ``type``.
        total_count: True count of matching features before capping.  May be
            greater than ``len(features)`` when capped.
        capped: True when the result was truncated at the hard cap.
        geodesic_paths: Per-dataset flag recording whether the executed path
            was geodesic (True) or spherical-approximate (False).
    """

    type: Literal["FeatureCollection"] = Field(
        default="FeatureCollection",
        description="GeoJSON type discriminator.",
    )
    features: List[Dict] = Field(
        default_factory=list,
        description="GeoJSON Feature objects.",
    )
    total_count: int = Field(
        default=0,
        ge=0,
        description="True count of matching features (>= len(features) when capped).",
    )
    capped: bool = Field(
        default=False,
        description="True when the result was truncated at the hard cap.",
    )
    geodesic_paths: Dict[str, bool] = Field(
        default_factory=dict,
        description="Per-dataset: True = geodesic, False = spherical-approx.",
    )
