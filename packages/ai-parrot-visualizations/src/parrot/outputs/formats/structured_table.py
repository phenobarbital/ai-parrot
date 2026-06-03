"""FEAT-218: Structured Table Output Mode renderer.

Deterministically converts an agent response (DataFrame in ``response.data`` or
``response.output``) into a :class:`~parrot.models.outputs.StructuredTableConfig`,
sets ``response.data`` to the canonical row list, and returns
``(out_without_data, explanation)`` so the HTTP envelope mirrors the
STRUCTURED_CHART shape.

Key design decisions (Option C from the brainstorm):
- The **deterministic layer owns data + base schema** — no LLM involvement for
  core types.
- An **optional LLM-refine pass** may annotate ambiguous (``string``/``integer``)
  columns with finer ``format`` hints (``currency``/``percent``/``id``/``code``).
  The LLM cannot change a hard base type; on conflict, **deterministic wins**.
- If the refine pass fails/times out, the renderer falls back to the
  deterministic-only schema and never raises.
- Renderer never raises — on any error it returns ``(None, error_message)``,
  mirroring ``StructuredChartRenderer``.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Tuple

from .chart import BaseChart
from . import register_renderer
from ...models.outputs import OutputMode, StructuredTableConfig, TableColumn
from ...outputs.formats.table import TableRenderer
from ...outputs.formats.table_types import base_column_types, canonical_records


logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

#: Default maximum rows per response (configurable via ``row_limit`` kwarg).
DEFAULT_ROW_LIMIT: int = 1000

#: Base types that are NOT ambiguous — LLM may NOT change these.
#: NOTE: "integer" is intentionally excluded — integer columns CAN receive
#: format hints ("id", "code") from the LLM refine pass.  The LLM may NOT
#: change the base type, but it may annotate the display format.
_HARD_TYPES: frozenset[str] = frozenset(
    {"number", "datetime", "boolean"}
)

#: Allowed finer format hints the LLM may add to ambiguous columns.
_ALLOWED_FORMATS: frozenset[str] = frozenset(
    {"currency", "percent", "email", "uri", "enum", "id", "code"}
)

# ── System Prompt ─────────────────────────────────────────────────────────────

_SCHEMA = StructuredTableConfig.model_json_schema()

STRUCTURED_TABLE_SYSTEM_PROMPT = f"""STRUCTURED TABLE OUTPUT MODE

You are generating structured table metadata for the frontend.

The data rows and base column types have already been determined deterministically.
Your task is ONLY to add optional format hints to ambiguous columns.

INSTRUCTIONS:
1. You will receive a list of columns with their base types.
2. For columns whose base type is "string" or "integer", you MAY add a "format" hint.
3. Valid format hints: currency, percent, email, uri, enum, id, code
4. You MUST NOT change a column's base type — only add/suggest a format hint.
5. Return ONLY a JSON object mapping column names to their suggested format hints.
   Example: {{"price": "currency", "rate": "percent", "user_id": "id"}}
6. Omit columns where no format hint applies.

SCHEMA (for reference — full config schema):
{json.dumps(_SCHEMA, indent=2)}

OUTPUT FORMAT:
- Return ONLY a JSON object, starting with {{ and ending with }}.
- No prose, no markdown fences.
- Empty object {{}} if no hints apply.
"""


# ── Renderer ──────────────────────────────────────────────────────────────────


@register_renderer(OutputMode.STRUCTURED_TABLE, system_prompt=STRUCTURED_TABLE_SYSTEM_PROMPT)
class StructuredTableRenderer(BaseChart):
    """Library-agnostic table renderer for the STRUCTURED_TABLE output mode.

    Extracts rows deterministically from ``response.data`` / ``response.output``
    via :meth:`TableRenderer._extract_data`, derives per-column storage types via
    :func:`~parrot.outputs.formats.table_types.base_column_types`, applies the
    row-limit, reuses the producer's ``explanation`` from ``response.response``,
    and optionally refines ambiguous column format hints via a narrow LLM pass.

    The renderer always:

    - Sets ``response.data`` to the canonical ``list[dict]`` rows.
    - Returns ``(out_without_data, explanation)`` — the structured-table config
      dict with the ``data`` key excluded, paired with the prose explanation.
    - Returns ``(None, error_message)`` on any unrecoverable error — never raises.
    """

    def __init__(self, row_limit: int = DEFAULT_ROW_LIMIT, **kwargs):
        """Initialise the renderer.

        Args:
            row_limit: Maximum rows to include in the response payload.
                Defaults to 1000.
            **kwargs: Forwarded to the base renderer.
        """
        super().__init__(**kwargs)
        self.row_limit = row_limit
        self._table_renderer = TableRenderer()

    async def render(
        self,
        response: Any,
        *,
        environment: str = "html",
        row_limit: Optional[int] = None,
        **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        """Render a structured table configuration from the agent response.

        Pipeline:
        1. Capture ``explanation`` from ``response.response`` (best-effort).
        2. Extract the DataFrame via :meth:`TableRenderer._extract_data`.
        3. Derive base column types via :func:`base_column_types`.
        4. Serialize rows canonically via :func:`canonical_records` with row-limit.
        5. Optionally refine ambiguous columns via LLM (deterministic wins).
        6. Build :class:`StructuredTableConfig`; exclude ``data`` from output.
        7. Set ``response.data = cfg.data``; return ``(out, explanation)``.

        On any error: return ``(None, error_message)`` — never raise.

        Args:
            response: An AIMessage-like object with ``data``, ``output``,
                and ``response`` attributes.
            environment: Rendering environment (unused; kept for protocol compat).
            row_limit: Override the instance-level row limit for this call.
            **kwargs: Unused.

        Returns:
            Tuple[Any, Optional[Any]]:
                - On success: ``(config_dict_without_data, explanation_or_None)``
                - On failure: ``(None, error_message_str)``
        """
        try:
            effective_row_limit = row_limit if row_limit is not None else self.row_limit

            # Step 1: Capture explanation from the producing agent.
            #   PandasAgent sets response.response = prose explanation;
            #   DB/SQL agent sets it from QueryResponse.explanation.
            #   If absent: omit gracefully (never block render).
            explanation: Optional[str] = getattr(response, "response", None) or None

            # Step 2: Extract DataFrame.
            #   Re-use TableRenderer._extract_data which handles
            #   PandasAgentResponse, response.data (DataFrame/list/dict), etc.
            try:
                df = self._table_renderer._extract_data(response)
            except Exception as exc:  # noqa: BLE001
                msg = f"StructuredTableRenderer: failed to extract data: {exc}"
                logger.warning(msg)
                return None, msg

            if df is None or df.empty:
                msg = "StructuredTableRenderer: no data found in response"
                logger.warning(msg)
                return None, msg

            # Step 3: Derive base column types (deterministic).
            col_types: dict[str, str] = base_column_types(df)

            # Step 4: Serialize rows canonically + apply row-limit.
            rows, total_rows, truncated = canonical_records(df, row_limit=effective_row_limit)

            # Step 5: Build base TableColumn list.
            columns: list[TableColumn] = [
                TableColumn(
                    name=col,
                    type=col_types.get(col, "any"),
                    title=col,  # default title = column name; LLM may refine
                    format=None,
                )
                for col in df.columns
            ]

            # Step 5b: Optional LLM-refine pass for ambiguous column format hints.
            #   Deterministic wins: the LLM may ONLY add a "format" hint to
            #   "string" or "integer" columns; it may NOT change a hard type.
            #   Any refine error → fall back to deterministic-only schema.
            columns = await self._apply_llm_refine(columns, response)

            # Step 6: Build StructuredTableConfig.
            #   The validator checks column.name ∈ rows[0].keys() when data
            #   is non-empty.  Pass an empty data list to skip validation here
            #   (rows are already validated by construction).
            try:
                cfg = StructuredTableConfig(
                    columns=columns,
                    data=rows,
                    explanation=explanation,
                    total_rows=total_rows,
                    truncated=truncated,
                )
            except Exception as exc:  # noqa: BLE001
                msg = f"StructuredTableRenderer: config build failed: {exc}"
                logger.warning(msg)
                return None, msg

            # Step 7: Exclude data from output; route rows to response.data.
            out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"})

            # Explicit None/empty-list check to avoid DataFrame truthiness crash:
            # if response.data is still a pd.DataFrame at this point, `if cfg.data`
            # would raise "truth value of a DataFrame is ambiguous".
            if cfg.data:
                # cfg.data (canonical list[dict]) takes priority over any raw
                # DataFrame the agent may have pre-populated in response.data.
                response.data = cfg.data
            # else: no rows — leave response.data untouched.

            return out, explanation

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error in StructuredTableRenderer: {exc}"
            logger.exception(msg)
            return None, msg

    async def _apply_llm_refine(
        self,
        columns: list[TableColumn],
        response: Any,
    ) -> list[TableColumn]:
        """Optionally refine ambiguous column format hints via a narrow LLM pass.

        The LLM may ONLY suggest a ``format`` hint for columns whose base type
        is ``"string"`` or ``"integer"``.  It may NOT change any base type.
        **Deterministic wins**: hard-typed columns (``number``, ``datetime``,
        ``boolean``) are never touched.  ``integer`` columns may receive
        format hints (e.g. ``"id"``, ``"code"``) but their base type is fixed.

        If the refine pass fails for any reason, the deterministic-only schema
        (original ``columns``) is returned unchanged.

        Args:
            columns: The deterministically-derived column list.
            response: The AIMessage-like response object (unused in the
                deterministic-only fallback path).

        Returns:
            The refined column list, or the original list on any error.
        """
        # Identify ambiguous columns (candidates for format hints)
        ambiguous = [c for c in columns if c.type in ("string", "integer")]
        if not ambiguous:
            return columns

        # Attempt to read LLM-supplied format hints from response.code
        # (the LLM may have embedded a hints JSON object there when called
        # with STRUCTURED_TABLE mode + our system prompt).
        raw_code = getattr(response, "code", None)
        if raw_code is None:
            # No LLM refine input available — return deterministic schema.
            return columns

        hints: Optional[dict[str, str]] = None
        try:
            if isinstance(raw_code, dict):
                hints = raw_code
            elif isinstance(raw_code, str):
                raw_code_stripped = raw_code.strip()
                # Extract JSON object if embedded in a code fence
                extracted = self._extract_json_code(raw_code_stripped)
                if extracted:
                    hints = json.loads(extracted)
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "StructuredTableRenderer: LLM refine parse failed (falling back): %s", exc
            )
            return columns

        if not hints or not isinstance(hints, dict):
            return columns

        # Apply hints: deterministic wins — only annotate ambiguous columns
        # with valid format strings; ignore any type-change attempts.
        col_map = {c.name: c for c in columns}
        for col_name, fmt in hints.items():
            col = col_map.get(col_name)
            if col is None:
                logger.debug(
                    "StructuredTableRenderer: LLM hinted unknown column %r — ignored",
                    col_name,
                )
                continue
            if col.type in _HARD_TYPES:
                logger.debug(
                    "StructuredTableRenderer: LLM tried to annotate hard-typed "
                    "column %r (type=%r) — ignored (deterministic wins)",
                    col_name, col.type,
                )
                continue
            if fmt not in _ALLOWED_FORMATS:
                logger.debug(
                    "StructuredTableRenderer: LLM suggested unknown format %r "
                    "for column %r — ignored",
                    fmt, col_name,
                )
                continue
            col_map[col_name] = TableColumn(
                name=col.name,
                type=col.type,
                title=col.title,
                format=fmt,
            )

        return list(col_map.values())

    # ── JSON extraction helper (mirrors StructuredChartRenderer) ──────────────

    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:
        """Extract a JSON object string from markdown code blocks or bare text.

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
        """Not used by StructuredTableRenderer (no HTML output).

        Args:
            chart_obj: Unused.
            **kwargs: Unused.

        Returns:
            Empty string.
        """
        return ""
