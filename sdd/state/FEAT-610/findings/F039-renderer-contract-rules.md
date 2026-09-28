---
id: F039
query_id: Q031
type: read
intent: Frontend renderer rules from the dashboard reference (interception, degradation, capabilities)
executed_at: 2026-09-28T18:24:17Z
parent_id: null
depth: 0
---
# F039 — Dashboard reference: intercept composites natively, lower the rest, never throw (degrade visibly)
## Summary
`docs/frontend/agentdashboard-a2ui-reference.md` (1101 lines) is the renderer-author contract: render Parrot composites (Chart, DataTable, Infographic, FilterBar) natively and lower anything unsupported to Basic primitives; never throw on an unknown component — render a notice Text (`"[<Component> not supported here: <reason>]"`, `parrot_role: notice`) keeping the original id and collect `degraded[]` records. It tabulates registered renderers' `RendererCapabilities` (interactive-html, ssr_html, pdf, echarts, folium_map, adaptive_cards) and states a live renderer would be `interactive, supports_actions, supports_updates, output "live"`. It also notes Chart → `AppChart`, DataTable → `DataTable.svelte`, lazy-importing heavy libs (ECharts/Leaflet). FEAT-598 linked-surface semantics are in `docs/outputs/a2ui-linked-surfaces.md` (Lane A).
## Citations
- path: `docs/frontend/agentdashboard-a2ui-reference.md`
  lines: 497-499
  symbol: `§5.2`
  excerpt: |
    ... the backend renderers **intercept** `Chart`, `DataTable`, `Infographic` (and FilterBar) before lowering
    and lower the rest. **Do the same**: render these natively, lower anything you do not support.
- path: `docs/frontend/agentdashboard-a2ui-reference.md`
  lines: 576-592
  symbol: `§5.3 Renderer capabilities contract to mirror`
  excerpt: |
    | `interactive-html` | ✓ | ✗ | ✗ | `text/html` | 18 Basic + `Chart`, `DataTable`, `Infographic`, ...
    | `echarts` | ✗ | ✗ | ✗ | `application/json` | `Chart`, `Graph` ...
    Rule inherited from `renderers/degrade.py`: **never throw on an unsupported component** — render a visible notice `Text`
- path: `docs/frontend/agentdashboard-a2ui-reference.md`
  lines: 935
  symbol: `-`
  excerpt: |
    - **Chart / Map / DataTable feed existing components**: `Chart` → `AppChart.svelte` ... Lazy-import these exactly
      like `ChatBubble.svelte` does so the global FloatingChat does not pull ECharts/Leaflet.
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/degrade.py`
  lines: 46
  symbol: `degradation_record`
  excerpt: |
    def degradation_record(node: BasicNode, reason: str) -> dict[str, Any]:
## Implications
- The FEAT-610 HTML5 renderer should follow the same intercept/lower/degrade rules (render KPICard/Chart/DataTable/FilterBar natively; Row/Column/Card/Text generically; notice for anything else) so it stays conformant with the catalog.
- If implemented as a Python-registered renderer, it should declare `RendererCapabilities(interactive=True, supports_updates=True, output="text/html", supported_catalog_ids=[BASIC, DEFAULT])`.
- Doc line 511 ("There is no ECharts option on the wire") confirms echarts options must be derived client-side from Chart props.
