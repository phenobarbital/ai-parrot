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


def _extensions(node: BasicNode) -> dict[str, Any]:
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
    variant = _extensions(node).get("parrot_variant")
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
    role = _extensions(node).get("parrot_role")
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
    unit = _extensions(node).get("parrot_unit")
    if not unit:
        return ""
    return f'<span class="kpi-unit">{_esc(unit)}</span>'


def trend_attr_html(node: BasicNode) -> str:
    """The `` data-trend="up|down|flat"`` attribute for a ``delta``-role Text's ``parrot_trend``.

    Args:
        node: The reconstructed ``Text`` :class:`BasicNode`.

    Returns:
        The leading-space-prefixed attribute string, or ``""`` (no
        attribute) when no trend is set. ``components.css`` colours the
        element based on this attribute's value.
    """
    trend = _extensions(node).get("parrot_trend")
    if not trend:
        return ""
    return f' data-trend="{_esc(trend)}"'


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
        isinstance(child, BasicNode) and child.component == "Card" and _extensions(child).get("parrot_variant") == "kpi"
        for child in children
    )
