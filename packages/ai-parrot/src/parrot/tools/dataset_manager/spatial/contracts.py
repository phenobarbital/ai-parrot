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
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator, model_validator

# Allowed display-format hint values for DatasetSpatialProfile.column_formats.
_ALLOWED_COLUMN_FORMATS: frozenset = frozenset(
    {"currency", "percent", "email", "uri", "enum", "id", "code"}
)

# Recognised geo column names (lowercased) for SpatialResult.from_dataframe.
_LAT_ALIASES: Tuple[str, ...] = ("lat", "latitude")
_LON_ALIASES: Tuple[str, ...] = ("lon", "lng", "long", "longitude")
_GEOM_ALIASES: Tuple[str, ...] = ("geometry", "geom")

# Splits a column name into tokens on any non-alphanumeric boundary so that
# prefixed/suffixed geo columns (``wh_latitude``, ``store_lat``, ``geom_wkt``)
# are recognised by token, not substring — avoiding false positives such as
# ``belongings`` matching ``long`` or ``flat_id`` matching ``lat``.
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _resolve_geo_column(
    lower: Dict[str, str], aliases: Tuple[str, ...],
) -> Optional[str]:
    """Resolve a geo column from a lowercased-name -> original-name map.

    Matching is two-tiered: an exact alias match is preferred (preserving the
    historical alias-priority ordering), then a token-boundary match catches
    prefixed/suffixed variants like ``wh_latitude`` or ``store_lng``.

    Args:
        lower: Mapping of ``column.lower().strip()`` to the original column name.
        aliases: Candidate alias names (already lowercased), in priority order.

    Returns:
        The original column name of the first match, or ``None`` when no column
        matches by exact alias or whole-token boundary.
    """
    for alias in aliases:
        if alias in lower:
            return lower[alias]
    alias_set = set(aliases)
    for col_lower, original in lower.items():
        tokens = {t for t in _TOKEN_SPLIT.split(col_lower) if t}
        if tokens & alias_set:
            return original
    return None


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

    # ── DataFrame ingestion (FEAT-224) ──────────────────────────────────────
    @classmethod
    def from_dataframe(
        cls,
        df: Any,
        *,
        lat_col: Optional[str] = None,
        lon_col: Optional[str] = None,
        geometry_col: Optional[str] = None,
        dataset: str = "result",
        layer: str = "result",
        property_cols: Optional[List[str]] = None,
        geodesic: bool = False,
    ) -> "SpatialResult":
        """Build a single-layer ``SpatialResult`` from a pandas DataFrame.

        Lets callers (e.g. ``PandasAgent``) turn an arbitrary result DataFrame
        into the GeoJSON wire contract the ``STRUCTURED_MAP`` renderer consumes —
        no backend map rendering, no LLM call. Two input shapes are supported and
        auto-detected when the ``*_col`` arguments are omitted:

        * **Coordinate pair** — a latitude column (``lat``/``latitude``) and a
          longitude column (``lon``/``lng``/``long``/``longitude``); each row
          becomes a GeoJSON ``Point``.
        * **Geo-structure column** — a ``geometry``/``geom`` column whose cells
          are GeoJSON geometry dicts, GeoJSON ``Feature`` dicts, WKT strings, or
          shapely geometries (anything exposing ``__geo_interface__``). The
          geometry is preserved as-is, so Polygons, LineStrings, etc. survive.

        Detection prefers a geometry column over a lat/lon pair. All columns
        except the resolved geo columns become each feature's ``properties``.
        Rows whose geometry cannot be resolved (missing/NaN coords, unparseable
        WKT) are skipped.

        Args:
            df: A pandas DataFrame (or GeoDataFrame) of result rows.
            lat_col: Latitude column name; auto-detected when omitted.
            lon_col: Longitude column name; auto-detected when omitted.
            geometry_col: Geometry column name; auto-detected when omitted.
            dataset: Key under which the single layer is stored in ``layers``.
            layer: Leaflet layer id / GeoJSON source discriminator.
            property_cols: Columns to expose as feature properties. Defaults to
                every column except the resolved geo columns.
            geodesic: Whether downstream paths should be treated as geodesic.

        Returns:
            A version-2 ``SpatialResult`` with a single ``SpatialLayerResult``.
            The layer may have zero features when no row yields a geometry.

        Raises:
            ValueError: When neither a geometry column nor a lat/lon pair can be
                resolved from the DataFrame columns.
        """
        columns = [str(c) for c in df.columns]
        lower = {c.lower().strip(): c for c in columns}

        if geometry_col is None and lat_col is None and lon_col is None:
            geometry_col = _resolve_geo_column(lower, _GEOM_ALIASES)
            if geometry_col is None:
                lat_col = _resolve_geo_column(lower, _LAT_ALIASES)
                lon_col = _resolve_geo_column(lower, _LON_ALIASES)

        if geometry_col is None and not (lat_col and lon_col):
            raise ValueError(
                "SpatialResult.from_dataframe: no geometry column and no "
                f"lat/lon pair could be resolved from columns: {columns}"
            )

        geo_cols = {c for c in (lat_col, lon_col, geometry_col) if c}
        if property_cols is None:
            property_cols = [c for c in columns if c not in geo_cols]

        features: List[Dict] = []
        for row in df.to_dict(orient="records"):
            if geometry_col is not None:
                geometry = cls._geometry_from_value(row.get(geometry_col))
            else:
                geometry = cls._point_geometry(row.get(lat_col), row.get(lon_col))
            if geometry is None:
                continue
            properties = {col: cls._jsonable(row.get(col)) for col in property_cols}
            features.append(
                {"type": "Feature", "geometry": geometry, "properties": properties}
            )

        return cls(
            layers={
                dataset: SpatialLayerResult(
                    layer=layer,
                    features=features,
                    total_count=len(features),
                    capped=False,
                    geodesic=geodesic,
                )
            }
        )

    @staticmethod
    def _is_missing(value: Any) -> bool:
        """True when a cell is ``None`` or NaN/NaT (no eager pandas import).

        NaN/NaT are the only values not equal to themselves, which lets this
        detect numpy NaN and pandas NaT without importing either library.
        """
        if value is None:
            return True
        try:
            return value != value  # noqa: PLR0124 — NaN/NaT self-inequality
        except Exception:  # noqa: BLE001 — exotic objects compare fine
            return False

    @classmethod
    def _point_geometry(cls, lat: Any, lon: Any) -> Optional[Dict]:
        """Build a GeoJSON ``Point`` (``[lon, lat]``) or ``None`` if unusable."""
        if cls._is_missing(lat) or cls._is_missing(lon):
            return None
        try:
            return {"type": "Point", "coordinates": [float(lon), float(lat)]}
        except (TypeError, ValueError):
            return None

    @classmethod
    def _geometry_from_value(cls, value: Any) -> Optional[Dict]:
        """Coerce a geometry-column cell into a GeoJSON geometry dict.

        Accepts GeoJSON geometry dicts, GeoJSON ``Feature`` dicts (unwrapped),
        shapely geometries (via ``__geo_interface__``), and WKT strings (parsed
        with shapely when available). Returns ``None`` when unresolvable.
        """
        if cls._is_missing(value):
            return None
        if isinstance(value, dict):
            if value.get("type") == "Feature" and isinstance(value.get("geometry"), dict):
                return value["geometry"]
            if value.get("type") and value.get("coordinates") is not None:
                return value
            return None
        geo = getattr(value, "__geo_interface__", None)
        if isinstance(geo, dict):
            if geo.get("type") == "Feature" and isinstance(geo.get("geometry"), dict):
                return geo["geometry"]
            return geo
        if isinstance(value, str):
            return cls._wkt_to_geometry(value)
        return None

    @staticmethod
    def _wkt_to_geometry(wkt: str) -> Optional[Dict]:
        """Parse a WKT string into a GeoJSON geometry via shapely (optional dep)."""
        text = wkt.strip()
        if not text:
            return None
        try:
            from shapely import wkt as _wkt
            from shapely.geometry import mapping
        except ImportError:
            return None
        try:
            return mapping(_wkt.loads(text))
        except Exception:  # noqa: BLE001 — invalid WKT -> no geometry
            return None

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        """Coerce a property cell to a JSON-native scalar.

        numpy scalars (``.item()``) and datetimes (``.isoformat()``) are
        unwrapped; NaN/NaT collapse to ``None``; anything exotic falls back to
        ``str()``.
        """
        if cls._is_missing(value):
            return None
        if isinstance(value, (str, bool, int, float)):
            return value
        item = getattr(value, "item", None)
        if callable(item):
            try:
                return item()
            except Exception:  # noqa: BLE001
                pass
        iso = getattr(value, "isoformat", None)
        if callable(iso):
            try:
                return iso()
            except Exception:  # noqa: BLE001
                pass
        return str(value)


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
