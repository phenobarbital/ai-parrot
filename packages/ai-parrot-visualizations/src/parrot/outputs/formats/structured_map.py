"""FEAT-221: Structured Map Output Mode renderer.

Deterministically converts a per-dataset ``SpatialResult`` (in ``response.data``)
into a :class:`~parrot.models.outputs.StructuredMapConfig`, sets ``response.data``
to the per-layer payload, and returns ``(out_without_data, explanation)`` so the
HTTP envelope mirrors the STRUCTURED_TABLE / STRUCTURED_CHART shape.

Key design decisions (mirroring StructuredTableRenderer):
- The **deterministic layer owns data + base schema** — no LLM involvement for
  core column types.
- Presentation metadata (columns, tooltip, label) derives from ``DatasetSpatialProfile``
  registry (deterministic wins).
- An **optional LLM-refine pass** may annotate ambiguous (``string``/``integer``)
  columns with finer ``format`` hints.  Hard types (``number``, ``datetime``,
  ``boolean``) are NEVER changed by the LLM.
- If the refine pass fails/times out, the renderer falls back to the deterministic-only
  schema and never raises.
- Renderer never raises — on any error it returns ``(None, error_message)``.
- Empty layer (zero features) is still emitted as a ``MapLayer`` with an empty payload.
- Both ``data_shape="geojson"`` and ``data_shape="rows"`` are supported per-layer.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .chart import BaseChart
from . import register_renderer
from ...models.outputs import (
    OutputMode,
    StructuredMapConfig,
    MapLayer,
    MapColumn,
    MapViewport,
    MapQuery,
)
from ...outputs.formats.table_types import base_column_types


logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

#: Base types that are NOT ambiguous — LLM may NOT change these.
_HARD_TYPES: frozenset[str] = frozenset({"number", "datetime", "boolean"})

#: Allowed finer format hints the LLM may add to ambiguous columns.
_ALLOWED_FORMATS: frozenset[str] = frozenset(
    {"currency", "percent", "email", "uri", "enum", "id", "code"}
)

# ── System Prompt ─────────────────────────────────────────────────────────────

STRUCTURED_MAP_SYSTEM_PROMPT = """\
STRUCTURED MAP OUTPUT MODE

You are generating structured map metadata for the frontend.

The data rows and base column types have already been determined deterministically.
Your task is ONLY to add optional format hints to ambiguous columns in a map layer.

INSTRUCTIONS:
1. You will receive a list of columns with their base types.
2. For columns whose base type is "string" or "integer", you MAY add a "format" hint.
3. Valid format hints: currency, percent, email, uri, enum, id, code
4. You MUST NOT change a column's base type — only add/suggest a format hint.
5. Return ONLY a JSON object mapping column names to their suggested format hints.
   Example: {"price": "currency", "rate": "percent", "user_id": "id"}
6. Omit columns where no format hint applies.

OUTPUT FORMAT:
- Return ONLY a JSON object, starting with { and ending with }.
- No prose, no markdown fences.
- Empty object {} if no hints apply.
"""


# ── Renderer ──────────────────────────────────────────────────────────────────


@register_renderer(OutputMode.STRUCTURED_MAP, system_prompt=STRUCTURED_MAP_SYSTEM_PROMPT)
class StructuredMapRenderer(BaseChart):
    """Library-agnostic map renderer for the STRUCTURED_MAP output mode (FEAT-221).

    Reads the per-dataset ``SpatialResult`` from ``response.data``, builds one
    ``MapLayer`` per dataset deterministically (columns from
    ``DatasetSpatialProfile.property_cols`` typed via
    :func:`~parrot.outputs.formats.table_types.base_column_types`, tooltip from
    the profile hints), optionally refines labels/format hints via a narrow LLM
    pass (deterministic wins), computes the viewport from feature bounds, and
    returns ``(out_without_data, explanation)``.

    The renderer always:

    - Sets ``response.data`` to the per-layer payload list.
    - Returns ``(out_without_data, explanation)`` — the structured-map config
      dict with the ``data`` key excluded, paired with the prose explanation.
    - Returns ``(None, error_message)`` on any unrecoverable error — never raises.
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the renderer.

        Args:
            **kwargs: Forwarded to the base renderer.
        """
        super().__init__(**kwargs)

    async def render(
        self,
        response: Any,
        *,
        environment: str = "html",
        row_limit: Optional[int] = None,
        **kwargs: Any,
    ) -> Tuple[Any, Optional[Any]]:
        """Render a structured map configuration from the agent response.

        Pipeline:
        1. Capture ``explanation`` from ``response.response`` (best-effort).
        2. Read the ``SpatialResult`` from ``response.data``.
        3. For each dataset/layer: build ``MapColumn`` list, payload, ``MapLayer``.
        4. Optional LLM-refine pass for ambiguous column format hints.
        5. Compute ``MapViewport`` from feature bounds.
        6. Build ``MapQuery`` from originating ``SpatialFilterSpec`` (if present).
        7. Build ``StructuredMapConfig``; exclude ``data`` from output.
        8. Set ``response.data`` to the per-layer payload list; return ``(out, explanation)``.

        On any error: return ``(None, error_message)`` — never raise.

        Args:
            response: An AIMessage-like object with ``data``, ``output``,
                and ``response`` attributes.
            environment: Rendering environment (unused; kept for protocol compat).
            row_limit: Optional per-layer row cap for ``data_shape="rows"`` layers.
            **kwargs: Unused.

        Returns:
            Tuple[Any, Optional[Any]]:
                - On success: ``(config_dict_without_data, explanation_or_None)``
                - On failure: ``(None, error_message_str)``
        """
        try:
            effective_row_limit = row_limit if row_limit is not None else 1000

            # Step 1: Capture explanation from the producing agent.
            explanation: Optional[str] = getattr(response, "response", None) or None

            # Step 2: Read the SpatialResult from response.data.
            spatial_result = getattr(response, "data", None)
            if spatial_result is None:
                msg = "StructuredMapRenderer: response.data is None — no SpatialResult to render"
                logger.warning(msg)
                return None, msg

            # Accept either a SpatialResult instance or a dict with 'layers'
            try:
                from ...tools.dataset_manager.spatial.contracts import SpatialResult
            except ImportError:
                msg = "StructuredMapRenderer: could not import SpatialResult"
                logger.warning(msg)
                return None, msg

            if isinstance(spatial_result, dict) and "layers" in spatial_result:
                try:
                    spatial_result = SpatialResult(**spatial_result)
                except Exception as exc:
                    msg = f"StructuredMapRenderer: failed to parse spatial_result dict: {exc}"
                    logger.warning(msg)
                    return None, msg

            if not isinstance(spatial_result, SpatialResult):
                msg = (
                    f"StructuredMapRenderer: response.data must be a SpatialResult, "
                    f"got {type(spatial_result).__name__}"
                )
                logger.warning(msg)
                return None, msg

            # Attempt to load profile registry (fail-open: renderer continues without profiles)
            try:
                from ...tools.dataset_manager.spatial.registry import get_spatial_profile
                _profiles_available = True
            except ImportError:
                _profiles_available = False
                get_spatial_profile = None  # type: ignore[assignment]

            # Step 3: Build one MapLayer per dataset.
            layers: List[MapLayer] = []
            all_payloads: List[Dict] = []

            for dataset_name, layer_result in spatial_result.layers.items():
                # Load profile for this dataset (fail-open: empty columns if absent)
                profile = None
                if _profiles_available and get_spatial_profile is not None:
                    try:
                        profile = get_spatial_profile(dataset_name)
                    except (ValueError, Exception):
                        pass  # Profile not found — use fallbacks

                # Determine data_shape for this layer
                data_shape: str = "geojson"
                if profile is not None:
                    data_shape = profile.default_data_shape

                # Build columns from feature.properties
                columns: List[MapColumn] = self._build_columns(
                    layer_result.features,
                    profile=profile,
                    row_limit=effective_row_limit,
                )

                # Optional LLM-refine pass
                columns = await self._apply_llm_refine(columns, response)

                # Build per-layer payload
                if data_shape == "rows":
                    payload = self._build_rows_payload(
                        layer_result.features,
                        row_limit=effective_row_limit,
                    )
                else:
                    payload = {
                        "type": "FeatureCollection",
                        "features": layer_result.features[:effective_row_limit],
                    }

                # Tooltip and label from profile hints
                tooltip_template: Optional[str] = None
                label_field: Optional[str] = None
                if profile is not None:
                    tooltip_template = (
                        profile.tooltip_template or profile.description_template or None
                    )
                    label_field = profile.label_col

                map_layer = MapLayer(
                    layer=layer_result.layer,
                    columns=columns,
                    tooltip_template=tooltip_template,
                    label_field=label_field,
                    data_shape=data_shape,  # type: ignore[arg-type]
                    total_count=layer_result.total_count,
                    capped=layer_result.capped,
                    geodesic=layer_result.geodesic,
                )
                layers.append(map_layer)
                all_payloads.append(
                    {
                        "dataset": dataset_name,
                        "layer": layer_result.layer,
                        "data_shape": data_shape,
                        "payload": payload,
                    }
                )

            # Step 5: Compute viewport from feature bounds.
            viewport = self._compute_viewport(spatial_result)

            # Step 6: Build MapQuery from SpatialFilterSpec (if present in response).
            query = self._extract_map_query(response)

            # Step 7: Build StructuredMapConfig (with data list for potential validation skip).
            try:
                cfg = StructuredMapConfig(
                    layers=layers,
                    data=[],  # data is in all_payloads; skip column-name validator
                    viewport=viewport,
                    query=query,
                    explanation=explanation,
                )
            except Exception as exc:
                msg = f"StructuredMapRenderer: config build failed: {exc}"
                logger.warning(msg)
                return None, msg

            # Step 8: Exclude data from output; route per-layer payloads to response.data.
            out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})

            if all_payloads:
                response.data = all_payloads

            return out, explanation

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error in StructuredMapRenderer: {exc}"
            logger.exception(msg)
            return None, msg

    # ── Column building ────────────────────────────────────────────────────────

    def _build_columns(
        self,
        features: List[Dict],
        *,
        profile: Any,
        row_limit: int,
    ) -> List[MapColumn]:
        """Build ``MapColumn`` list from feature properties.

        Args:
            features: GeoJSON Feature list for this layer.
            profile: ``DatasetSpatialProfile`` (may be None).
            row_limit: Max rows to use for type inference.

        Returns:
            List of ``MapColumn`` instances, or empty list when no properties.
        """
        if not features:
            # Empty layer — still emit columns from profile if available
            if profile is not None and profile.property_cols:
                return [
                    MapColumn(
                        name=col,
                        type="any",
                        title=profile.column_titles.get(col, col),
                        format=profile.column_formats.get(col) or None,
                    )
                    for col in profile.property_cols
                ]
            return []

        # Determine which columns to include
        if profile is not None and profile.property_cols:
            prop_cols = profile.property_cols
        else:
            # Derive from first feature's properties
            first_props = features[0].get("properties") or {}
            prop_cols = list(first_props.keys())

        # Build a DataFrame from properties for type inference
        rows = [
            feat.get("properties") or {}
            for feat in features[:row_limit]
        ]
        if rows and prop_cols:
            try:
                df = pd.DataFrame(rows)[prop_cols]
                col_types = base_column_types(df)
            except Exception:
                col_types = {}
        else:
            col_types = {}

        columns: List[MapColumn] = []
        for col in prop_cols:
            # Profile may override title and format
            title = col
            fmt: Optional[str] = None
            if profile is not None:
                title = profile.column_titles.get(col, col)
                fmt = profile.column_formats.get(col) or None
            columns.append(
                MapColumn(
                    name=col,
                    type=col_types.get(col, "any"),
                    title=title,
                    format=fmt,
                )
            )
        return columns

    # ── Row payload builder ────────────────────────────────────────────────────

    @staticmethod
    def _build_rows_payload(
        features: List[Dict],
        *,
        row_limit: int,
    ) -> Dict:
        """Flatten GeoJSON features to a rows+columns+geometry-ref payload.

        Args:
            features: GeoJSON Feature list.
            row_limit: Maximum rows to include.

        Returns:
            Dict with ``rows`` (list of flat dicts, each including a ``_geometry``
            key with the GeoJSON geometry) and ``truncated`` flag.
        """
        rows = []
        for feat in features[:row_limit]:
            props = dict(feat.get("properties") or {})
            geom = feat.get("geometry")
            if geom:
                props["_geometry"] = geom
            rows.append(props)
        return {
            "rows": rows,
            "truncated": len(features) > row_limit,
        }

    # ── Viewport computation ───────────────────────────────────────────────────

    @staticmethod
    def _compute_viewport(spatial_result: Any) -> Optional[MapViewport]:
        """Compute MapViewport (bbox + center) from all feature coordinates.

        Args:
            spatial_result: A ``SpatialResult`` instance.

        Returns:
            A ``MapViewport`` with ``bbox`` and optional ``center``, or ``None``
            if no coordinates are found.
        """
        lngs: List[float] = []
        lats: List[float] = []

        for layer_result in spatial_result.layers.values():
            for feat in layer_result.features:
                geom = feat.get("geometry") or {}
                geom_type = geom.get("type", "")
                coords = geom.get("coordinates")
                if coords is None:
                    continue
                try:
                    if geom_type == "Point":
                        lng, lat = float(coords[0]), float(coords[1])
                        lngs.append(lng)
                        lats.append(lat)
                    elif geom_type in ("LineString", "MultiPoint"):
                        for c in coords:
                            lngs.append(float(c[0]))
                            lats.append(float(c[1]))
                    elif geom_type in ("Polygon", "MultiLineString"):
                        for ring in coords:
                            for c in ring:
                                lngs.append(float(c[0]))
                                lats.append(float(c[1]))
                    elif geom_type == "MultiPolygon":
                        for polygon in coords:
                            for ring in polygon:
                                for c in ring:
                                    lngs.append(float(c[0]))
                                    lats.append(float(c[1]))
                except (IndexError, TypeError, ValueError):
                    continue

        if not lats or not lngs:
            return None

        min_lng, max_lng = min(lngs), max(lngs)
        min_lat, max_lat = min(lats), max(lats)
        center_lat = (min_lat + max_lat) / 2.0
        center_lng = (min_lng + max_lng) / 2.0

        return MapViewport(
            bbox=[min_lng, min_lat, max_lng, max_lat],
            center=(center_lat, center_lng),
        )

    # ── MapQuery extraction ────────────────────────────────────────────────────

    @staticmethod
    def _extract_map_query(response: Any) -> Optional[MapQuery]:
        """Extract MapQuery from the response's spatial filter spec (if present).

        Args:
            response: The AIMessage-like response object.

        Returns:
            A ``MapQuery`` if a ``SpatialFilterSpec`` can be found; ``None``
            otherwise.  Never raises.
        """
        # Try response.spatial_filter_spec (PandasAgent may attach it)
        spec = getattr(response, "spatial_filter_spec", None)
        if spec is None:
            return None
        try:
            return MapQuery(
                point=spec.point,
                radius=spec.radius,
                unit=spec.unit,
            )
        except Exception:
            return None

    # ── LLM-refine pass ────────────────────────────────────────────────────────

    async def _apply_llm_refine(
        self,
        columns: List[MapColumn],
        response: Any,
    ) -> List[MapColumn]:
        """Optionally refine ambiguous column format hints via a narrow LLM pass.

        The LLM may ONLY suggest a ``format`` hint for columns whose base type
        is ``"string"`` or ``"integer"``.  Hard types (``number``, ``datetime``,
        ``boolean``) are NEVER touched.  **Deterministic wins**.

        If the refine pass fails for any reason, the deterministic-only schema
        (original ``columns``) is returned unchanged.

        Args:
            columns: The deterministically-derived column list.
            response: The AIMessage-like response object (checked for ``code``).

        Returns:
            The refined column list, or the original list on any error.
        """
        ambiguous = [c for c in columns if c.type in ("string", "integer")]
        if not ambiguous:
            return columns

        raw_code = getattr(response, "code", None)
        if raw_code is None:
            return columns

        hints: Optional[dict] = None
        try:
            if isinstance(raw_code, dict):
                hints = raw_code
            elif isinstance(raw_code, str):
                raw_code_stripped = raw_code.strip()
                extracted = self._extract_json_code(raw_code_stripped)
                if extracted:
                    hints = json.loads(extracted)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "StructuredMapRenderer: LLM refine parse failed (falling back): %s", exc
            )
            return columns

        if not hints or not isinstance(hints, dict):
            return columns

        col_map = {c.name: c for c in columns}
        for col_name, fmt in hints.items():
            col = col_map.get(col_name)
            if col is None:
                continue
            if col.type in _HARD_TYPES:
                logger.debug(
                    "StructuredMapRenderer: LLM tried to annotate hard-typed "
                    "column %r (type=%r) — ignored (deterministic wins)",
                    col_name, col.type,
                )
                continue
            if fmt not in _ALLOWED_FORMATS:
                logger.debug(
                    "StructuredMapRenderer: LLM suggested unknown format %r "
                    "for column %r — ignored",
                    fmt, col_name,
                )
                continue
            col_map[col_name] = MapColumn(
                name=col.name,
                type=col.type,
                title=col.title,
                format=fmt,
            )

        return list(col_map.values())

    # ── JSON extraction helper ─────────────────────────────────────────────────

    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:
        """Extract a JSON object string from markdown code blocks or bare text.

        Args:
            content: Raw text that may contain embedded JSON.

        Returns:
            The extracted JSON string, or ``None`` if nothing suitable was found.
        """
        pattern = r"```json\n(.*?)```"
        if matches := re.findall(pattern, content, re.DOTALL):
            return matches[0].strip()

        pattern = r"```\n(.*?)```"
        if matches := re.findall(pattern, content, re.DOTALL):
            potential = matches[0].strip()
            if potential.startswith("{") or potential.startswith("["):
                return potential

        content = content.strip()
        if content.startswith("{") and content.endswith("}"):
            return content

        return None

    # ── Abstract method stub (BaseChart requires this) ────────────────────────

    def _render_chart_content(self, chart_obj: Any, **kwargs: Any) -> str:
        """Not used by StructuredMapRenderer (no HTML output).

        Args:
            chart_obj: Unused.
            **kwargs: Unused.

        Returns:
            Empty string.
        """
        return ""
