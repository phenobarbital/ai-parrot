"""System-prompt addon for authoring one inline A2UI component (FEAT-755).

The addon carries PROSE ONLY — the component's catalog ``instructions`` plus any
inline-specific authoring notes. The schema reaches the model as
``structured_output=component_model(component)`` (catalog/_model.py), mirroring how
``STRUCTURED_CHART`` advertises ``StructuredChartConfig`` instead of inlining its
schema (``bots/data.py:1504-1515``). Keeping the two apart is what keeps prompt and
schema from drifting (spec G6).
"""
from __future__ import annotations

import logging
from typing import Final

from parrot.outputs.a2ui.catalog import get_component
# Component registration happens on import of the catalog subpackages (side effect only).
from parrot.outputs.a2ui.catalog import parrot as _parrot_catalog  # noqa: F401
from parrot.outputs.a2ui.catalog import viz_core as _viz_core_catalog  # noqa: F401

logger = logging.getLogger(__name__)

__all__ = ["INLINE_COMPONENTS", "INLINE_AUTHORING_NOTES", "build_component_prompt"]

#: v1 allowlist. Display-only components only (``requires_actions=False``). Spans two
#: catalogs: KPICard/InfoCard/Timeline are Parrot-catalog, Graph is viz-core — which is
#: why membership is resolved by NAME and no catalog id is hard-coded.
INLINE_COMPONENTS: Final[frozenset[str]] = frozenset({"KPICard", "InfoCard", "Timeline", "Graph"})

#: Inline-specific guidance ADDED ON TOP of a component's catalog ``instructions``.
#: Graph is the only v1 entry: GRAPH_INSTRUCTIONS already covers the vocabulary, but
#: not the constraints an inline chat bubble imposes.
INLINE_AUTHORING_NOTES: Final[dict[str, str]] = {
    "Graph": (
        "Inline graph constraints: keep the graph small — at most 25 nodes. Use stable, "
        "slug-like node ids (e.g. `fetch_data`, `validate_input`). Always set `direction` "
        "and always set `accessibleDescription`. Never emit positions or coordinates. "
        "Pick `kind` as described above (flowchart/state/sequence/dag)."
    ),
}

_FIXED_RULES: Final[str] = (
    "RULES:\n"
    "- Compute every figure yourself in the tool loop before answering; values such as "
    "`value` and `delta` are literals, never bindings.\n"
    "- Never emit data rows, positions or `action`.\n"
    "- Return only the component config: no prose, no markdown, no code fences."
)


def build_component_prompt(component: str) -> str:
    """Return the system-prompt addon for authoring ``component`` inline.

    Sections, in order: a header (``"INLINE A2UI <Name> OUTPUT MODE"``), the component's
    catalog ``instructions``, ``INLINE_AUTHORING_NOTES`` for it (when present), and the
    fixed rules.

    Args:
        component: The registered component name (e.g. ``"KPICard"``).

    Returns:
        The prompt addon text.

    Raises:
        KeyError: If ``component`` is not registered in any catalog.
    """
    definition = get_component(component).definition
    sections = [f"INLINE A2UI {component} OUTPUT MODE", definition.instructions]
    notes = INLINE_AUTHORING_NOTES.get(component)
    if notes:
        sections.append(notes)
    sections.append(_FIXED_RULES)
    return "\n\n".join(s for s in sections if s)
