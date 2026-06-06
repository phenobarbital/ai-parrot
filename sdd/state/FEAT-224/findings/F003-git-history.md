---
id: F003
query_id: Q011
type: git_log
intent: Check recent activity on the mixin / base ask path for churn risk.
executed_at: 2026-06-05T13:12:30Z
duration_ms: 200
parent_id: null
depth: 0
---

# F003 — Existing mixin is recently & actively maintained

## Summary

`bots/mixins/intent_router.py` is under active development as recently as
2026-05-12, evolved across at least three features (ontology-entity-extraction,
concept-document-authority). `bots/basic.py` itself has had only the
2026-03-23 monorepo scaffolding commit. `bots/abstract.py` (the real ask/
conversation home) churns frequently (visualizations/infographic work through
late May 2026). Implication: the change must coordinate with the live retrieval
router and the busy abstract base — touching `abstract.ask()/conversation()`
carries merge-conflict risk and needs a narrow, well-named hook.

## Citations

- path: `parrot/bots/mixins/intent_router.py`
  lines: 1
  symbol: git log
  excerpt: |
    21039d51 2026-05-12 fix(concept-document-authority): address 5 code-review issues
    20783618 2026-05-12 feat: TASK-1091 — IntentRouterMixin branch logic for ContextEnvelope
    24334a8a 2026-05-11 feat: TASK-1077 — wire _run_graph_pageindex user_context/tenant_id

- path: `parrot/bots/abstract.py`
  lines: 1
  symbol: git log (recent churn)
  excerpt: |
    febef625 2026-05-28 fix(ai-parrot-visualizations): ...
    39871fde 2026-05-28 feat(ai-parrot-visualizations): TASK-1359 ...

## Notes

Favors the template-method hook (A3) over a full `ask()` override (A2) to
minimize surface area against the churning base. Cross-ref F006, F010.
