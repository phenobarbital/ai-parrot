"""Pure ``DataTable`` cell formatting, shared by both HTML renderers (FEAT-493, TASK-2711).

``TableColumn.type``/``.format`` (``parrot.models.outputs``) already carry
"the minimum information a frontend grid library needs to render a column
correctly" — both renderers used to ignore it and render every cell as
``str(value)``. This module formats **in Python**, so ``ssr-html`` and
``pdf`` come out formatted with zero client-side JS, and ``interactive-html``
shares the exact same rules.

Pure, stateless functions only — no I/O, no renderer instance state — so
they're directly testable and safe to call from three render call sites
(interactive, SSR, and PDF via SSR) without any shared mutable context.
"""

from __future__ import annotations

import html
from typing import Any

#: ``TableColumn.type`` values treated as numeric — right-aligned, comma/
#: decimal-grouped, and carrying ``<td class="num" data-v="...">`` for the
#: client sort to compare rather than parsing rendered text. Detection comes
#: from the DECLARED type only, never from sniffing the value — a zip code
#: typed ``string`` must never be grouped or right-aligned.
NUMERIC_TYPES: frozenset[str] = frozenset({"integer", "number", "duration"})


def is_numeric_column(col_type: str | None) -> bool:
    """Whether a declared ``TableColumn.type`` renders as a numeric column.

    Args:
        col_type: The column's declared ``type`` (may be ``None`` when a
            caller omits it, e.g. a hand-authored envelope in a test).

    Returns:
        ``True`` for ``integer``/``number``/``duration`` only.
    """
    return col_type in NUMERIC_TYPES


def format_cell(value: Any, *, col_type: str | None, col_format: str | None = None) -> str:
    """Format one cell value for display. Pure: no I/O, no renderer state.

    Args:
        value: The raw (already-resolved) cell value.
        col_type: The column's declared ``TableColumn.type``
            (``string`` | ``integer`` | ``number`` | ``boolean`` | ``date``
            | ``datetime`` | ``time`` | ``duration`` | ``any``).
        col_format: The column's optional ``TableColumn.format`` hint
            (``currency`` | ``percent`` | ``email`` | ``uri`` | ``enum`` |
            ``id`` | ``code``). Only ``currency``/``percent`` affect
            formatting here; the rest are display hints for a frontend grid
            library, not something this text-only renderer acts on.

    Returns:
        The formatted display string. ``None`` always formats as ``""``,
        regardless of type. A non-numeric type (or a value that fails
        numeric coercion) passes through as ``str(value)`` unmodified —
        a typed ``string`` column is NEVER comma-grouped or aligned, even
        if its value happens to look numeric (e.g. a zip code).
    """
    if value is None:
        return ""
    if not is_numeric_column(col_type):
        return str(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    if col_format == "percent":
        return f"{number * 100:,.1f}%"
    if col_format == "currency":
        return f"{number:,.2f}"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def format_cell_html(value: Any, *, col_type: str | None, col_format: str | None = None) -> str:
    """Render one ``<td>`` for a DataTable cell, HTML-escaped.

    Args:
        value: The raw (already-resolved) cell value.
        col_type: The column's declared ``TableColumn.type``.
        col_format: The column's optional ``TableColumn.format`` hint.

    Returns:
        ``<td class="num" data-v="<raw>"><formatted></td>`` for a numeric
        column (``data-v`` carries the RAW, unformatted value so the
        existing client-side sort compares numbers rather than
        separator-laden text), or a plain ``<td><formatted></td>``
        otherwise.
    """
    formatted = html.escape(format_cell(value, col_type=col_type, col_format=col_format))
    if not is_numeric_column(col_type):
        return f"<td>{formatted}</td>"
    raw = html.escape("" if value is None else str(value), quote=True)
    return f'<td class="num" data-v="{raw}">{formatted}</td>'
