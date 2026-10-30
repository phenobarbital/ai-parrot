---
id: FG-001
query_id: Q060
type: git_log
intent: "Recent activity on PromptBuilder / prompts (is the identity layer still moving?)."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 400
parent_id: null
depth: 0
---

# FG-001 — bots/prompts/: 15 commits in 90 days; layer primitives extended (literal, toolless) — no identity-layer rework

## Summary

15 non-merge commits since 2026-08-01 on `packages/ai-parrot/src/parrot/bots/prompts/` (authors: Jesus Lara, Jesus, revbot). Dominant themes: (1) FEAT-707 per-tenant skills added a `literal` flag to `PromptLayer` so user-authored text (skill descriptions) is never ``-substituted; (2) a new REQUEST-phase `TOOLLESS_DATA_GROUNDING_LAYER` registered in the `_DOMAIN_LAYERS` dict of `domain_layers.py`; (3) FEAT-638 jiraspecialist multilang output-language layer; (4) prompt text rewrites (A2UI/structured-chart). No commit in the window touches the identity layer itself — the layer machinery is stable and extensible by registering named `PromptLayer` objects in a dict.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/prompts/layers.py`
  lines: 62-141
  symbol: `PromptLayer`
  excerpt: |
    22eb900e1c 2026-10-20 Jesus Lara feat(per-tenant-skills): TASK-4507 — tenant skill hardening
    +    literal: When True the template is plain text, never substituted: render()/partial_render()
    +        return it verbatim. Use it for layers built from untrusted or user-authored text (FEAT-707).
    +    literal: bool = False
    (also touched: bots/base.py, skills/mixin.py, skills/prompt.py, skills/tenancy.py, handlers/agents/abstract.py, handlers/chat.py)

- path: `packages/ai-parrot/src/parrot/bots/prompts/domain_layers.py`
  lines: 786-880
  symbol: `TOOLLESS_DATA_GROUNDING_LAYER`, `_DOMAIN_LAYERS`
  excerpt: |
    c6541d544d 2026-10-16 Jesus Lara fix(bots): honour use_tools=False in ask/ask_stream/conversation and its prompt
    +TOOLLESS_DATA_GROUNDING_LAYER = PromptLayer(name="toolless_data_grounding",
    +    priority=LayerPriority.BEHAVIOR - 5, phase=RenderPhase.REQUEST, template="""<grounding_policy>...""")
    + _DOMAIN_LAYERS: Dict[str, PromptLayer] = { ..., "toolless_data_grounding": TOOLLESS_DATA_GROUNDING_LAYER, ...}

- path: `packages/ai-parrot/src/parrot/bots/prompts/`
  lines: n/a
  symbol: commits
  excerpt: |
    0ddc055b93 2026-10-08 Jesus style(jiraspecialist-agent-multilang): FEAT-638 — lint fixes
    39ce62d924..c5636f7a20 2026-10-08 Jesus feat(jiraspecialist-agent-multilang): TASK-4118/4120/4121/4122 (output_language layer)
    2aec942b38 2026-09-30 revbot feat(infographic-a2ui-display-hints): TASK-4001 — LLM contract text for display hints
    8134e350e4 2026-08-16 Jesus feat(purge-matplotlib-renderer-libs): TASK-2219 — Rewrite system prompts for structured-chart/A2UI

## Notes

- Layers carry `priority` (`LayerPriority` enum), `phase` (CONFIGURE vs REQUEST), `cacheable` (FEAT-181) and now `literal`. A `persona.md` layer would be a CONFIGURE-phase, cacheable, `literal=True` layer — the flag exists precisely for untrusted authored text.
- [cross-lane: type=read, intent=confirm in layers.py which LayerPriority value the identity layer uses and whether PromptBuilder supports replacing a layer by name]
