---
id: F105
query: Q110, Q112, Q113
type: code_analysis
confidence: high
---
# F105: A2UI Catalog Components + Builders

**Directory**: `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/components/`

9 registered components (+ Form which is action-bearing):
  Card, Chart, DataTable, Form, Infographic (composite), KPICard, Map,
  Report (composite), Timeline

**Builders** (`builders.py`): `build_surface`, `build_chart`, `build_kpicard`,
`build_card`, `build_datatable`, `build_infographic`. Pure functions, all
display-only (reject requires_actions via `validate_envelope`).

**Gap for FEAT-301 new blocks**:
The A2UI adapter (`adapters/infographic.py`) maps legacy blocks → A2UI
components. For new blocks, the choices are:
1. **Card-based lowering** (existing fallback): chain/steps/code/card_grid
   all map to Card with body text. Quick but loses structure.
2. **New A2UI catalog components**: register `Code`, `Steps` etc. as new
   components with schemas + lowerings. Correct but scope-expanding.
3. **Hybrid**: use Card for simple cases, add catalog components only for
   blocks that have genuinely different rendering needs (e.g. Code needs
   syntax highlighting, Steps needs sequence semantics).

**Recommendation**: Option 3. The A2UI adapter extension for new blocks
should be a separate task within FEAT-301 (or a follow-up). The HTML
renderer is the primary consumer and doesn't go through A2UI.
