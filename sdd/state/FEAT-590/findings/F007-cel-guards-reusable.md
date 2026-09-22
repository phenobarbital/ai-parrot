---
id: F007
query_id: Q007
type: read
intent: Check whether CEL guard infrastructure is reusable for delegate accept_when
executed_at: 2026-09-21T22:11:00Z
depth: 0
parent_id: null
---

# F007 — CEL guards reusable for accept_when

## Summary

Plan guards in `plan/guards.py` use `CELPredicateEvaluator` from `flow/cel_evaluator.py`. PlanGuard evaluates against `ctx.artifacts.<node_id>.<facet>`, `ctx.status.<node_id>`, `ctx.errors`. The delegate's `accept_when` guard could reuse the same evaluator with a different variable context exposing the proposal's fields (name, arguments, confidence). CEL is sandboxed and compiles at construction time, fitting the fail-fast pattern.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/plan/guards.py`
  symbol: `PlanGuard`
  excerpt: |
    class PlanGuard:
        """A compiled ``when`` expression."""
        def evaluate(self, artifacts, statuses, errors):
            """Evaluate the guard against the accumulated facet map."""

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/cel_evaluator.py`
  symbol: `CELPredicateEvaluator`
  excerpt: |
    class CELPredicateEvaluator:
        """Evaluate CEL expression strings as flow transition predicates."""

## Notes

The `accept_when` guard is distinct from the plan-level `when` guard. `when` decides whether the node runs at all (against upstream facets); `accept_when` decides whether a specific proposal from the delegate model is accepted (against the proposal's own fields). Both can use CEL but need different variable bindings. A `DelegateProposalGuard` wrapping CELPredicateEvaluator with `{proposal.name, proposal.arguments, proposal.confidence}` bindings would be clean.
