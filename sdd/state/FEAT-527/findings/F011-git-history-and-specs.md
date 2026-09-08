---
id: F011
query_id: Q015, spec-status
type: git_log
intent: recent activity and governing specs
executed_at: 
parent_id: null
depth: 0
---
# F011 — Both lanes received investment in the last 30 days; all governing specs are "approved"; no open SDD task covers an infographic→A2UI migration
## Summary
`git log --since=120 days` over the infographic/adapter/UI paths shows 40 commits, all by the repo owner(s). Newest: FEAT-493 (2026-09-01/02) migrated the *legacy* infographic HTML lane onto the DesignSystem composer (TASK-2706/2712) — i.e. investment in the lane FEAT-273 G7 deprecates; FEAT-476 (2026-08-30) flagged the infographic canvas surface in the bundled UI; FEAT-470 (2026-08-28) remapped the Infographic adapter to v1.0 primitives; FEAT-301 (2026-08-19, 11 commits) added 7 new block types + HTML renderers + adapter converters for them; a "wip: info agent" commit (2026-08-29) touched toolkit/emission/data.py wiring. Specs FEAT-095, 273, 301, 470, 476, 491, 492, 493 are all `Status: approved`. The task-index scan found no pending task in any infographic/a2ui/html-renderer feature (only FEAT-476 TASK-2598 "done-with-issues"). Branches `claude/a2ui-infografias-audit-wtp9eu` and `claude/agenttalk-infographic-toolkit-0q473i` exist on origin (not inspected).
## Citations
- commit `e4628fcea` 2026-09-02 — feat(html-renderer-design-system): TASK-2712 — migrate the infographic HTML lane onto the composer
- commit `e5f6a3c16` 2026-09-01 — TASK-2706 — ThemeConfig layout tokens + CSS-variable emission
- commit `d81ac63df` 2026-08-30 — feat(agentchat-migration): TASK-2595 — Flagged surfaces: canvas, charts, maps, infographic
- commit `69422348d` 2026-08-29 — wip: info agent (toolkit, emission.py, data.py, models/infographic.py, a2ui wiring tests)
- commit `8d62f8c89` 2026-08-28 — feat(a2ui-v1-dialect): TASK-2541 — Infographic adapter remap to v1.0 primitives
- commit `bd0fbbe41` 2026-08-19 — TASK-2257 — A2UI Adapter Explicit Converters for the 4 New Block Types
- commit `a4d7059ed` 2026-08-19 — TASK-2253 — HTML Renderers for chain / steps / code / card_grid
- commit `076814287` 2026-08-14 — feat(a2ui): add InfographicResponse → CreateSurface adapter
- commit `eb74b3326` 2026-05-28 — TASK-1358 — move infographic/messaging/utility renderers to satellite (FEAT-200)
- path: `sdd/specs/a2ui-implementation.spec.md` (FEAT-273, approved) — G7 deprecation policy
- path: `sdd/specs/html-renderer-design-system.spec.md` (FEAT-493, approved)
- path: `sdd/specs/a2ui-v1-dialect.spec.md` (FEAT-470, approved)
- path: `sdd/specs/infographic-theme-catalog-a2ui.spec.md` (FEAT-301, approved)
- path: `sdd/specs/a2ui-surface-rehydration.spec.md` (FEAT-492, approved)
- path: `sdd/specs/flex-agent-infographic-a2ui.spec.md` (FEAT-491, approved)
- path: `sdd/specs/agentchat-migration.spec.md` (FEAT-476, approved)
- path: `sdd/specs/get-infographic-handler.spec.md` (FEAT-095, approved)
- path: `sdd/tasks/index/agentchat-migration.json` — TASK-2598 done-with-issues (only non-done task in scope)
- path: `docs/infographic_handler_api.md` lines 1-8 — FEAT-095 contract for the navigator frontend (HTML/JSON lane)
- path: `sdd/proposals/infographic-html-output.brainstorm.md` lines 1-25 — 2026-04-10 origin of the HTML lane (BlockCanvas expected HTML)
