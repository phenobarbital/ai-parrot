---
id: F002
query_id: Q003
type: grep
intent: Confirm whether the two-phase RenderPhase (CONFIGURE/REQUEST) enum exists.
executed_at: 2026-06-05T13:08:50Z
duration_ms: 120
parent_id: null
depth: 0
---

# F002 — `RenderPhase` exists, but scoped to prompt layers

## Summary

`RenderPhase(str, Enum)` exists at `bots/prompts/layers.py:35` with `CONFIGURE`
and `REQUEST` members. However it governs **prompt-layer caching** (which layers
are static vs per-request), not a general agent lifecycle dispatch. The
brainstorm's "CONFIGURE vs REQUEST" principle is therefore real as a *concept*
and is concretely realized by `configure()` (load-once) vs `ask()/conversation()`
(per-request), but there is no generic phase router to plug into.

## Citations

- path: `parrot/bots/prompts/layers.py`
  lines: 35-79
  symbol: `RenderPhase`
  excerpt: |
    class RenderPhase(str, Enum):
        CONFIGURE = ...
        REQUEST = ...
    phase: RenderPhase = RenderPhase.REQUEST

## Notes

Practical mapping for this feature: encoder + route embeddings load once in
`configure()` (CONFIGURE); per-query routing runs in `ask()/conversation()`
(REQUEST). Cross-ref F001.
