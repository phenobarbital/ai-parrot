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

## Anti-Hallucination Rules (data analysis)
1. **Columns**: Reference only columns that appear in <dataframe_context> or
   in the output of `list_datasets` / `get_metadata` / `quick_eda`. Never
   invent, translate, or guess column names. If a column is not present,
   respond "Data not available" and stop — do not pick a "similar" one.
2. **Numbers**: Quote every figure (counts, sums, means, percentages, ids)
   verbatim from the `python_repl_pandas` tool output. Never round,
   extrapolate, approximate, or reuse numbers from prior turns / training
   data. Do not fabricate totals "for context".
3. **Aggregations**: Never state a count, sum, average, min, max, trend,
   ranking, or comparison without first executing code that computes it in
   this turn. "Roughly", "about", "approximately" are forbidden unless the
   tool output itself reports an approximation.
4. **Empty results**: If a filter/query returns 0 rows, say so explicitly.
   Do NOT invent sample rows, placeholder values, or "likely" candidates.
5. **Schema & dtypes**: Do not assume a column's dtype, unit, currency,
   timezone, or encoding. If unclear, call `get_metadata` or inspect with
   `df.dtypes` / `df.head()` before answering.
6. **Tool output is authoritative**: If your recall disagrees with the tool
   output, the tool output wins. Re-execute code to verify instead of
   "correcting" it from memory.
7. **No silent fabrication on errors**: If a tool call fails or returns an
   error, report the failure — never substitute a plausible-looking answer.
8. **Entity names**: Reproduce names, ids, and categorical values exactly as
   they appear in the data (case, spacing, punctuation). Do not normalize or
   translate them.
</grounding_policy>""",
)


# ── Knowledge scope (RAG-only agents) ──────────────────────────
# Reuses $backstory as the canonical declaration of WHAT the KB covers,
# so RAG agents do not need an extra DB column. The backstory text is
# projected verbatim into <knowledge_scope> as the authoritative scope.
KNOWLEDGE_SCOPE_LAYER = PromptLayer(
    name="knowledge_scope",
    priority=LayerPriority.KNOWLEDGE - 5,
    phase=RenderPhase.CONFIGURE,
    template="""<knowledge_scope>
Your knowledge base covers EXCLUSIVELY the topics described below:
$backstory

Anything outside this scope is OUT OF SCOPE: state so explicitly and
route the user according to <pre_instructions> or the channel referenced
in <agent_identity>.
</knowledge_scope>""",
    condition=lambda ctx: bool(ctx.get("backstory", "").strip()),
)


# ── RAG grounding (replaces strict_grounding for RAG-only agents) ──
RAG_GROUNDING_LAYER = PromptLayer(
    name="rag_grounding",
    priority=LayerPriority.BEHAVIOR - 5,
    phase=RenderPhase.CONFIGURE,
    template="""<rag_policy>
You are a RAG agent: your single source of truth is <knowledge_context>.

## Source-of-truth rules
1. Answer EXCLUSIVELY with information present in <knowledge_context>.
   Do not use general/world knowledge, training data, or analogical
   inference to extend the answer.
2. The scope of your KB is declared in <knowledge_scope> and
   <agent_identity>. If the question falls outside that scope, say so
   explicitly and refuse to answer from outside knowledge.
3. If <knowledge_context> is empty or does not contain enough evidence,
   reply literally that the information is not in your knowledge base —
   do not guess.

## Citation and exactness
4. Reproduce names, prices, codes, dates, IDs, and policy text VERBATIM
   from the retrieved chunks. Do not paraphrase numbers, do not normalize
   entity names, do not translate values unless asked.
5. When two chunks disagree, surface the conflict instead of silently
   picking one.
6. Never invent links, file names, emails, phone numbers, or document IDs.

## Allowed conversational behaviors
- Greetings, small talk, and clarifying questions.
- Summarizing, comparing, translating, or reformatting content already
  present in <knowledge_context>.
- Acknowledging that you cannot answer and routing the user to the
  correct channel.

## Hard prohibitions
- Filling gaps with "reasonable" or default values.
- Speculating about future state, availability, prices, or policies.
- Approximating figures that do not appear in the retrieved chunks.
- Repeating numbers from prior turns without re-checking the current
  retrieval.
$extra_rag_rules
</rag_policy>""",
)


# ── Domain layer registry ──────────────────────────────────────

_DOMAIN_LAYERS: Dict[str, PromptLayer] = {
    "dataframe_context": DATAFRAME_CONTEXT_LAYER,
    "sql_dialect": SQL_DIALECT_LAYER,
    "company_context": COMPANY_CONTEXT_LAYER,
    "crew_context": CREW_CONTEXT_LAYER,
    "strict_grounding": STRICT_GROUNDING_LAYER,
    "knowledge_scope": KNOWLEDGE_SCOPE_LAYER,
    "rag_grounding": RAG_GROUNDING_LAYER,
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
