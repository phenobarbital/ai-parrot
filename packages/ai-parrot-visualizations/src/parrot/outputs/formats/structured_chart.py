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
3. Put the data rows inside the JSON under "data" (a list of flat row dicts).
4. For xAxisMode="time", the x column values MUST be ISO 8601 date strings (e.g. "2024-01-15").
5. For type="map", mapName is required.
6. The y field is a list — include all series columns.

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
            # 1. Extract raw JSON string
            raw = getattr(response, "code", None)
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

            # 4. Route chart rows to response.data.
            #    cfg.data contains the rows the LLM selected and matched to
            #    x/y — they take priority over any raw DataFrame the agent
            #    placed in response.data before the renderer ran.
            #    Explicit None/empty check avoids DataFrame truthiness crash:
            #    `not response.data` raises "truth value of a DataFrame is
            #    ambiguous" when the agent pre-populated response.data with a
            #    pd.DataFrame.
            if cfg.data:
                # cfg.data rows always win — they match the chart config.
                response.data = cfg.data
            # else: leave response.data as-is (e.g. raw DataFrame from agent)

            # response.code is left untouched (renderer never sets it)
            return out, None

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error in StructuredChartRenderer: {exc}"
            logger.exception(msg)
            return None, msg

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
