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
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

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
    # 1 degree longitude ≈ cos(lat) * 111_320 m.
    # Guard against division by zero near the poles (cos ≈ 0 at ±90°): when the
    # absolute cosine is below 1e-6 the point is essentially at a pole and all
    # longitudes are equidistant, so we expand the bbox to cover all longitudes.
    cos_lat = math.cos(math.radians(lat))
    # Threshold: cos(lat) < 1e-4 means lat is within ~0.006° of a pole.
    # At that proximity the longitude degree length approaches zero, so the bbox
    # expands to cover all longitudes (full 360° wrap) rather than dividing by
    # a near-zero value.
    if abs(cos_lat) < 1e-4:
        lng_delta = 180.0  # near poles: bbox covers all longitudes
    else:
        lng_delta = radius_m / (111_320.0 * cos_lat)
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
    count_sql: Optional[str] = None  # COUNT(*) query without LIMIT for true_count
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
        'ST_AsGeoJSON("{geom_col}") AS __geojson__ '
        "FROM {table} "
        'WHERE ST_DWithin("{geom_col}"::geography, '
        "ST_MakePoint({lng}, {lat})::geography, {radius_m}) "
        "LIMIT {cap}"
    )

    # COUNT(*) counterpart for true_count — same WHERE, no LIMIT, no projection.
    _PG_COUNT_GEOM_TEMPLATE = (
        "SELECT COUNT(*) AS __count__ "
        "FROM {table} "
        'WHERE ST_DWithin("{geom_col}"::geography, '
        "ST_MakePoint({lng}, {lat})::geography, {radius_m})"
    )

    _PG_PUSHDOWN_LATLON_TEMPLATE = (
        "SELECT {property_cols}, "
        'ST_AsGeoJSON(ST_MakePoint("{lng_col}", "{lat_col}")) AS __geojson__ '
        "FROM {table} "
        "WHERE ST_DWithin("
        'ST_MakePoint("{lng_col}", "{lat_col}")::geography, '
        "ST_MakePoint({lng}, {lat})::geography, {radius_m}) "
        "LIMIT {cap}"
    )

    _PG_COUNT_LATLON_TEMPLATE = (
        "SELECT COUNT(*) AS __count__ "
        "FROM {table} "
        "WHERE ST_DWithin("
        'ST_MakePoint("{lng_col}", "{lat_col}")::geography, '
        "ST_MakePoint({lng}, {lat})::geography, {radius_m})"
    )

    _BQ_PUSHDOWN_GEOM_TEMPLATE = (
        "SELECT {property_cols}, "
        "ST_ASGEOJSON(`{geom_col}`) AS __geojson__ "
        "FROM `{table}` "
        "WHERE ST_DWITHIN(`{geom_col}`, "
        "ST_GEOGPOINT({lng}, {lat}), {radius_m}) "
        "LIMIT {cap}"
    )

    _BQ_COUNT_GEOM_TEMPLATE = (
        "SELECT COUNT(*) AS __count__ "
        "FROM `{table}` "
        "WHERE ST_DWITHIN(`{geom_col}`, "
        "ST_GEOGPOINT({lng}, {lat}), {radius_m})"
    )

    _BQ_PUSHDOWN_LATLON_TEMPLATE = (
        "SELECT {property_cols}, "
        "ST_ASGEOJSON(ST_GEOGPOINT(`{lng_col}`, `{lat_col}`)) AS __geojson__ "
        "FROM `{table}` "
        "WHERE ST_DWITHIN("
        "ST_GEOGPOINT(`{lng_col}`, `{lat_col}`), "
        "ST_GEOGPOINT({lng}, {lat}), {radius_m}) "
        "LIMIT {cap}"
    )

    _BQ_COUNT_LATLON_TEMPLATE = (
        "SELECT COUNT(*) AS __count__ "
        "FROM `{table}` "
        "WHERE ST_DWITHIN("
        "ST_GEOGPOINT(`{lng_col}`, `{lat_col}`), "
        "ST_GEOGPOINT({lng}, {lat}), {radius_m})"
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

        # Build property columns projection (with dialect-appropriate quoting)
        property_cols_sql = self._build_property_projection(profile.property_cols, driver=driver)

        count_sql: Optional[str] = None
        if profile.geom_col:
            geom_col = profile.geom_col
            if driver == "pg":
                sql = self._PG_PUSHDOWN_GEOM_TEMPLATE.format(
                    property_cols=property_cols_sql,
                    geom_col=geom_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m, cap=cap,
                )
                count_sql = self._PG_COUNT_GEOM_TEMPLATE.format(
                    geom_col=geom_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m,
                )
            else:  # bigquery
                sql = self._BQ_PUSHDOWN_GEOM_TEMPLATE.format(
                    property_cols=property_cols_sql,
                    geom_col=geom_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m, cap=cap,
                )
                count_sql = self._BQ_COUNT_GEOM_TEMPLATE.format(
                    geom_col=geom_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m,
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
                count_sql = self._PG_COUNT_LATLON_TEMPLATE.format(
                    lat_col=lat_col, lng_col=lng_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m,
                )
            else:  # bigquery
                sql = self._BQ_PUSHDOWN_LATLON_TEMPLATE.format(
                    property_cols=property_cols_sql,
                    lat_col=lat_col, lng_col=lng_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m, cap=cap,
                )
                count_sql = self._BQ_COUNT_LATLON_TEMPLATE.format(
                    lat_col=lat_col, lng_col=lng_col, table=table,
                    lat=lat, lng=lng, radius_m=radius_m,
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
            count_sql=count_sql,
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
    def _build_property_projection(property_cols: List[str], driver: str = "") -> str:
        """Build the SQL SELECT projection for property columns.

        Column identifiers are quoted per dialect so that reserved words (e.g.
        ``order``, ``type``) and names containing spaces or special characters
        are handled correctly:

        - PostgreSQL: ``"double_quotes"``
        - BigQuery: `` `backticks` ``
        - Other/unknown: unquoted (safe for most simple names)

        Args:
            property_cols: List of column names.
            driver: Normalised driver name (``"pg"``, ``"bigquery"``, etc.).

        Returns:
            Comma-separated, dialect-quoted column list, or ``'*'`` if empty.
        """
        if not property_cols:
            return "*"
        if driver == "pg":
            return ", ".join(f'"{col}"' for col in property_cols)
        if driver == "bigquery":
            return ", ".join(f"`{col}`" for col in property_cols)
        # Fallback: unquoted (non-spatial drivers go through pandas path)
        return ", ".join(property_cols)

    # ── execute() ────────────────────────────────────────────────────────

    async def execute(
        self,
        compiled: CompiledQuery,
        source: Any,
    ) -> Tuple[List[dict], int]:
        """Execute a compiled query against the given DataSource.

        Routes to the engine push-down or pandas fallback path based on
        ``compiled.path``.  Does NOT route through DatasetEntry.materialize
        (spec G4).

        Args:
            compiled: Output of compile().
            source: The DataSource for this dataset.

        Returns:
            Tuple of (features, true_count) where true_count is the total
            number of matching rows BEFORE any cap is applied.  When the
            engine path has a count_sql, true_count may exceed len(features).
        """
        if compiled.path == "engine":
            return await self._execute_engine(compiled, source)
        return await self._execute_pandas(compiled, source)

    async def _execute_engine(
        self,
        compiled: CompiledQuery,
        source: Any,
    ) -> Tuple[List[dict], int]:
        """Execute the engine push-down SQL via AsyncDB.

        When ``compiled.count_sql`` is set, runs a COUNT(*) query first to
        obtain the true number of matching rows (before the LIMIT cap), then
        runs the main query.  This allows ``total_count`` in the response to
        accurately reflect how many rows matched — not just how many were
        returned.

        Args:
            compiled: A CompiledQuery with path="engine".
            source: TableSource instance.

        Returns:
            Tuple of (features, true_count).  ``true_count`` is the number of
            rows that satisfied the spatial predicate before the LIMIT cap;
            ``features`` is the capped list of GeoJSON Feature dicts.

        Raises:
            RuntimeError: If either query fails.
        """
        from asyncdb import AsyncDB  # type: ignore[import]

        credentials, dsn = source._get_connection_args()

        if dsn:
            db = AsyncDB(source.driver, dsn=dsn)
        else:
            db = AsyncDB(source.driver, params=credentials)

        features: List[dict] = []
        true_count: int = 0

        async with await db.connection() as conn:
            conn.output_format("pandas")

            # Run COUNT(*) first if we have a count query (for true total_count)
            if compiled.count_sql:
                count_result, count_errors = await conn.query(compiled.count_sql)
                if count_errors:
                    logger.warning(
                        "SpatialCompiler: count query failed for '%s': %s — "
                        "true_count will fall back to len(features).",
                        compiled.profile_dataset, count_errors,
                    )
                else:
                    import pandas as _pd
                    if isinstance(count_result, _pd.DataFrame) and not count_result.empty:
                        true_count = int(count_result.iloc[0]["__count__"])

            result, errors = await conn.query(compiled.sql)

            if errors:
                raise RuntimeError(
                    f"SpatialCompiler engine query failed for "
                    f"'{compiled.profile_dataset}': {errors}"
                )

            if result is None or (hasattr(result, "empty") and result.empty):
                return features, true_count

            import pandas as _pd
            if isinstance(result, _pd.DataFrame):
                for _, row in result.iterrows():
                    feature = self._row_to_geojson_feature(
                        row=dict(row),
                        compiled=compiled,
                    )
                    if feature:
                        features.append(feature)

        # If count query was not available or failed, use returned feature count
        if true_count == 0:
            true_count = len(features)

        return features, true_count

    async def _execute_pandas(
        self,
        compiled: CompiledQuery,
        source: Any,
    ) -> Tuple[List[dict], int]:
        """Execute bbox prefilter + haversine refine for non-spatial backends.

        For InMemorySource: uses the in-memory DataFrame directly.
        For TableSource with non-spatial driver: fetches via AsyncDB with a
        BETWEEN WHERE clause, then refines with haversine.

        The true count (matches BEFORE cap) is recorded by counting the full
        haversine-refined result before slicing to ``compiled.cap``.

        Args:
            compiled: A CompiledQuery with path="pandas".
            source: DataSource instance (TableSource or InMemorySource).

        Returns:
            Tuple of (features[:cap], total_matches) where ``total_matches`` is
            the count of haversine-passing rows before the cap is applied.
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
            return [], 0

        # Haversine refine: keep only rows inside the exact circle
        df = self._haversine_refine(df, compiled)

        # Convert ALL surviving rows to GeoJSON features (count BEFORE cap)
        features: List[dict] = []
        for _, row in df.iterrows():
            feature = self._row_to_latlon_geojson_feature(
                row=dict(row),
                compiled=compiled,
            )
            if feature:
                features.append(feature)

        # Record the true match count before applying the cap
        total_matches = len(features)

        # Apply cap
        return features[:compiled.cap], total_matches

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
            # Over-fetch by 4× to account for haversine refinement loss: a bbox covers
            # ~(4/π ≈ 1.27) times the area of the inscribed circle, so corners add ~27%
            # extra rows.  The 4× factor is conservative to handle non-uniform data
            # distributions.  Configure ``bbox_overfetch_factor`` on SpatialCompiler
            # if a different multiplier is needed for a specific dataset.
            sql += f" LIMIT {compiled.cap * 4}"

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
