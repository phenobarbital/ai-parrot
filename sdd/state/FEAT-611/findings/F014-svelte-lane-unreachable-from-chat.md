---
id: F014
query_id: Q011
type: read
intent: can the Svelte linked lane be reached from real agent chat
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F014 — Svelte A2UISurface linked lane is unreachable from agent chat

## Summary
Five blockers: (1) InfographicCanvas renders A2UISurface without persistedSurfaceId (no server refresh button); (2) infographic-tab-builder opens no tab for non-Infographic/Report roots; (3) features.a2ui build flag; (4) qs_build_linked_surface returns a plain dict and bots/base.py only lifts InteractiveRenderResult/InfographicRenderResult, emission.finalize_a2ui_response and runtime/dispatch.py don't forward dict envelopes; (5) tool emits inner CreateSurface dump but Svelte expects {version:"v1.0", createSurface:{…}}. Python renderers in ai-parrot-visualizations ignore parrot_data_sources (snapshot only).

## Citations
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/InfographicCanvas.svelte`
  lines: 353
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic-tab-builder.ts`
  lines: 60
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/a2ui/A2UISurface.svelte`
  lines: 40, 105, 119-192
  symbol: `A2UISurface`, serverRefresh
- path: `packages/ai-parrot/src/parrot/bots/base.py`
  lines: 1476-1534
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/emission.py`
  lines: 30-41
  symbol: `finalize_a2ui_response`
- path: `packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py`
  lines: 401-413
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  lines: 683
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py`
  lines: 620-653
