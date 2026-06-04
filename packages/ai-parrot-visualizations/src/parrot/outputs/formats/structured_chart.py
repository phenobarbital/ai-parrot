"""FEAT-215 (FEAT-223 Module 2 / FEAT-224 Module 2): Structured Chart Output Mode renderer.

Validates LLM-emitted JSON into :class:`StructuredChartConfig`, sets
``response.output`` to the camelCase config dict **without the data key**, routes
data rows to ``response.data``, and leaves ``response.code`` untouched (null).

FEAT-223 deterministic refactor: rows come exclusively from the agent's DataFrame
(``response.data``), extracted via :class:`StructuredOutputBase._extract_rows`.
The LLM contributes **presentation only** (type, x, y, palette, color_by_sign, …);
it must NOT emit data rows.  If the LLM picks an absent x/y column, the renderer
applies a deterministic fallback so the frontend always receives a valid config.

FEAT-224 (Module 2 — G3): The renderer now reads its config from
``response.output`` / ``response.structured_output`` (where PandasAgent stores the
LLM's StructuredChartConfig) rather than from ``response.code``, which is reserved
for genuine interpretable Python/TS code.  ``response.code`` is no longer consulted
as a config source; a text-fallback path is retained for any client that sends
the raw JSON string in the response body.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Tuple

from .chart import BaseChart
from .structured_base import StructuredOutputBase
from . import register_renderer
from ...models.outputs import OutputMode, StructuredChartConfig
from ...outputs.formats.table_types import canonical_records


logger = logging.getLogger(__name__)

# ── System Prompt ─────────────────────────────────────────────────────────────

_SCHEMA = StructuredChartConfig.model_json_schema()

STRUCTURED_CHART_SYSTEM_PROMPT = f"""STRUCTURED CHART OUTPUT MODE

You are generating a structured chart configuration for the frontend.

REQUIREMENTS:
1. Data rows are provided automatically from the DataFrame you computed — do NOT
   emit rows.  Set "data" to an empty list [] (the backend reads from your tool
   output directly, so you do not need to retype the rows).
2. CRITICAL — column names: set "x" and "y" to the EXACT column names visible
   in your tool output (the DataFrame you computed).  These are matched against
   the real data at render time.  Do NOT invent semantic names like "category",
   "value", or "metric" unless those are the actual column headers — an absent
   column falls back to the first available column.
3. Emit ONLY a single JSON object matching the schema below — no prose, no
   markdown, no code fences.
4. For xAxisMode="time", the x column values MUST be ISO 8601 date strings.
5. For type="map", mapName is required.
6. The y field is a list — include all series column names.
7. ALWAYS include a short "title" (≤1 line, no trailing punctuation) and a
   one-paragraph "description" in natural language summarizing the chart's key
   takeaway (shown to the user next to the chart).
8. MANDATORY: set "dataVariable" to the exact variable name of your final pandas
   DataFrame (e.g. "chart_data").  If multiple DataFrames were produced, this
   tells the backend which one to use.

SCHEMA (your output must match this exactly):
{json.dumps(_SCHEMA, indent=2)}

OUTPUT FORMAT:
- Return ONLY the JSON object, starting with {{ and ending with }}.
- No explanatory text before or after the JSON.
- No markdown code blocks.
- All required fields (type, x, y) must be present.
"""


# ── Renderer ──────────────────────────────────────────────────────────────────


@register_renderer(OutputMode.STRUCTURED_CHART, system_prompt=STRUCTURED_CHART_SYSTEM_PROMPT)
class StructuredChartRenderer(StructuredOutputBase, BaseChart):
    """Library-agnostic chart renderer for the STRUCTURED_CHART output mode.

    Rows come **deterministically** from the agent's DataFrame injected into
    ``response.data`` (extracted via :meth:`StructuredOutputBase._extract_rows`).
    The LLM is responsible for presentation only: chart type, x/y column names,
    palette, color_by_sign, title, and description.  If the LLM picks a column
    absent from the real data, :meth:`_safe_x` / :meth:`_safe_y` apply a
    deterministic fallback so the frontend never receives an invalid config.

    The renderer always:

    - Sets ``response.data`` to the canonical ``list[dict]`` rows.
    - Returns ``(out_without_data, wrapped)`` — the config dict with ``data``
      excluded, paired with the chart description or prose explanation.
    - Returns ``(None, error_message)`` on any unrecoverable error — never raises.
    """

    async def render(
        self,
        response: Any,
        *,
        environment: str = "html",
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """Render a structured chart configuration from the LLM response.

        Pipeline (FEAT-224):
        1. Capture ``explanation`` from ``response.response`` (best-effort).
        2. Parse the LLM-emitted config into :class:`StructuredChartConfig`
           (three sources, in priority order):
           a. ``response.output`` — a StructuredChartConfig instance or dict.
           b. ``response.structured_output`` — same types as (a).
           c. Text fallback via :meth:`_extract_json_code` on response content.
           NOTE: ``response.code`` is NO LONGER consulted (G3).
        3. Extract real rows deterministically from ``response.data`` via
           :meth:`StructuredOutputBase._extract_rows` — **never** from ``cfg.data``.
        4. Serialize rows canonically via :func:`canonical_records`.
        5. Validate / fallback x/y against the real column set.
        6. Route via :meth:`StructuredOutputBase._route_envelope`.

        On any error: return ``(None, error_message)`` — never raise.

        Args:
            response: An AIMessage-like object with ``output``, ``structured_output``,
                ``data``, and ``response`` attributes.  ``code`` is ignored as a
                config source (FEAT-224 G3).
            environment: Rendering environment (unused; kept for protocol compat).
            **kwargs: Forwarded to base class (unused by this renderer).

        Returns:
            Tuple[Any, Optional[Any]]:
                - On success: ``(config_dict_without_data, description_or_explanation)``
                - On failure: ``(None, error_message_str)``
        """
        try:
            # 0. Preserve the pre-existing prose explanation.
            explanation: Optional[str] = getattr(response, "response", None) or None

            # 1. Parse presentation config from LLM.
            #    Sources (in priority order — FEAT-224 G3, response.code removed):
            #    a) response.output — StructuredChartConfig instance or dict
            #    b) response.structured_output — same types as (a)
            #    c) text fallback via _extract_json_code on response content
            cfg: Optional[StructuredChartConfig] = None

            # Prefer response.output; fall back to structured_output if output
            # is absent or is a plain string (non-structured turn).
            candidate = getattr(response, "output", None)
            if candidate is None or isinstance(candidate, str):
                candidate = getattr(response, "structured_output", None)

            # 1a. candidate is already a StructuredChartConfig instance (or duck-type)
            # Use duck-typing in addition to isinstance to handle cross-module
            # identity issues that can arise when different test suites load the
            # same module through different sys.path entries (FEAT-224 test isolation).
            _is_chart_cfg = isinstance(candidate, StructuredChartConfig) or (
                candidate is not None
                and not isinstance(candidate, (str, dict, list))
                and hasattr(candidate, "model_dump")
                and hasattr(candidate, "x")
                and hasattr(candidate, "y")
                and hasattr(candidate, "type")
            )
            if _is_chart_cfg:
                if not isinstance(candidate, StructuredChartConfig):
                    # Re-validate through the canonical class to normalise the object.
                    try:
                        candidate = StructuredChartConfig.model_validate(
                            candidate.model_dump(mode="python")
                        )
                    except Exception:  # noqa: BLE001
                        pass  # keep original; model_dump will still work
                cfg = candidate  # type: ignore[assignment]

            # 1b. candidate is a dict — validate into StructuredChartConfig
            elif isinstance(candidate, dict):
                try:
                    cfg = StructuredChartConfig.model_validate(candidate)
                except Exception as exc:
                    msg = f"Invalid structured chart config (dict): {exc}"
                    logger.warning(msg)
                    return None, msg

            # 1c. text fallback — extract JSON from response body
            if cfg is None:
                content = self._get_content(response)
                raw: Optional[str] = self._extract_json_code(content)

                if not raw:
                    msg = "No structured chart configuration found in response"
                    logger.warning(msg)
                    return None, msg

                try:
                    cfg = StructuredChartConfig.model_validate_json(raw)
                except Exception as exc:
                    msg = f"Invalid structured chart config: {exc}"
                    logger.warning(msg)
                    return None, msg

            # 2. Extract real rows deterministically from response.data.
            # NOTE: _extract_data looks at response.output first.  When output
            # holds a StructuredChartConfig (FEAT-224 new path), its .data field
            # is the LLM's presentation config payload — not the canonical row
            # source.  We pass a shim with output=None so _extract_data falls
            # through to response.data (the agent-injected DataFrame).
            _row_shim = type(
                "_RowShim", (), {"output": None, "data": getattr(response, "data", None)}
            )()
            df = self._extract_rows(_row_shim)
            if df is None:
                msg = "StructuredChartRenderer: no data available for chart"
                logger.warning(msg)
                return None, msg

            # 3. Serialize to canonical rows.
            rows, _, _ = canonical_records(df)

            # 4. Validate x/y against the real column set; deterministic fallback.
            real_cols = list(df.columns)
            x = self._safe_x(cfg.x, real_cols, rows)
            y = self._safe_y(cfg.y, x, real_cols, rows)

            logger.info(
                "structured_chart render: type=%s x=%r y=%r data_cols=%s rows=%d",
                cfg.type, x, y, real_cols, len(rows),
            )

            # 5. Inject final x/y + canonical rows, then route via shared envelope.
            final_cfg = cfg.model_copy(update={"x": x, "y": y, "data": rows})
            return self._route_envelope(response, final_cfg, final_cfg.description or explanation)

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error in StructuredChartRenderer: {exc}"
            logger.exception(msg)
            return None, msg

    # ── x/y safety helpers ────────────────────────────────────────────────────

    def _safe_x(self, x_hint: str, cols: list, rows: list) -> str:
        """Return *x_hint* when it names a real column; otherwise fallback.

        Fallback priority: first non-numeric column, then the first column.

        Args:
            x_hint: The LLM-chosen x column name.
            cols: The real DataFrame column list.
            rows: Canonical row list (first row used for type-sniffing).

        Returns:
            A column name that exists in *cols*.
        """
        if x_hint in cols:
            return x_hint
        first = rows[0] if rows else {}
        categorical = next(
            (c for c in cols if not self._is_numeric(first.get(c))), None
        )
        return categorical or cols[0]

    def _safe_y(
        self, y_hint: list, x: str, cols: list, rows: list
    ) -> list:
        """Return valid y columns from *y_hint*; apply deterministic fallback.

        Filters index-like columns in both the configured and fallback paths.

        Args:
            y_hint: The LLM-chosen y column names.
            x: The resolved x column (excluded from y).
            cols: The real DataFrame column list.
            rows: Canonical row list (first row used for type-sniffing).

        Returns:
            A list of column names that exist in *cols* (possibly empty on failure).
        """
        col_set = set(cols)
        first = rows[0] if rows else {}

        # Keep configured y-cols that exist and are not index-like.
        present_y = [
            c for c in y_hint
            if c in col_set and not self._is_index_like(c)
        ]

        if not present_y:
            # Fallback: numeric columns that are not x and not index-like.
            present_y = [
                c for c in cols
                if c != x
                and self._is_numeric(first.get(c))
                and not self._is_index_like(c)
            ]

        return present_y if present_y else y_hint

    @staticmethod
    def _is_numeric(v: Any) -> bool:
        """Return True when *v* is a non-boolean number."""
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    @staticmethod
    def _is_index_like(col: Any) -> bool:
        """Return True when *col* looks like a leaked pandas row index."""
        return str(col).strip().lower() in {"index", "level_0", "unnamed: 0", ""}

    # ── Abstract method stub (BaseChart requires this) ────────────────────────

    def _render_chart_content(self, chart_obj: Any, **kwargs) -> str:
        """Not used by StructuredChartRenderer (no HTML output).

        Args:
            chart_obj: Unused.
            **kwargs: Unused.

        Returns:
            Empty string.
        """
        return ""
