"""Per-component data-feasibility checks for the inline emitter (FEAT-755).

A schema-valid config can still be unrenderable — a KPICard with no scalar value, a
Timeline with no events. The emitter runs these checks after parsing and degrades
instead of emitting an empty-looking card. Emitter-local by design: no
``CapabilityRegistry`` coupling (the rev-1 layer-1 hook was never built).

Pure module: no parrot imports, no pandas. ``frame`` is duck-tested only.
"""

from __future__ import annotations

from typing import Any, Mapping, NamedTuple, Optional

__all__ = ["FeasibilityResult", "check_feasibility"]


class FeasibilityResult(NamedTuple):
    """Outcome of a feasibility check; ``reason`` is a fixed code when infeasible."""

    feasible: bool
    reason: Optional[str] = None


_FEASIBLE = FeasibilityResult(True, None)


def _non_empty_str(value: Any) -> bool:
    """Return True when ``value`` is a string with non-whitespace content.

    Args:
        value: Any value.

    Returns:
        Whether it is a non-blank string.
    """
    return isinstance(value, str) and bool(value.strip())


def _check_kpicard(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """``value`` must be present and scalar (number, or non-empty string).

    A Mapping value is a binding descriptor, not a renderable scalar for an inline card.

    Args:
        config: Parsed component config.
        frame: Optional data frame (unused).

    Returns:
        The feasibility result.
    """
    value = config.get("value")
    if isinstance(value, bool):
        return FeasibilityResult(False, "kpicard_value_missing")
    if isinstance(value, (int, float)) or _non_empty_str(value):
        return _FEASIBLE
    return FeasibilityResult(False, "kpicard_value_missing")


def _check_timeline(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """>= 1 event carrying a non-empty ``title``.

    Args:
        config: Parsed component config.
        frame: Optional data frame (unused).

    Returns:
        The feasibility result.
    """
    events = config.get("events")
    if isinstance(events, (list, tuple)):
        for event in events:
            if isinstance(event, Mapping) and _non_empty_str(event.get("title")):
                return _FEASIBLE
    return FeasibilityResult(False, "timeline_events_missing")


def _check_infocard(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """Non-empty ``title``.

    Args:
        config: Parsed component config.
        frame: Optional data frame (unused).

    Returns:
        The feasibility result.
    """
    if _non_empty_str(config.get("title")):
        return _FEASIBLE
    return FeasibilityResult(False, "infocard_title_missing")


def _check_graph(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """>= 1 node, and every edge endpoint names an existing node id.

    Args:
        config: Parsed component config.
        frame: Optional data frame (unused).

    Returns:
        The feasibility result.
    """
    nodes = config.get("nodes")
    if not isinstance(nodes, (list, tuple)) or not nodes:
        return FeasibilityResult(False, "graph_nodes_missing")
    ids = {node.get("id") for node in nodes if isinstance(node, Mapping) and node.get("id") is not None}
    if not ids:
        return FeasibilityResult(False, "graph_nodes_missing")
    edges = config.get("edges") or []
    if not isinstance(edges, (list, tuple)):
        return FeasibilityResult(False, "graph_edge_dangling")
    for edge in edges:
        if not isinstance(edge, Mapping) or edge.get("from") not in ids or edge.get("to") not in ids:
            return FeasibilityResult(False, "graph_edge_dangling")
    return _FEASIBLE


_CHECKS = {
    "KPICard": _check_kpicard,
    "Timeline": _check_timeline,
    "InfoCard": _check_infocard,
    "Graph": _check_graph,
}

_REASONS = {
    "KPICard": "kpicard_value_missing",
    "Timeline": "timeline_events_missing",
    "InfoCard": "infocard_title_missing",
    "Graph": "graph_nodes_missing",
}


def check_feasibility(component: str, config: Mapping[str, Any], frame: Any | None) -> FeasibilityResult:
    """Run ``component``'s feasibility rule against ``config``.

    An unknown component is feasible — schema validation decides for it, which keeps
    this module closed to edits when FEAT-753/754 register new components.

    Never raises: a malformed ``config`` yields an infeasible result, not an exception.

    Args:
        component: Catalog component name.
        config: Parsed component config.
        frame: Optional data frame, duck-tested only.

    Returns:
        The feasibility result.
    """
    checker = _CHECKS.get(component) if isinstance(component, str) else None
    if checker is None:
        return _FEASIBLE
    if not isinstance(config, Mapping):
        return FeasibilityResult(False, _REASONS[component])
    try:
        return checker(config, frame)
    except Exception:  # noqa: BLE001 - never raise by contract
        return FeasibilityResult(False, _REASONS[component])
