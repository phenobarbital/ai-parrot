# TASK-494: OntologyIntentResolver Demotion

**Feature**: intent-router
**Spec**: `sdd/specs/intent-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-491
**Assigned-to**: unassigned

---

## Context

> Implements Module 6 from the spec. OntologyIntentResolver transitions from a router
> ("graph or vector?") to an AQL query planner ("WHAT traversal to run"). When called
> from IntentRouter's GRAPH_PAGEINDEX strategy, the decision to use the graph has already
> been made — the resolver only needs to decide which pattern/AQL to execute.

---

## Scope

- Modify `OntologyIntentResolver` in `parrot/knowledge/ontology/intent.py`:
  - Deprecate `IntentDecision.action` field (keep for backwards compat but add deprecation note).
  - Remove the `vector_only` fallback case from `resolve()` — when called from IntentRouter, graph decision is already made.
  - `_try_fast_path()` and `_try_llm_path()` remain — they decide WHICH pattern/AQL.
  - If no pattern matches, return a "no match" result instead of `vector_only`.
- Modify `ResolvedIntent` in `parrot/knowledge/ontology/schema.py`:
  - Make `action` field optional with deprecation note.
- Ensure `OntologyRAGMixin.ontology_process()` still works unchanged — it's called by IntentRouter as GRAPH strategy.
- Ensure standalone usage (without IntentRouter) still works — no breaking change.
- Write unit tests for the demoted resolver.

**NOT in scope**: IntentRouterMixin changes, CapabilityRegistry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/knowledge/ontology/intent.py` | MODIFY | Demote: deprecate action, remove vector_only fallback |
| `parrot/knowledge/ontology/schema.py` | MODIFY | Make ResolvedIntent.action optional |
| `tests/knowledge/test_resolver_demotion.py` | CREATE | Unit tests for demoted behavior |

---

## Implementation Notes

### Pattern to Follow
```python
# IntentDecision — deprecate action
class IntentDecision(BaseModel):
    action: Literal["graph_query", "vector_only"] | None = None  # Deprecated: router decides this
    pattern: str | None = None
    aql: str | None = None
    suggested_post_action: str | None = None

# ResolvedIntent — make action optional
class ResolvedIntent(BaseModel):
    action: Literal["graph_query", "vector_only"] | None = "graph_query"  # Deprecated
    pattern: str | None = None
    aql: str | None = None
    # ... rest unchanged
```

### Key Constraints
- Backwards compatible: standalone OntologyIntentResolver.resolve() must still return valid ResolvedIntent.
- `OntologyRAGMixin.ontology_process()` is unchanged — it still calls resolve() and processes the result.
- When called via IntentRouter, the `action` field is ignored — routing was already decided.
- When called standalone (no IntentRouter), behavior should still work but action decision is less meaningful.

### References in Codebase
- `parrot/knowledge/ontology/intent.py:21-36` — IntentDecision
- `parrot/knowledge/ontology/intent.py:39-250` — OntologyIntentResolver
- `parrot/knowledge/ontology/schema.py:279-300` — ResolvedIntent
- `parrot/knowledge/ontology/mixin.py:100-109` — where resolve() is called

---

## Acceptance Criteria

- [ ] `IntentDecision.action` is optional with deprecation note
- [ ] `ResolvedIntent.action` is optional with default "graph_query"
- [ ] Resolver no longer returns `vector_only` when called from IntentRouter context
- [ ] `_try_fast_path()` and `_try_llm_path()` still decide pattern/AQL correctly
- [ ] Standalone usage (without IntentRouter) still works
- [ ] `OntologyRAGMixin.ontology_process()` unchanged and functional
- [ ] All existing ontology tests still pass
- [ ] New tests pass: `pytest tests/knowledge/test_resolver_demotion.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-494-ontology-resolver-demotion.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
