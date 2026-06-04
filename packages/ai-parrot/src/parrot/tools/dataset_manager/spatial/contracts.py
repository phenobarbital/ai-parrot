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

# Allowed display-format hint values for DatasetSpatialProfile.column_formats.
_ALLOWED_COLUMN_FORMATS: frozenset = frozenset(
    {"currency", "percent", "email", "uri", "enum", "id", "code"}
)


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

    # ── FEAT-221 Presentation Hints (optional, backward-compatible) ───────────

    label_col: Optional[str] = Field(
        default=None,
        description=(
            "Property key for the marker label (e.g. 'name'). "
            "Used by StructuredMapRenderer to set MapLayer.label_field."
        ),
    )
    tooltip_template: Optional[str] = Field(
        default=None,
        description=(
            "Per-layer tooltip template distinct from description_template. "
            "Falls back to description_template when unset. "
            "Applied client-side over feature.properties via str.format_map."
        ),
    )
    column_titles: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional human-readable column titles keyed by property column name. "
            "Renderer default = column name when absent."
        ),
    )
    column_formats: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional display format hints keyed by property column name. "
            "Allowed values: currency | percent | email | uri | enum | id | code."
        ),
    )
    default_data_shape: Literal["geojson", "rows"] = Field(
        default="geojson",
        description=(
            "Per-dataset default data payload shape for MapLayer.data_shape (G6). "
            "'geojson' passes features through; 'rows' flattens to canonical row dicts."
        ),
    )

    @field_validator("column_formats", mode="after")
    @classmethod
    def _validate_column_formats(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate that all column_formats values are recognised format hints.

        Args:
            v: The ``column_formats`` dict to validate.

        Returns:
            The validated dict unchanged.

        Raises:
            ValueError: If any value is not in ``_ALLOWED_COLUMN_FORMATS``.
        """
        bad = {k: fmt for k, fmt in v.items() if fmt not in _ALLOWED_COLUMN_FORMATS}
        if bad:
            raise ValueError(
                f"column_formats contains invalid format hints: {bad!r}. "
                f"Allowed: {sorted(_ALLOWED_COLUMN_FORMATS)}"
            )
        return v

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


class SpatialLayerResult(BaseModel):
    """Per-dataset slice of a spatial filter result (FEAT-221 G4).

    Attributes:
        layer: Leaflet layer id / GeoJSON source discriminator (from DatasetSpatialProfile).
        features: GeoJSON Feature dicts for this dataset.
        total_count: True count of matching features before capping.
        capped: True when the result was truncated at the hard cap.
        geodesic: Whether the executed path was geodesic (True) or
            spherical-approximate (False).
    """

    layer: str = Field(..., description="Leaflet layer id / GeoJSON source discriminator.")
    features: List[Dict] = Field(
        default_factory=list,
        description="GeoJSON Feature objects for this dataset.",
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
    geodesic: bool = Field(
        default=True,
        description="True = geodesic path; False = spherical-approx.",
    )


class SpatialResult(BaseModel):
    """Versioned per-dataset result returned by spatial_filter (FEAT-221 G4).

    Replaces the merged ``SpatialFeatureCollection`` with per-dataset grouping.
    The ``as_feature_collection()`` method reproduces the legacy merged shape for
    backward-compatible callers (e.g. the transport handler).

    Attributes:
        version: Schema version — always 2 for this model.
        layers: Per-dataset results keyed by resolved dataset name.
    """

    version: Literal[2] = Field(
        default=2,
        description="Schema version — always 2.",
    )
    layers: Dict[str, SpatialLayerResult] = Field(
        default_factory=dict,
        description="Per-dataset results keyed by resolved dataset name.",
    )

    def as_feature_collection(self) -> "SpatialFeatureCollection":
        """Reproduce the legacy merged SpatialFeatureCollection shape.

        Concatenates all per-dataset features, sums ``total_count`` values,
        ORs the ``capped`` flags, and builds ``geodesic_paths`` from each
        layer's ``geodesic`` flag.

        Returns:
            A ``SpatialFeatureCollection`` compatible with pre-FEAT-221 callers.
        """
        all_features: List[Dict] = []
        total_count = 0
        capped = False
        geodesic_paths: Dict[str, bool] = {}

        for dataset_name, layer_result in self.layers.items():
            all_features.extend(layer_result.features)
            total_count += layer_result.total_count
            capped = capped or layer_result.capped
            geodesic_paths[dataset_name] = layer_result.geodesic

        return SpatialFeatureCollection(
            features=all_features,
            total_count=total_count,
            capped=capped,
            geodesic_paths=geodesic_paths,
        )


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
