"""Composite route-label grammar and the A2UI component-hint channel (FEAT-755).

A phrase-bank key is either a plain :class:`OutputMode` value
(``"structured_chart"``) or a composite ``"a2ui:<ComponentName>"`` that resolves
to :attr:`OutputMode.A2UI` plus a component hint carried on the request context.

This module is deliberately pure: the A2UI catalog is imported lazily, inside
:func:`is_inline_component` only, so ``parrot.registry.routing`` stays light.
"""

from __future__ import annotations

import logging
from typing import Any, Final, NamedTuple, Optional

from parrot.models.outputs import OutputMode

logger = logging.getLogger(__name__)

__all__ = [
    "A2UI_LABEL_PREFIX",
    "OutputShape",
    "make_route_label",
    "parse_route_label",
    "is_inline_component",
    "set_output_shape",
    "get_component_hint",
]

A2UI_LABEL_PREFIX: Final[str] = "a2ui:"


class OutputShape(NamedTuple):
    """Resolved output shape: ``mode`` plus an optional A2UI ``component`` hint."""

    mode: OutputMode
    component: Optional[str] = None


def make_route_label(component: str) -> str:
    """Return ``"a2ui:<component>"``.

    Args:
        component: The A2UI catalog component name.

    Raises:
        ValueError: If ``component`` is empty or whitespace-only.
    """
    component = component.strip()
    if not component:
        raise ValueError("A2UI route-label component must not be empty.")
    return f"{A2UI_LABEL_PREFIX}{component}"


def parse_route_label(label: str) -> OutputShape:
    """Parse a phrase-bank key into an :class:`OutputShape`.

    ``"structured_chart"`` -> ``OutputShape(OutputMode.STRUCTURED_CHART)``;
    ``"a2ui:KPICard"`` -> ``OutputShape(OutputMode.A2UI, "KPICard")``.

    Does NOT consult the catalog — see :func:`is_inline_component`.

    Args:
        label: A plain output-mode value or composite A2UI route label.

    Raises:
        ValueError: On an unknown OutputMode value or a malformed composite
            (empty component after the prefix).
    """
    if label.startswith(A2UI_LABEL_PREFIX):
        component = label[len(A2UI_LABEL_PREFIX) :].strip()
        if not component:
            raise ValueError("A2UI route-label component must not be empty.")
        return OutputShape(OutputMode.A2UI, component)
    return OutputShape(OutputMode(label))


def is_inline_component(component: str) -> bool:
    """Return whether ``component`` is registered and does not require actions.

    The catalog is imported only for the lookup to keep routing imports light.

    Args:
        component: The A2UI catalog component name to check.

    Returns:
        ``True`` when the component is display-only; otherwise ``False``.
    """
    from parrot.outputs.a2ui.catalog import CatalogError, get_component

    try:
        return not get_component(component).definition.requires_actions
    except (KeyError, CatalogError):
        return False


def set_output_shape(ctx: Any, shape: OutputShape) -> OutputMode:
    """Write an A2UI component hint to a context and return its output mode.

    Args:
        ctx: A request-context-like object, or ``None``.
        shape: The resolved output shape to apply.

    Returns:
        The output mode stored in ``shape``.
    """
    if ctx is not None:
        ctx.a2ui_component = shape.component
    return shape.mode


def get_component_hint(ctx: Any) -> Optional[str]:
    """Return a context's A2UI component hint, if present.

    Args:
        ctx: A request-context-like object, or ``None``.

    Returns:
        The component hint or ``None`` when it is unavailable.
    """
    if ctx is None:
        return None
    return getattr(ctx, "a2ui_component", None)
