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

        Args:
            response: An AIMessage-like object with ``code``, ``data``,
                ``output``, and ``response`` attributes.
            environment: Rendering environment (unused; kept for protocol compat).
            **kwargs: Forwarded to base class (unused by this renderer).

        Returns:
            Tuple[Any, Optional[Any]]:
                - On success: ``(config_dict_without_data, None)``
                - On failure: ``(None, error_message_str)``
        """
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

        # 4. Route rows to response.data only if currently empty
        if not getattr(response, "data", None) and cfg.data:
            response.data = cfg.data

        # response.code is left untouched (renderer never sets it)
        return out, None

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
