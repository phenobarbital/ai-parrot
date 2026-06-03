"""SpatialCompiler — compile and execute spatial filter queries (FEAT-219).

Two execution paths, selected by ``getattr(source, "driver", None)``:

1. **Engine push-down** (pg, bigquery): emits an ``ST_DWITHIN`` + ``ST_AsGeoJSON``
   SQL query using driver-specific dialect templates.  ``compile()`` is I/O-free
   and ``syrupy``-snapshotable.  ``execute()`` runs via AsyncDB.

2. **Pandas bbox fallback** (mysql, unknown, InMemorySource): derives a bounding
   box from ``(point, radius)``, pushes a BETWEEN predicate, fetches box survivors,
   then refines to the exact circle with vectorized haversine (numpy).

Design principles (FEAT-219 spec §2):
- ``compile()`` is deterministic and I/O-free — no DB calls.
- ``execute()`` is async and performs all I/O.
- ``geodesic`` is declared on the profile and verified at compile time; the true
  path (geodesic vs spherical-approx) is returned in ``CompiledQuery.geodesic``.
- Never route through ``DatasetEntry.materialize`` / Redis Parquet cache (spec G4).
- TASK-1437 resolved NO-GO for Ibis — two hand-written SQL dialect templates are used.

Classes:
    CompiledQuery: Immutable result of compile() — SQL + metadata, no I/O.
    SpatialCompiler: Stateless compiler + executor.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import DatasetSpatialProfile, SpatialFilterSpec

logger = logging.getLogger(__name__)

# Drivers that support native spatial push-down.
_ENGINE_DRIVERS = frozenset({"pg", "bigquery"})

# Hard cap on engine-push-down results per dataset (prevent huge result sets).
_DEFAULT_ENGINE_CAP = 1000

# ---------------------------------------------------------------------------
# Radius unit conversion
# ---------------------------------------------------------------------------

_METERS_PER_MILE = 1609.344
_METERS_PER_KM = 1000.0

# Earth's mean radius in km (WGS-84 approximation for haversine)
_EARTH_RADIUS_KM = 6371.0088


def _to_meters(radius: float, unit: str) -> float:
    """Convert a radius to metres.

    Args:
        radius: Numeric distance value.
        unit: Distance unit — ``"mi"``, ``"km"``, or ``"m"``.

    Returns:
        Radius in metres.

    Raises:
        ValueError: If unit is not recognised.
    """
    if unit == "mi":
        return radius * _METERS_PER_MILE
    if unit == "km":
        return radius * _METERS_PER_KM
    if unit == "m":
        return radius
    raise ValueError(f"Unsupported distance unit: {unit!r}")


# ---------------------------------------------------------------------------
# Bounding-box helper
# ---------------------------------------------------------------------------


def _bbox_from_point(lat: float, lng: float, radius_m: float) -> tuple:
    """Derive a bounding box from a centre point and radius.

    The bbox is a *superset* of the circle — it is used for a cheap SQL BETWEEN
    predicate before the exact haversine refine.

    Args:
        lat: Centre latitude in decimal degrees.
        lng: Centre longitude in decimal degrees.
        radius_m: Search radius in metres.

    Returns:
        ``(min_lat, max_lat, min_lng, max_lng)`` in decimal degrees.
    """
    # 1 degree latitude ≈ 111_320 m (approximately constant)
    lat_delta = radius_m / 111_320.0
    # 1 degree longitude ≈ cos(lat) * 111_320 m
    lng_delta = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return (
        lat - lat_delta,
        lat + lat_delta,
        lng - lng_delta,
        lng + lng_delta,
    )


# ---------------------------------------------------------------------------
# CompiledQuery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledQuery:
    """Immutable result of SpatialCompiler.compile().

    All fields are set at compile time; no I/O occurs during construction.

    Attributes:
        sql: The SQL string to execute (engine push-down) or ``None`` for the
            in-memory fallback path.
        driver: Normalised AsyncDB driver name (``"pg"``, ``"bigquery"``,
            ``"mysql"``, or other).
        path: ``"engine"`` for pg/bigquery push-down; ``"pandas"`` for bbox fallback.
        geodesic: True if the executed path is geodesic (native geography column or
            BigQuery GEOGRAPHY).  False = spherical-approximate haversine.
        profile_dataset: The dataset name this compiled query is for.
        bbox: ``(min_lat, max_lat, min_lng, max_lng)`` for the pandas path (used in
            the BETWEEN predicate).  None for the engine path.
        lat_col: Latitude column name used in the fallback path.  None for engine path.
        lng_col: Longitude column name used in the fallback path.  None for engine path.
        point: ``(lat, lng)`` of the query centre point (used in haversine refine).
        radius_m: Search radius converted to metres.
        property_cols: Column names to include in GeoJSON feature properties.
        description_template: Python str.format_map template for feature description.
        geom_col: Geometry/geography column name for the engine path.
        cap: Maximum features to return for this dataset.
        geodesic_warning: Non-empty string if a geodesic mismatch was detected.
    """

    sql: Optional[str]
    driver: str
    path: str  # "engine" | "pandas"
    geodesic: bool
    profile_dataset: str
    point: tuple  # (lat, lng)
    radius_m: float
    property_cols: List[str]
    description_template: str
    bbox: Optional[tuple] = None  # (min_lat, max_lat, min_lng, max_lng) — pandas only
    lat_col: Optional[str] = None
    lng_col: Optional[str] = None
    geom_col: Optional[str] = None
    cap: int = _DEFAULT_ENGINE_CAP
    geodesic_warning: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SpatialCompiler
# ---------------------------------------------------------------------------


class SpatialCompiler:
    """Stateless spatial filter compiler and executor.

    compile() is pure (I/O-free, syrupy-snapshotable).
    execute() is async and performs DB/DataFrame I/O.
    """

    # ── Engine push-down SQL templates ───────────────────────────────────
    # Both use ?-style positional params so the VALUES are NOT interpolated
    # into the SQL string (snapshot-stable).  The actual bind values are
    # embedded in the CompiledQuery for execute() to supply.
    #
    # pg: uses ST_DWithin on a geography column.
    # bigquery: uses ST_DWITHIN on a GEOGRAPHY column.

    _PG_PUSHDOWN_GEOM_TEMPLATE = (
        "SELECT {property_cols}, "
        "ST_AsGeoJSON({geom_col}) AS __geojson__ "
        "FROM {table} "
        "WHERE ST_DWithin({geom_col}::geography, "
        "ST_MakePoint({lng}, {lat})::geography, {radius_m}) "
        "LIMIT {cap}"
    )

    _PG_PUSHDOWN_LATLON_TEMPLATE = (
        "SELECT {property_cols}, "
        "ST_AsGeoJSON(ST_MakePoint({lng_col}, {lat_col})) AS __geojson__ "
        "FROM {table} "
        "WHERE ST_DWithin("
        "ST_MakePoint({lng_col}, {lat_col})::geography, "
        "ST_MakePoint({lng}, {lat})::geography, {radius_m}) "
        "LIMIT {cap}"
    )

    _BQ_PUSHDOWN_GEOM_TEMPLATE = (
        "SELECT {property_cols}, "
        "ST_ASGEOJSON({geom_col}) AS __geojson__ "
        "FROM `{table}` "
        "WHERE ST_DWITHIN({geom_col}, "
        "ST_GEOGPOINT({lng}, {lat}), {radius_m}) "
        "LIMIT {cap}"
    )

    _BQ_PUSHDOWN_LATLON_TEMPLATE = (
        "SELECT {property_cols}, "
        "ST_ASGEOJSON(ST_GEOGPOINT({lng_col}, {lat_col})) AS __geojson__ "
        "FROM `{table}` "
        "WHERE ST_DWITHIN("
        "ST_GEOGPOINT({lng_col}, {lat_col}), "
        "ST_GEOGPOINT({lng}, {lat}), {radius_m}) "
        "LIMIT {cap}"
    )

    # ── Column-type → geodesic resolution ────────────────────────────────
    # pg column types that indicate a native geography column (geodesic).
    _PG_GEOGRAPHY_TYPES = frozenset({
        "geography",
        "pg_catalog.geography",
    })

    def compile(
        self,
        spec: "SpatialFilterSpec",
        profile: "DatasetSpatialProfile",
        source: Any = None,
        cap: int = _DEFAULT_ENGINE_CAP,
    ) -> CompiledQuery:
        """Compile a spatial filter spec into a CompiledQuery.

        I/O-free: this method does not touch the database.  The returned
        ``CompiledQuery`` is deterministic for a given (spec, profile, driver)
        triple and can be snapshot-tested without a DB connection.

        Args:
            spec: The spatial filter request.
            profile: The dataset's spatial profile.
            source: The DataSource for this dataset (TableSource or InMemorySource).
                Used only to read ``source.driver`` and ``source.table`` — no I/O.
                May be None for pure compile-time tests.
            cap: Maximum number of features to return for this dataset.

        Returns:
            CompiledQuery populated for either the engine push-down or pandas
            fallback path.
        """
        lat, lng = spec.point
        radius_m = _to_meters(spec.radius, spec.unit)
        driver = getattr(source, "driver", None) or ""
        table = getattr(source, "table", profile.dataset)

        if driver in _ENGINE_DRIVERS:
            return self._compile_engine(
                lat=lat, lng=lng, radius_m=radius_m,
                driver=driver, table=table,
                profile=profile, source=source, cap=cap,
            )
        # Fallback: pandas bbox + haversine
        return self._compile_pandas(
            lat=lat, lng=lng, radius_m=radius_m,
            driver=driver, profile=profile, cap=cap,
        )

    def _compile_engine(
        self,
        lat: float, lng: float, radius_m: float,
        driver: str, table: str,
        profile: "DatasetSpatialProfile",
        source: Any,
        cap: int,
    ) -> CompiledQuery:
        """Compile a push-down query for pg or bigquery.

        Args:
            lat: Centre latitude.
            lng: Centre longitude.
            radius_m: Radius in metres.
            driver: Normalised driver name (``"pg"`` or ``"bigquery"``).
            table: Fully-qualified table name.
            profile: Dataset spatial profile.
            source: DataSource instance (for schema inspection).
            cap: Hard cap on returned rows.

        Returns:
            CompiledQuery with path="engine".
        """
        # Geodesic declare + verify (declared hint on profile verified against column type)
        geodesic_actual, geodesic_warning = self._verify_geodesic(
            driver=driver, profile=profile, source=source
        )

        # Build property columns projection
        property_cols_sql = self._build_property_projection(profile.property_cols)

        if profile.geom_col:
            geom_col = profile.geom_col
            if driver == "pg":
                sql = self._PG_PUSHDOWN_GEOM_TEMPLATE.format(
                    property_cols=property_cols_sql,
                    geom_col=geom_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m, cap=cap,
                )
            else:  # bigquery
                sql = self._BQ_PUSHDOWN_GEOM_TEMPLATE.format(
                    property_cols=property_cols_sql,
                    geom_col=geom_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m, cap=cap,
                )
        elif profile.lat_col and profile.lng_col:
            lat_col = profile.lat_col
            lng_col = profile.lng_col
            if driver == "pg":
                sql = self._PG_PUSHDOWN_LATLON_TEMPLATE.format(
                    property_cols=property_cols_sql,
                    lat_col=lat_col, lng_col=lng_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m, cap=cap,
                )
            else:  # bigquery
                sql = self._BQ_PUSHDOWN_LATLON_TEMPLATE.format(
                    property_cols=property_cols_sql,
                    lat_col=lat_col, lng_col=lng_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m, cap=cap,
                )
        else:
            raise ValueError(
                f"Profile for '{profile.dataset}' has neither geom_col nor "
                "lat_col+lng_col — cannot compile engine push-down."
            )

        return CompiledQuery(
            sql=sql,
            driver=driver,
            path="engine",
            geodesic=geodesic_actual,
            profile_dataset=profile.dataset,
            point=(lat, lng),
            radius_m=radius_m,
            property_cols=list(profile.property_cols),
            description_template=profile.description_template,
            geom_col=profile.geom_col,
            cap=cap,
            geodesic_warning=geodesic_warning,
        )

    def _compile_pandas(
        self,
        lat: float, lng: float, radius_m: float,
        driver: str,
        profile: "DatasetSpatialProfile",
        cap: int,
    ) -> CompiledQuery:
        """Compile a bbox + haversine fallback for non-spatial backends.

        Args:
            lat: Centre latitude.
            lng: Centre longitude.
            radius_m: Radius in metres.
            driver: Normalised driver name (may be empty string for InMemorySource).
            profile: Dataset spatial profile.
            cap: Hard cap on returned rows.

        Returns:
            CompiledQuery with path="pandas" and sql=None.
        """
        bbox = _bbox_from_point(lat, lng, radius_m)
        return CompiledQuery(
            sql=None,
            driver=driver,
            path="pandas",
            geodesic=False,  # spherical-approximate haversine
            profile_dataset=profile.dataset,
            point=(lat, lng),
            radius_m=radius_m,
            property_cols=list(profile.property_cols),
            description_template=profile.description_template,
            lat_col=profile.lat_col,
            lng_col=profile.lng_col,
            geom_col=profile.geom_col,
            bbox=bbox,
            cap=cap,
            geodesic_warning="",
        )

    def _verify_geodesic(
        self,
        driver: str,
        profile: "DatasetSpatialProfile",
        source: Any,
    ) -> tuple:
        """Verify the declared geodesic hint against the actual column type.

        For pg, checks whether the geometry column is typed as ``geography``
        (geodesic) or ``geometry`` (planar).  For BigQuery, GEOGRAPHY is always
        geodesic.  For unknown driver/no source, returns the declared hint.

        Args:
            driver: Normalised driver name.
            profile: Dataset spatial profile.
            source: DataSource instance (or None for pure compile-time tests).

        Returns:
            ``(actual_geodesic: bool, warning_message: str)``.  Warning is non-empty
            when the declared hint mismatches the actual column type.
        """
        declared = profile.geodesic
        geom_col = profile.geom_col

        if driver == "bigquery":
            # BigQuery GEOGRAPHY is always geodesic
            actual = True
            if not declared:
                warning = (
                    f"Dataset '{profile.dataset}': profile declares geodesic=False "
                    "but BigQuery GEOGRAPHY is always geodesic.  "
                    "Updating effective geodesic to True."
                )
                logger.warning(warning)
                return True, warning
            return True, ""

        if driver == "pg" and geom_col and source is not None:
            # Check the column type from the prefetched schema
            schema: Dict[str, str] = getattr(source, "_schema", {})
            col_type = schema.get(geom_col, "").lower()
            if col_type:
                actual = col_type in self._PG_GEOGRAPHY_TYPES
                if actual != declared:
                    warning = (
                        f"Dataset '{profile.dataset}': profile declares "
                        f"geodesic={declared} but column '{geom_col}' has "
                        f"type '{col_type}' (geodesic={actual}).  "
                        "Recording actual path."
                    )
                    logger.warning(warning)
                    return actual, warning
                return actual, ""
            # Schema not available (strict_schema=False, source not prefetched)
            # Fall back to the declared hint; note the uncertainty.
            logger.debug(
                "Dataset '%s': column '%s' not found in prefetched schema; "
                "using declared geodesic=%s.",
                profile.dataset, geom_col, declared,
            )
            return declared, ""

        # Fallback: trust the declared hint
        return declared, ""

    @staticmethod
    def _build_property_projection(property_cols: List[str]) -> str:
        """Build the SQL SELECT projection for property columns.

        Args:
            property_cols: List of column names.

        Returns:
            Comma-separated column list string, or ``'*'`` if empty.
        """
        if not property_cols:
            return "*"
        # Simple identity projection — no aliasing needed
        return ", ".join(property_cols)

    # ── execute() ────────────────────────────────────────────────────────

    async def execute(
        self,
        compiled: CompiledQuery,
        source: Any,
    ) -> List[dict]:
        """Execute a compiled query against the given DataSource.

        Routes to the engine push-down or pandas fallback path based on
        ``compiled.path``.  Does NOT route through DatasetEntry.materialize
        (spec G4).

        Args:
            compiled: Output of compile().
            source: The DataSource for this dataset.

        Returns:
            List of GeoJSON Feature dicts.
        """
        if compiled.path == "engine":
            return await self._execute_engine(compiled, source)
        return await self._execute_pandas(compiled, source)

    async def _execute_engine(
        self,
        compiled: CompiledQuery,
        source: Any,
    ) -> List[dict]:
        """Execute the engine push-down SQL via AsyncDB.

        Args:
            compiled: A CompiledQuery with path="engine".
            source: TableSource instance.

        Returns:
            List of GeoJSON Feature dicts.

        Raises:
            RuntimeError: If the query fails.
        """
        from asyncdb import AsyncDB  # type: ignore[import]

        credentials, dsn = source._get_connection_args()

        if dsn:
            db = AsyncDB(source.driver, dsn=dsn)
        else:
            db = AsyncDB(source.driver, params=credentials)

        features: List[dict] = []

        async with await db.connection() as conn:
            conn.output_format("pandas")
            result, errors = await conn.query(compiled.sql)

            if errors:
                raise RuntimeError(
                    f"SpatialCompiler engine query failed for "
                    f"'{compiled.profile_dataset}': {errors}"
                )

            if result is None or (hasattr(result, "empty") and result.empty):
                return features

            import pandas as _pd
            if isinstance(result, _pd.DataFrame):
                for _, row in result.iterrows():
                    feature = self._row_to_geojson_feature(
                        row=dict(row),
                        compiled=compiled,
                    )
                    if feature:
                        features.append(feature)

        return features

    async def _execute_pandas(
        self,
        compiled: CompiledQuery,
        source: Any,
    ) -> List[dict]:
        """Execute bbox prefilter + haversine refine for non-spatial backends.

        For InMemorySource: uses the in-memory DataFrame directly.
        For TableSource with non-spatial driver: fetches via AsyncDB with a
        BETWEEN WHERE clause, then refines with haversine.

        Args:
            compiled: A CompiledQuery with path="pandas".
            source: DataSource instance (TableSource or InMemorySource).

        Returns:
            List of GeoJSON Feature dicts (after haversine refine).
        """
        # Determine how to get the bbox-filtered DataFrame
        from ..sources.memory import InMemorySource

        if isinstance(source, InMemorySource):
            # In-memory: filter directly (no DB)
            df = await source.fetch()
        else:
            # TableSource with non-spatial driver: fetch via AsyncDB with bbox SQL
            bbox_sql = self._build_bbox_sql(compiled, source)
            df = await source._run_query(bbox_sql)

        if df is None or (hasattr(df, "empty") and df.empty):
            return []

        # Haversine refine: keep only rows inside the exact circle
        df = self._haversine_refine(df, compiled)

        # Convert surviving rows to GeoJSON features
        features: List[dict] = []
        for _, row in df.iterrows():
            feature = self._row_to_latlon_geojson_feature(
                row=dict(row),
                compiled=compiled,
            )
            if feature:
                features.append(feature)

        # Apply cap
        return features[:compiled.cap]

    @staticmethod
    def _build_bbox_sql(compiled: CompiledQuery, source: Any) -> str:
        """Build a SQL SELECT with BETWEEN bbox predicate for the fallback path.

        This is a standalone query (not using _build_filter_clause) to avoid
        disturbing the TableSource.permanent_filter path.  The BETWEEN predicate
        is injected as a fresh WHERE clause; _inject_permanent_filter is then
        applied on top so permanent filters still apply.

        Args:
            compiled: CompiledQuery with bbox and lat/lng column names.
            source: TableSource instance.

        Returns:
            SQL string with bbox WHERE + permanent filter injected.
        """
        min_lat, max_lat, min_lng, max_lng = compiled.bbox  # type: ignore[misc]
        lat_col = compiled.lat_col
        lng_col = compiled.lng_col

        property_cols = compiled.property_cols or []
        if property_cols:
            select_cols = ", ".join(property_cols)
            if lat_col and lat_col not in property_cols:
                select_cols += f", {lat_col}"
            if lng_col and lng_col not in property_cols:
                select_cols += f", {lng_col}"
        else:
            select_cols = "*"

        sql = (
            f"SELECT {select_cols} FROM {source.table} "
            f"WHERE {lat_col} BETWEEN {min_lat} AND {max_lat} "
            f"AND {lng_col} BETWEEN {min_lng} AND {max_lng}"
        )

        # Inject permanent filter (permanent_filter dict on the source)
        sql = source._inject_permanent_filter(sql)

        if compiled.cap:
            sql += f" LIMIT {compiled.cap * 4}"  # over-fetch to account for refine loss

        return sql

    @staticmethod
    def _haversine_refine(df: Any, compiled: CompiledQuery) -> Any:
        """Vectorized haversine refine: drop rows outside the exact circle.

        The bbox is a superset of the circle (corners are outside) — this step
        converts the cheap BETWEEN-filtered survivors to the exact radius match.

        Args:
            df: pandas DataFrame with at least lat_col and lng_col columns.
            compiled: CompiledQuery with point, radius_m, lat_col, lng_col.

        Returns:
            Filtered DataFrame (reset index).
        """
        import numpy as np

        lat_col = compiled.lat_col
        lng_col = compiled.lng_col

        if not lat_col or not lng_col:
            logger.warning(
                "SpatialCompiler: haversine_refine called without lat/lng columns; "
                "returning unfiltered DataFrame."
            )
            return df

        center_lat, center_lng = compiled.point
        radius_m = compiled.radius_m

        # Vectorized haversine
        lat1 = np.radians(center_lat)
        lng1 = np.radians(center_lng)
        lat2 = np.radians(df[lat_col].values.astype(float))
        lng2 = np.radians(df[lng_col].values.astype(float))

        dlat = lat2 - lat1
        dlng = lng2 - lng1

        a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
        c = 2 * np.arcsin(np.sqrt(a))
        distance_m = _EARTH_RADIUS_KM * 1000.0 * c

        mask = distance_m <= radius_m
        return df[mask].reset_index(drop=True)

    @staticmethod
    def _row_to_geojson_feature(row: Dict[str, Any], compiled: CompiledQuery) -> Optional[dict]:
        """Build a GeoJSON Feature from a push-down row (has ``__geojson__`` column).

        Args:
            row: Dict of column name → value from the query result.
            compiled: CompiledQuery for this dataset.

        Returns:
            GeoJSON Feature dict, or None if the geometry is missing/invalid.
        """
        import json as _json

        geojson_str = row.get("__geojson__")
        if not geojson_str:
            return None

        try:
            geometry = _json.loads(geojson_str) if isinstance(geojson_str, str) else geojson_str
        except (ValueError, TypeError):
            logger.debug("SpatialCompiler: invalid __geojson__ value skipped: %r", geojson_str)
            return None

        properties = {col: row.get(col) for col in compiled.property_cols}
        properties["source"] = compiled.profile_dataset

        if compiled.description_template:
            try:
                properties["description"] = compiled.description_template.format_map(properties)
            except (KeyError, ValueError):
                properties["description"] = ""

        return {
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        }

    @staticmethod
    def _row_to_latlon_geojson_feature(
        row: Dict[str, Any],
        compiled: CompiledQuery,
    ) -> Optional[dict]:
        """Build a GeoJSON Feature from a pandas-path row (has lat/lng columns).

        Args:
            row: Dict of column name → value.
            compiled: CompiledQuery for this dataset.

        Returns:
            GeoJSON Feature dict, or None if lat/lng are missing.
        """
        lat_col = compiled.lat_col
        lng_col = compiled.lng_col

        if not lat_col or not lng_col:
            return None

        lat_val = row.get(lat_col)
        lng_val = row.get(lng_col)

        if lat_val is None or lng_val is None:
            return None

        try:
            geometry = {
                "type": "Point",
                "coordinates": [float(lng_val), float(lat_val)],
            }
        except (TypeError, ValueError):
            return None

        properties = {col: row.get(col) for col in compiled.property_cols}
        properties["source"] = compiled.profile_dataset

        if compiled.description_template:
            try:
                properties["description"] = compiled.description_template.format_map(properties)
            except (KeyError, ValueError):
                properties["description"] = ""

        return {
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        }
