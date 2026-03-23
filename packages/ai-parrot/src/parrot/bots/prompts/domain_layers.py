"""Domain-specific prompt layers.

Reusable layers for specialized bot types (PandasAgent, SQL agents,
company bots, crew orchestration). These extend the built-in layers
without modifying them.

See spec: sdd/specs/composable-prompt-layer.spec.md (Section 3.5)
"""
from __future__ import annotations

from typing import Dict

from .layers import PromptLayer, LayerPriority, RenderPhase


# ── PandasAgent: data analysis context ──────────────────────────
DATAFRAME_CONTEXT_LAYER = PromptLayer(
    name="dataframe_context",
    priority=LayerPriority.KNOWLEDGE + 5,
    phase=RenderPhase.REQUEST,
    template="""<dataframe_context>
$dataframe_schemas
</dataframe_context>""",
    condition=lambda ctx: bool(ctx.get("dataframe_schemas", "").strip()),
)


# ── SQL Agent: dialect-specific instructions ────────────────────
SQL_DIALECT_LAYER = PromptLayer(
    name="sql_dialect",
    priority=LayerPriority.TOOLS + 5,
    phase=RenderPhase.CONFIGURE,
    template="""<sql_policy>
Generate syntactically correct $dialect queries.
Limit results to $top_k unless the user specifies otherwise.
Only select relevant columns, never SELECT *.
</sql_policy>""",
    condition=lambda ctx: bool(ctx.get("dialect")),
)


# ── Company context ─────────────────────────────────────────────
COMPANY_CONTEXT_LAYER = PromptLayer(
    name="company_context",
    priority=LayerPriority.KNOWLEDGE + 10,
    phase=RenderPhase.CONFIGURE,
    template="""<company_information>
$company_information
</company_information>""",
    condition=lambda ctx: bool(ctx.get("company_information", "").strip()),
)


# ── Crew cross-pollination ─────────────────────────────────────
CREW_CONTEXT_LAYER = PromptLayer(
    name="crew_context",
    priority=LayerPriority.KNOWLEDGE + 15,
    phase=RenderPhase.REQUEST,
    template="""<prior_agent_results>
$crew_context
</prior_agent_results>""",
    condition=lambda ctx: bool(ctx.get("crew_context", "").strip()),
)


# ── Strict grounding (replaces anti-hallucination block) ────────
STRICT_GROUNDING_LAYER = PromptLayer(
    name="strict_grounding",
    priority=LayerPriority.BEHAVIOR - 5,
    phase=RenderPhase.CONFIGURE,
    template="""<grounding_policy>
Use only data from provided context and tool outputs.
If information is missing, state "Data not available" rather than estimating.
</grounding_policy>""",
)


# ── Domain layer registry ──────────────────────────────────────

_DOMAIN_LAYERS: Dict[str, PromptLayer] = {
    "dataframe_context": DATAFRAME_CONTEXT_LAYER,
    "sql_dialect": SQL_DIALECT_LAYER,
    "company_context": COMPANY_CONTEXT_LAYER,
    "crew_context": CREW_CONTEXT_LAYER,
    "strict_grounding": STRICT_GROUNDING_LAYER,
}


def get_domain_layer(name: str) -> PromptLayer:
    """Look up a registered domain layer by name.

    Args:
        name: The domain layer name.

    Returns:
        The registered PromptLayer.

    Raises:
        KeyError: If the name is not registered.
    """
    if name not in _DOMAIN_LAYERS:
        raise KeyError(
            f"Unknown domain layer: '{name}'. "
            f"Available: {list(_DOMAIN_LAYERS.keys())}"
        )
    return _DOMAIN_LAYERS[name]
