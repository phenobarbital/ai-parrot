---
id: F013
query_id: Q012
type: read
intent: server-lane refresh, persistence, share, PBAC guard
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F013 — Server lane: publish → persist → refresh(params) → share → PBAC

## Summary
Refresh route returns 409 non-refreshable / stale CAS, 403 no-guard or deny, runs owner pctx even for share bearer, params per-source or broadcast, warnings in X-Parrot-Refresh-Warnings. Save paths: REST _pin_save, publish_surface mixin, PublishSurfaceTool (defaults guard=None → fails closed unless linked_service injected). Guard only registered when PBAC loads from PARROT_PBAC_POLICY_DIR; resource query_slug id "<tenant|public>:<slug>" action source:read; no such policy in policies/. GET ?format=html renders stored snapshot without executing. ensure_snapshot owner re-check is present (FEAT-610 F008 note stale).

## Citations
- path: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`
  lines: 275-304, 508-613, 617-736
  symbol: html GET, `_pin_save`, refresh route
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/linked/service.py`
  lines: 70-229
  symbol: `LinkedSurfaceService` (_assert_sources_allowed l.127, params l.161-171)
- path: `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`
  lines: 533-545
  symbol: publish_surface
- path: `packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py`
  lines: 213-221
  symbol: `PublishSurfaceTool`
- path: `packages/ai-parrot/src/parrot/auth/pbac.py`
  lines: 292-348
  symbol: `setup_dataplane_guard`
- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  lines: 2304, 2325, 2337-2338, 2707-2731
  symbol: guard wiring, agent surface mirror route, share routes
