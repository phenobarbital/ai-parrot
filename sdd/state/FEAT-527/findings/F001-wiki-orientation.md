---
id: F001
query_id: Q001-Q004
type: wiki_query
intent: orient across infographic renderer/themes/templates, A2UI infographic surface, AgentTalk, block registry
executed_at: 2026-09-04T19:45:00Z
parent_id: null
depth: 0
---
# F001 — Wiki orientation (4 free queries)
## Summary
Four wiki queries located the three code families involved: (a) the legacy structured-infographic lane (helpers façade, TASK-644 theme system, FEAT-095 handler); (b) the A2UI lane (FEAT-273 Module 11 toolkit wiring test, adapters package, FEAT-499 builders, ui_surfaces UISurfaceKind); (c) AgentTalk hooks (FEAT-197 TASK-1320 OutputMode.INFOGRAPHIC, _format_infographic_response) and the Svelte block registry (FEAT-039).
## Citations
- path: `packages/ai-parrot/src/parrot/helpers/infographics.py` (wiki score 0.00 but exact title match) — template+theme registry façade
- path: `packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py` (score 1.00) — InfographicToolkit → A2UI adapter wiring, FEAT-273 M11
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/__init__.py` (0.56) — legacy output models → A2UI envelopes
- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py` symbol `UISurfaceKind` (0.34)
- path: `packages/ai-parrot-server/src/parrot/handlers/agent.py` symbols `AgentTalk._format_infographic_response`, `AgentTalk._extract_infographic_explanation`
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/canvas/infographic/infographic-registry.ts` (1.00)
- path: `sdd/proposals/infographic-html-output.brainstorm.md` (1.00) — 2026-04-10 content-negotiation brainstorm
- path: `docs/frontend/agentdashboard-a2ui-reference.md` (0.44)
