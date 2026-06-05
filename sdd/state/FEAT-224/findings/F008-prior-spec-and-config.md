---
id: F008
query_id: Q009
type: grep
intent: Locate the prior intent-router spec/brainstorm and the existing config model.
executed_at: 2026-06-05T13:11:30Z
duration_ms: 140
parent_id: null
depth: 0
---

# F008 — A prior intent-router spec + config model already shipped

## Summary

This is not greenfield. A prior `intent-router.brainstorm.md` (2026-03-30) and a
25 KB `intent-router.spec.md` (2026-03-30) already exist under `sdd/`, and the
implementation landed (F006). The config object `IntentRouterConfig` exists at
`registry/capabilities/models.py:149` (thresholds, timeouts, mode,
custom_keywords, hitl_threshold). A soft-deprecated alternative also points
callers at the mixin (`knowledge/ontology/intent.py:76`). The new feature is
therefore an **evolution of an existing, specced, deployed subsystem**, not a
new build.

## Citations

- path: `sdd/specs/intent-router.spec.md`
  lines: 1
  symbol: prior spec (25 KB, 2026-03-30)
  excerpt: |
    (existing approved spec for the retrieval-strategy IntentRouterMixin)

- path: `parrot/registry/capabilities/models.py`
  lines: 149-150
  symbol: `IntentRouterConfig`
  excerpt: |
    class IntentRouterConfig(BaseModel):
        """Configuration for the IntentRouter."""

- path: `parrot/knowledge/ontology/intent.py`
  lines: 66-86
  symbol: soft-deprecated alias → IntentRouterMixin
  excerpt: |
    Prefer parrot.bots.mixins.intent_router.IntentRouterMixin
    #: Soft-deprecated: use IntentRouterMixin for new code.

## Notes

Adding embedding-routing config (model name, per-route threshold, route
utterances) most likely extends `IntentRouterConfig` rather than inventing a
parallel config. Cross-ref F006.
