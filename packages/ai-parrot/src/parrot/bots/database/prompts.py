"""Database agent prompt layers and builder factory.

Replaces the legacy string.Template constants with composable PromptLayer
instances that integrate with the PromptBuilder machinery used by PandasAgent.

Module 2 of FEAT-164 (database-agent-homologation).
"""
from __future__ import annotations

from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
from parrot.bots.prompts.domain_layers import SQL_DIALECT_LAYER, STRICT_GROUNDING_LAYER


DATABASE_CONTEXT_LAYER = PromptLayer(
    name="database_context",
    priority=LayerPriority.KNOWLEDGE + 5,
    phase=RenderPhase.REQUEST,
    template="""<database_context>
Database: $database
Intent: $intent
Requested output components: $output_components
</database_context>""",
)

DATABASE_SAFETY_LAYER = PromptLayer(
    name="database_safety",
    priority=LayerPriority.SECURITY + 5,
    phase=RenderPhase.CONFIGURE,
    template="""<database_safety>
CRITICAL CONSTRAINTS — NEVER VIOLATE:
1. Read-only operations only. Never execute INSERT, UPDATE, DELETE, DROP,
   TRUNCATE, ALTER, or any DDL/DML that modifies data unless explicitly granted.
   Exception: `db_explain_query` is always safe to call — it handles read-only
   safety internally. For SELECT queries it runs EXPLAIN ANALYZE and returns the
   full execution plan. For non-read-only statements it automatically downgrades
   to planner-only EXPLAIN. Call it directly; do not refuse based on EXPLAIN ANALYZE semantics.
2. Never guess table or column names. Use only schema information confirmed
   by available tools or the schema summary.
3. Bind all user-supplied values as parameters — never interpolate raw user
   input into SQL strings.
4. If a request requires destructive or privileged operations, explain the
   limitation and stop.
5. Every factual statement about the database must be traceable to the
   schema or tool output.
</database_safety>""",
)

SCHEMA_GROUNDING_LAYER = PromptLayer(
    name="schema_grounding",
    priority=LayerPriority.KNOWLEDGE + 10,
    phase=RenderPhase.REQUEST,
    template="""<schema_reference>
Use ONLY the tables and columns listed below. Do not reference any table,
column, or relationship not present here. If a requested object is absent,
respond "Data not available" and stop.
$schema_summary
</schema_reference>""",
    condition=lambda ctx: bool(ctx.get("schema_summary", "").strip()),
)

DATABASE_INSTRUCTIONS_LAYER = PromptLayer(
    name="database_instructions",
    priority=LayerPriority.PRE_INSTRUCTIONS + 1,
    phase=RenderPhase.CONFIGURE,
    template="""<database_instructions>
Respond with a structured QueryResponse containing:
- explanation: A human-readable summary of the query and its results.
- query: The SQL or DSL generated and executed (when applicable).
- data: Inline tabular results for small result sets.
- data_variable: Variable name holding a large result DataFrame.

Use tools only when schema lookup or query execution is required.
Prefer the schema-grounded query path — derive answers from the schema
summary before falling back to tool calls.
</database_instructions>""",
)

SCHEMA_TOOL_USAGE_LAYER = PromptLayer(
    name="schema_tool_usage",
    priority=LayerPriority.PRE_INSTRUCTIONS + 2,
    phase=RenderPhase.CONFIGURE,
    template="""<schema_tool_usage>
## Schema discovery workflow
1. `db_search_schema(term)` finds tables whose NAME, COLUMN NAME, or COMMENT
   matches `term`. It searches *identifiers, not data values*.
   - `db_search_schema('alaska')` will NOT find rows where `state_code = 'AK'`.
     To filter by a data value, find the table first, describe it, then write
     SQL with a WHERE clause.
2. `db_describe_table(schema, table)` returns the full column list, primary
   key, indexes, and foreign keys for a single table. Always call this before
   generating SQL that references a table — never reference a column you have
   not seen in a `db_describe_table` result.
3. `db_generate_query(natural_language, target_tables=[...])` produces a
   SELECT skeleton grounded in the real columns of `target_tables`. Refine
   the WHERE / JOIN clauses before executing.

Follow this order: `db_search_schema` → `db_describe_table` →
`db_generate_query` (or author SQL directly from the describe output).
4. `db_explain_query(query)` runs EXPLAIN ANALYZE on a SELECT query and returns
   the full execution plan with actual row counts and timing. Call it whenever
   the user asks for "explain analyze", "execution plan", "query plan", or
   performance analysis of a query. It is safe to call directly — no manual
   safety check needed.
</schema_tool_usage>""",
)


def _build_database_prompt_builder() -> PromptBuilder:
    """Create a PromptBuilder for DatabaseAgent with domain-specific layers."""
    builder = PromptBuilder.default()
    builder.add(DATABASE_CONTEXT_LAYER)
    builder.add(DATABASE_SAFETY_LAYER)
    builder.add(SCHEMA_GROUNDING_LAYER)
    builder.add(DATABASE_INSTRUCTIONS_LAYER)
    builder.add(SCHEMA_TOOL_USAGE_LAYER)
    builder.add(SQL_DIALECT_LAYER)
    builder.add(STRICT_GROUNDING_LAYER)
    return builder
