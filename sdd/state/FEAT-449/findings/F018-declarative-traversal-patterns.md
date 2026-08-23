---
id: F018
query_id: Q025,Q027
type: read
intent: Judge whether temporal traversals are expressible declaratively or need custom AQL
executed_at: 2026-08-23T00:41:45Z
depth: 2
parent_id: F011
---

# F018 — TraversalPattern makes the deterministic legal traversals declarative config: AQL template + bind vars + trigger keywords + authorization

## Summary

`TraversalPattern` is a first-class ontology construct: a named, human-described pattern
carrying `trigger_intents` (keywords for a fast path that skips LLM intent detection),
`query_template` (AQL with bind variables), `post_action`/`post_query` for chaining into
vector search, plus FEAT-158 additions for `entity_extraction`, declarative `authorization`,
and a post-traversal `tool_call`. Patterns live in `MergedOntology.traversal_patterns` and can
be loaded from overlay rows (`overlay_kind == "traversal_pattern"`). This means the source's
§3.4 deterministic traversals — `article_in_force(as_of)`, `case_chain`, `what_applies` — can
be authored as configuration with `as_of` as a bind variable, rather than as bespoke Python,
and the `tool_call` hook is a natural home for the CENDOJ verification step.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 263-290
  symbol: `TraversalPattern`
  excerpt: |
    class TraversalPattern(BaseModel):
        """Predefined graph traversal pattern for a known query type.
        Traversal patterns are the "fast path" — when the user's query matches
        a trigger_intent keyword, the system skips LLM intent detection and
        executes the AQL template directly.
        Args:
            trigger_intents: Keywords for fast-path matching.
            query_template: AQL with bind variables.
            post_action: What happens after graph traversal.
            authorization: Declarative authorization spec (FEAT-158).
            tool_call: Tool invocation spec (FEAT-158).

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 313-350
  symbol: `MergedOntology.traversal_patterns`
  excerpt: |
    traversal_patterns: dict[str, TraversalPattern] = Field(default_factory=dict)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py`
  lines: 351-374
  excerpt: |
    patterns: dict[str, TraversalPattern] = {}
            elif row.overlay_kind == "traversal_pattern":
                    patterns[row.name] = TraversalPattern(**row.definition)

## Notes

Does not solve the data model — `versions[]` still has to be designed and populated (F011) —
but it removes the query layer from the greenfield column.
