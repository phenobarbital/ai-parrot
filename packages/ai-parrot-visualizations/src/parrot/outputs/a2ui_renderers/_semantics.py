"""Shared ``parrot_variant``/``parrot_role`` -> CSS class mapping (FEAT-493, TASK-2710).

The A2UI catalog already emits a rich semantic vocabulary on lowered
``BasicNode`` metadata (``parrot_variant``, ``parrot_role``, ``parrot_unit``,
``parrot_trend`` — see ``catalog/parrot/kpicard.py`` and
``catalog/parrot/infographic.py``). Both HTML renderers used to drop this
information on the floor (a ``KPICard`` arrived as a generic bordered box).
This module closes that gap with free helper functions shared by both
renderers.

Free functions, not a mixin: :class:`~parrot.outputs.a2ui_renderers.interactive_html.InteractiveHTMLRenderer`
dispatches by ``_render_prim_<Name>`` while
:class:`~parrot.outputs.a2ui_renderers.ssr_html.SSRHTMLRenderer` dispatches by
``_render_<Name>`` — a mixin defining one set of method names would attach to
only one of the two renderers and silently no-op on the other, producing a
half-applied feature that single-surface tests would not catch.

No ``lower()`` method is read or modified here — this module only maps
metadata that lowering already produces to presentation classes/attributes.
"""

from __future__ import annotations

import html
from typing import Any

from parrot.outputs.a2ui.catalog.base import BasicNode

from ._table_format import format_cell

#: ``parrot_variant`` -> semantic ``Card`` class, appended to (never replacing)
#: the pre-existing bare ``a2ui-card`` class. Variants without a dedicated
#: entry degrade to a generic ``a2ui-card-<variant>`` class (never dropped).
_CARD_VARIANT_CLASSES: dict[str, str] = {
    "kpi": "kpi-card",
    "report": "report-card",
    "chart": "panel",
    "table": "panel",
}

#: ``parrot_role`` -> semantic ``Text`` class, appended alongside the
#: pre-existing ``a2ui-<role>`` class, for the roles the design system
#: actually styles. A role absent from this map (e.g. ``cell``) gets no
#: extra class — the pre-existing ``a2ui-<role>`` class is untouched.
_TEXT_ROLE_CLASSES: dict[str, str] = {
    "label": "kpi-label",
    "value": "kpi-value",
    "delta": "kpi-delta",
    "title": "ds-title",
    "subtitle": "ds-subtitle",
    "heading": "ds-heading",
    "caption": "ds-caption",
    "notice": "ds-notice",
}


def _esc(value: Any) -> str:
    """HTML-escape any resolved value as a display/attribute string."""
    return html.escape("" if value is None else str(value))


def node_extensions(node: BasicNode) -> dict[str, Any]:
    """The node's ``metadata.extensions.root`` dict, or ``{}`` when absent."""
    if node.metadata is not None and node.metadata.extensions is not None:
        return node.metadata.extensions.root
    return {}


def semantic_card_class(node: BasicNode) -> str | None:
    """The extra class to append to ``a2ui-card`` for this ``Card``'s ``parrot_variant``.

    Args:
        node: The reconstructed ``Card`` :class:`BasicNode`.

    Returns:
        The semantic class name, or ``None`` when the node carries no
        variant — callers append nothing in that case, leaving the
        pre-existing bare ``a2ui-card`` class untouched.
    """
    variant = node_extensions(node).get("parrot_variant")
    if not variant:
        return None
    return _CARD_VARIANT_CLASSES.get(variant, f"a2ui-card-{variant}")


def semantic_text_class(node: BasicNode) -> str | None:
    """The extra class to append alongside ``a2ui-<role>`` for this ``Text``'s ``parrot_role``.

    Args:
        node: The reconstructed ``Text`` :class:`BasicNode`.

    Returns:
        The semantic class name, or ``None`` when the role carries no
        design-system styling (e.g. ``cell``) or no role is set at all.
    """
    role = node_extensions(node).get("parrot_role")
    if not role:
        return None
    return _TEXT_ROLE_CLASSES.get(role)


def kpi_unit_html(node: BasicNode) -> str:
    """The ``<span class="kpi-unit">`` markup for a ``value``-role Text's ``parrot_unit``.

    Args:
        node: The reconstructed ``Text`` :class:`BasicNode`.

    Returns:
        The unit ``<span>`` markup, or ``""`` when no unit is set — callers
        concatenate this directly onto the rendered ``<p>`` content.
    """
    unit = node_extensions(node).get("parrot_unit")
    if not unit:
        return ""
    return f'<span class="kpi-unit">{_esc(unit)}</span>'


def humanize_key(name: str) -> str:
    """``in_progress`` -> "In progress": a column key made readable.

    A chart's series are named by the data column they came from, and both
    the legend and the metric toggles printed that key verbatim — a report's
    key read ``scheduled | in_progress | completed | unfulfilled``, which is
    a schema, not a label.

    First word capitalised only: "In progress", not "In Progress". These sit
    in a legend, not in a heading.
    """
    words = str(name).replace("_", " ").replace("-", " ").split()
    if not words:
        return str(name)
    return " ".join([words[0].capitalize()] + [w.lower() for w in words[1:]])


def kpi_value_display(node: BasicNode, raw: Any) -> str:
    """The display string for a ``value``-role Text, honouring ``parrot_value_format``.

    A KPI value arrives as the number it is: a completion rate is ``0.683``,
    not ``"68.3%"``. Both HTML renderers printed that straight through, so a
    report card read ``0.6833333333333333`` — sixteen digits of float noise
    where a reader wanted three characters.

    The formatting is DECLARED, never guessed (``KPICard.format``, mirroring
    ``TableColumn.format`` which these renderers already honour). Without a
    declared format the value passes through as ``str(value)``, byte-identical
    to before: a renderer that inferred meaning from the number would group a
    year as ``2,026``.

    Args:
        node: The reconstructed ``value``-role ``Text`` :class:`BasicNode`.
        raw: The node's already-resolved ``text`` value.

    Returns:
        The display string, unescaped — callers escape.
    """
    fmt = node_extensions(node).get("parrot_value_format")
    if not fmt:
        return "" if raw is None else str(raw)
    # `format_cell` needs a numeric declared type to do anything; the format
    # hint IS the declaration that this value is a number.
    return format_cell(raw, col_type="number", col_format=fmt)


def kpi_comparison_html(node: BasicNode) -> str:
    """The ``<span class="kpi-comparison">`` markup for a kpi ``Card``'s baseline label.

    ``KPICardComponent.lower`` has carried ``comparisonPeriod`` as a Card
    extension since FEAT-527 and both HTML renderers dropped it, so a card
    showed "+52.4%" without ever saying what it was 52.4% more THAN.

    Args:
        node: The reconstructed ``Card`` :class:`BasicNode`.

    Returns:
        The span markup, or ``""`` when the card declares no baseline.
    """
    period = node_extensions(node).get("parrot_comparison_period")
    if not period:
        return ""
    return f'<span class="kpi-comparison">{_esc(period)}</span>'


def trend_attr_html(node: BasicNode) -> str:
    """The `` data-trend="up|down|flat"`` attribute for a ``delta``-role Text's ``parrot_trend``.

    Args:
        node: The reconstructed ``Text`` :class:`BasicNode`.

    Returns:
        The leading-space-prefixed attribute string, or ``""`` (no
        attribute) when no trend is set. Carries ``data-sentiment`` too when
        lowering supplied one; ``components.css`` colours by that and falls
        back to ``data-trend``.
    """
    ext = node_extensions(node)
    trend = ext.get("parrot_trend")
    if not trend:
        return ""
    attrs = f' data-trend="{_esc(trend)}"'
    # The direction is what the arrow shows; the sentiment is what the colour
    # means. `components.css` prefers the sentiment and falls back to the
    # direction, so a card lowered before this existed is unchanged.
    sentiment = ext.get("parrot_sentiment")
    if sentiment:
        attrs += f' data-sentiment="{_esc(sentiment)}"'
    return attrs


def is_kpi_row(node: BasicNode) -> bool:
    """Whether every child of this ``Row`` is a ``Card`` with ``parrot_variant: "kpi"``.

    Args:
        node: The reconstructed ``Row`` :class:`BasicNode`.

    Returns:
        ``True`` only when the row has at least one child and every child
        is a ``kpi``-variant ``Card`` — a mixed or childless row is not a
        KPI grid.
    """
    children = node.children if isinstance(node.children, list) else []
    if not children:
        return False
    return all(
        isinstance(child, BasicNode)
        and child.component == "Card"
        and node_extensions(child).get("parrot_variant") == "kpi"
        for child in children
    )
