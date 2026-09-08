---
id: F010
query_id: Q014, Q016
type: read
intent: the A2UI-native infographic production path (FlexDashboard, recipes, persisted surfaces)
executed_at: 
parent_id: F005
depth: 1
---
# F010 — An A2UI-native infographic lane already exists end-to-end on the backend: FlexDashboard (FEAT-491), recipes (FEAT-324), persisted ui_surfaces (FEAT-492), and a reference doc for the external navigator frontend
## Summary
`agents/flex_dashboard.py` composes `NarrativeMixin + InfographicAuthoringMixin + PandasAgent`; its dashboard is a recipe whose `LayoutSpec` root is `component="Infographic"` with five sections → Tabs, replayed by `RecipeRunner` and refreshed by the `refresh_dashboard` agent function. `PgUISurfaceStore` (FEAT-492) persists A2UI surfaces with `UISurfaceKind ∈ {dashboard, infographic, widget}`, share tokens and JSON/HTML negotiation. `docs/frontend/agentdashboard-a2ui-reference.md` (verified against dev@a1eca82b4, 2026-09-02) tells the **navigator-frontend-next** team to build a new Svelte 5 A2UI renderer; §6.1 states an *Infographic* kind is "an LLM-authored Infographic surface (InfographicToolkit …)" requested with `output_mode: "a2ui"`. §11 lists 16 known gaps, incl. `interactive-html` not resolvable from a cold registry and the recipe narrative never reaching the envelope.
## Citations
- path: `agents/flex_dashboard.py`
  lines: 1-16, 127, 432-439, 568
  symbol: `FlexDashboard`
  excerpt: |
    class FlexDashboard(NarrativeMixin, InfographicAuthoringMixin, PandasAgent):
    component="Infographic",  # LayoutSpec root
- path: `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`
  lines: 1-20
  symbol: `InfographicAuthoringMixin`
- path: `packages/ai-parrot/src/parrot/bots/info.py`
  lines: 33-43
  symbol: `InfoAgent` (NarrativeMixin, InfographicAuthoringMixin, Agent)
- path: `packages/ai-parrot-server/src/parrot/handlers/models/ui_surfaces.py`
  lines: 1-17, 39-45, 48-70
  symbol: `UISurfaceKind`, `UISurfaceRecord`
- path: `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py`
  lines: 11, 30-38, 187
- path: `packages/ai-parrot-server/src/parrot/handlers/a2ui.py`
  lines: 1-13
  symbol: `A2UIHandler` (separate endpoint /api/v1/agents/{agent_id}/a2ui; spec §8 rejected routing A2UI through AgentTalk POST)
- path: `packages/ai-parrot/src/parrot/tools/infographic_recipes/__init__.py`
  lines: 1-6
  symbol: `RecipeRunner`
- path: `docs/frontend/agentdashboard-a2ui-reference.md`
  lines: 1-20, §6.1-6.3, §11 items 1,4,14
  excerpt: |
    | Infographic | an LLM-authored Infographic surface (InfographicToolkit, producer loop with catalog validation and up to 3 attempts) | Infographic | infographic-<12hex> |
    Infographic request: {"query": "/infographic ...", "output_mode": "a2ui"}
