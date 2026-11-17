---
id: FC-029
query_id: Q048
type: tree
intent: "R5: structure of the Svelte UI lib (where a Connections panel/store would live)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-029 — ui/src/lib has agents/, api/, components/{agents,charts,common,grid,schema-form,visualizations}, config/, oauth/, services/, shims/, stores/, styles/, types/{generated}, ui/, utils/

## Summary

`find packages/ai-parrot-server/ui/src/lib -maxdepth 2 -type d`: agents, api, components (agents, charts, common, grid, schema-form, visualizations), config, oauth, services, shims, stores, styles/themes, types/generated, ui/components, ui/internal, utils. No `src/routes` directory (component library + AgentChat shell, not SvelteKit routes).

## Citations

- path: `packages/ai-parrot-server/ui/src/lib/oauth`
  lines: —
  symbol: `oauth/`
  excerpt: |
    popup.ts
- path: `packages/ai-parrot-server/ui/src/lib/components/agents/integrations`
  lines: —
  symbol: `integrations/`
  excerpt: |
    IntegrationsMenu.svelte, IntegrationItem.svelte, ConnectIntegrationPill.svelte
- path: `packages/ai-parrot-server/ui/src/lib/stores`
  lines: —
  symbol: `stores/`
  excerpt: |
    Svelte 5 .svelte.ts stores (toast.svelte used by integrations)

## Notes

A `connections.svelte.ts` store would live in `lib/stores/`; the existing `components/agents/integrations/` is the natural home for a Connections panel.
