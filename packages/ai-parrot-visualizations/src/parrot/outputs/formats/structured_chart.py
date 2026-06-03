"""FEAT-215: Structured Chart Output Mode renderer.

Validates LLM-emitted JSON into :class:`StructuredChartConfig`, sets
``response.output`` to the camelCase config dict **without the data key**, routes
data rows to ``response.data``, and leaves ``response.code`` untouched (null).

No HTML generation, no ECharts/Altair dependency, no retry logic.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Tuple

from .chart import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode, StructuredChartConfig


logger = logging.getLogger(__name__)

# ── System Prompt ─────────────────────────────────────────────────────────────

_SCHEMA = StructuredChartConfig.model_json_schema()

STRUCTURED_CHART_SYSTEM_PROMPT = f"""STRUCTURED CHART OUTPUT MODE

You are generating a structured chart configuration for the frontend.

REQUIREMENTS:
1. Use available tools (e.g. database_query) to FETCH real data first, then map columns.
   - **IMPORTANT**: Do NOT ask the user for data if you can fetch it yourself.
   - First, fetch the data using the appropriate tool.
   - Then map the fetched column names to x/y in the config.
2. Emit ONLY a single JSON object matching the schema below — no prose, no markdown, no code fences.
3. CRITICAL — column names: set "x" and "y" to the EXACT column names of the
   DataFrame you computed with your tools (the column headers shown in your tool
   output). These names are matched against the real data, which the system takes
   directly from the DataFrame you computed. Do NOT invent semantic names such as
   "category", "metric" or "value" unless those are the actual column headers —
   a name that is not a real column produces an empty chart. The "data" field is
   OPTIONAL: you may leave it as an empty list [], because the system uses the
   DataFrame you computed as the data source (you do not need to retype the rows).
   MANDATORY data-delivery convention: your LAST tool call before emitting the
   JSON MUST be a `python_repl_pandas` step that assigns the exact, final chart
   rows to a flat pandas DataFrame named EXACTLY `chart_data`, and you MUST set
   "dataVariable": "chart_data". If you obtained the data with
   `dataset_fetch_dataset`, `database_query` or SQL, load/rebuild it into
   `chart_data` in that final step (e.g. `chart_data = <your_dataframe>`). This is
   what guarantees the rows reach the chart — data fetched only via
   `dataset_fetch_dataset` and NOT placed into `chart_data` may not render. The
   columns of `chart_data` MUST include your x and y.
4. For xAxisMode="time", the x column values MUST be ISO 8601 date strings (e.g. "2024-01-15").
5. For type="map", mapName is required.
6. The y field is a list — include all series columns.
7. ALWAYS include a short "title" (≤1 line, no trailing punctuation) and a one-paragraph
   "description" in natural language summarizing the chart's key takeaway (this is the text
   shown to the user next to the chart).

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
class StructuredChartRenderer(BaseChart):
    """Library-agnostic chart renderer for the STRUCTURED_CHART output mode.

    Validates the LLM's JSON response into :class:`StructuredChartConfig` and
    populates the response envelope:

    - ``response.output`` — camelCase config dict **without** the ``data`` key.
    - ``response.data`` — flat data rows (only populated when currently empty).
    - ``response.code`` — left untouched (remains null).

    On any parse or validation error the renderer returns ``(None, message)``
    without raising, enabling graceful degradation in the UI.
    """

    async def render(
        self,
        response: Any,
        *,
        environment: str = "html",
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """Render a structured chart configuration from the LLM response.

        Reads ``response.code`` first; falls back to JSON extraction from the
        message text. Validates the result into :class:`StructuredChartConfig`.

        **Data-placement contract**: ``cfg.data`` (the rows the LLM included
        in its JSON, matched to the chart's x/y columns) **always wins** over
        any raw DataFrame that a PandasAgent may have placed in
        ``response.data`` before the renderer runs.  This is intentional:
        PandasAgent sets ``response.data`` to the full tool-local DataFrame
        (potentially hundreds of rows with arbitrary columns), which is
        unsuitable for chart rendering.  The LLM is responsible for selecting
        and packaging only the relevant rows inside the structured JSON; the
        renderer trusts that selection.

        If ``cfg.data`` is empty (the LLM omitted the ``data`` key), the
        pre-existing ``response.data`` is left untouched so that callers
        (e.g. a generic DataFrame table view) can still use it.

        Args:
            response: An AIMessage-like object with ``code``, ``data``,
                ``output``, and ``response`` attributes.  ``response.data``
                may be a ``pd.DataFrame`` at call time (set by PandasAgent
                before the formatter runs); the renderer replaces it with a
                plain ``list[dict]`` when ``cfg.data`` is non-empty.
            environment: Rendering environment (unused; kept for protocol compat).
            **kwargs: Forwarded to base class (unused by this renderer).

        Returns:
            Tuple[Any, Optional[Any]]:
                - On success: ``(config_dict_without_data, None)``
                - On failure: ``(None, error_message_str)``
        """
        try:
            # 0. Capture the pre-existing explanation so we can surface it as
            #    the human-readable message even after data.py overwrites
            #    response.response with the renderer's `wrapped` return value.
            #    When PandasAgent processes the turn it sets
            #    response.response = PandasAgentResponse.explanation before
            #    calling the formatter; we must preserve that text.
            explanation: Optional[str] = getattr(response, "response", None) or None

            # 1. Extract raw JSON — three sources, in priority order:
            #    a) response.code as a dict (PandasAgentResponse.code may carry
            #       the chart config as a pre-parsed dict when the LLM returns
            #       a JSON object in the `code` field rather than Python code)
            #    b) response.code as a string (chart JSON or embedded in text)
            #    c) response.response / content (explanation text may contain
            #       the JSON object)
            raw_code = getattr(response, "code", None)

            cfg: Optional[StructuredChartConfig] = None

            # 1a. response.code is already a dict → validate directly
            if isinstance(raw_code, dict):
                try:
                    cfg = StructuredChartConfig.model_validate(raw_code)
                except Exception as exc:
                    msg = f"Invalid structured chart config (dict): {exc}"
                    logger.warning(msg)
                    return None, msg

            # 1b. response.code is a string → try JSON extraction
            if cfg is None:
                raw: Optional[str] = raw_code if isinstance(raw_code, str) else None
                if not raw:
                    content = self._get_content(response)
                    raw = self._extract_json_code(content)

                if not raw:
                    msg = "No structured chart configuration found in response"
                    logger.warning(msg)
                    return None, msg

                # 2. Validate into StructuredChartConfig
                try:
                    cfg = StructuredChartConfig.model_validate_json(raw)
                except Exception as exc:
                    msg = f"Invalid structured chart config: {exc}"
                    logger.warning(msg)
                    return None, msg

            # 3. Build output — camelCase, data key excluded
            out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})

            # 4. Resolve the data rows and reconcile the config's x/y columns.
            #    Reality (FEAT-215): the LLM does NOT reliably embed rows — it
            #    emits a placeholder like `[{}]` even when asked. The
            #    authoritative data is the DataFrame the agent computed, which
            #    PandasAgent injects into ``response.data`` *before* the renderer
            #    runs. We pick the best available rows, then ensure out["x"] /
            #    out["y"] name columns that actually exist in those rows —
            #    otherwise the frontend (LayerChart) builds a scale over
            #    `undefined` and renders nothing.
            rows = self._resolve_rows(cfg, getattr(response, "data", None))
            if rows:
                self._reconcile_columns(out, cfg, rows)
                response.data = rows
            # else: no usable rows — leave response.data as-is (the frontend
            # shows a graceful "no data" fallback).

            # Diagnostic: log the FINAL config axes vs the actual data columns so
            # a config/data mismatch (the frontend "columns don't match" guard)
            # can be pinpointed from the server log without guesswork.
            logger.info(
                "structured_chart render: type=%s x=%r y=%r data_cols=%s rows=%d",
                out.get("type"),
                out.get("x"),
                out.get("y"),
                list(rows[0].keys()) if rows else None,
                len(rows) if rows else 0,
            )

            # response.code is left untouched (renderer never sets it)
            # Return the natural-language text as `wrapped` so that data.py's
            #   response.response = wrapped
            # surfaces it as the message body. Prefer the config's own
            # `description` (the LLM's chart summary); fall back to any
            # pre-existing explanation the agent set before the renderer ran.
            return out, (cfg.description or explanation)

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error in StructuredChartRenderer: {exc}"
            logger.exception(msg)
            return None, msg

    # ── Data resolution + column reconciliation ──────────────────────────────

    @staticmethod
    def _resolve_rows(cfg: StructuredChartConfig, existing: Any) -> Optional[list]:
        """Pick the authoritative data rows for the chart.

        Priority:
            1. Real rows the LLM embedded in ``cfg.data`` (non-empty first row).
            2. The agent-injected pandas DataFrame in ``response.data``
               (converted to records). Duck-typed (``to_dict`` + ``empty``) so
               this module doesn't need to import pandas.
            3. A pre-existing plain ``list[dict]`` with a non-empty first row.

        Args:
            cfg: The validated chart configuration.
            existing: The current ``response.data`` (may be a DataFrame, list,
                or None).

        Returns:
            A list of row dicts, or ``None`` when nothing usable is available.
        """
        # 1. LLM embedded real rows
        if cfg.data and cfg.data[0]:
            return cfg.data
        # 2. Agent-injected pandas DataFrame (duck-typed)
        if existing is not None and hasattr(existing, "to_dict") and hasattr(existing, "empty"):
            return None if existing.empty else existing.to_dict("records")
        # 3. Pre-existing list of non-empty dicts
        if isinstance(existing, list) and existing and existing[0]:
            return existing
        return None

    @staticmethod
    def _reconcile_columns(
        out: dict, cfg: StructuredChartConfig, rows: list
    ) -> None:
        """Ensure ``out['x']`` and ``out['y']`` reference columns present in rows.

        The LLM frequently names semantic axes (e.g. ``x="category"``) that do
        not match the real DataFrame columns. When a configured column is absent
        we infer a sensible replacement from the data: the first non-numeric
        column becomes ``x`` and the numeric columns become ``y``. This mutates
        ``out`` in place so the frontend receives a config whose x/y exist in
        ``response.data``.

        Index-like columns (``index``, ``level_0``, ``Unnamed: 0``) — typically
        the pandas row index that leaked in via ``reset_index`` or dataset
        materialization — are never used as a ``y`` series: they are row counters,
        not metrics, and would otherwise show up as a meaningless extra series in
        the legend (e.g. an "index" entry alongside "total_amount").

        Args:
            out: The camelCase config dict (mutated in place).
            cfg: The validated chart configuration (source x/y).
            rows: The resolved data rows (first row used for column inference).
        """
        first = rows[0]
        cols = list(first.keys())
        col_set = set(cols)

        def _is_number(v: Any) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        def _is_index_like(c: Any) -> bool:
            return str(c).strip().lower() in {"index", "level_0", "unnamed: 0", ""}

        # x: keep when present, else first non-numeric column, else first column.
        if cfg.x not in col_set:
            categorical = next(
                (c for c in cols if not _is_number(first.get(c))), None
            )
            out["x"] = categorical or cols[0]

        # y: keep the configured columns that exist and are real metrics (drop
        # index-like columns); otherwise infer from the numeric columns. Either
        # way, never emit an index column as a series.
        present_y = [
            c for c in cfg.y if c in col_set and not _is_index_like(c)
        ]
        if not present_y:
            x_col = out.get("x")
            present_y = [
                c
                for c in cols
                if c != x_col and _is_number(first.get(c)) and not _is_index_like(c)
            ]
        if present_y:
            out["y"] = present_y

    # ── JSON extraction helper (mirrors EChartsRenderer._extract_json_code) ──

    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:
        """Extract a JSON object string from markdown code blocks or bare text.

        Tries (in order):
        1. Fenced ```json ... ``` block.
        2. Generic fenced ``` ... ``` block that looks like JSON.
        3. The content itself, if it starts with ``{`` and ends with ``}``.

        Args:
            content: Raw text that may contain embedded JSON.

        Returns:
            The extracted JSON string, or ``None`` if nothing suitable was found.
        """
        # 1. Explicit JSON code block
        pattern = r"```json\n(.*?)```"
        if matches := re.findall(pattern, content, re.DOTALL):
            return matches[0].strip()

        # 2. Generic code block — accept if it looks like JSON
        pattern = r"```\n(.*?)```"
        if matches := re.findall(pattern, content, re.DOTALL):
            potential = matches[0].strip()
            if potential.startswith("{") or potential.startswith("["):
                return potential

        # 3. Bare JSON
        content = content.strip()
        if content.startswith("{") and content.endswith("}"):
            return content

        return None

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
