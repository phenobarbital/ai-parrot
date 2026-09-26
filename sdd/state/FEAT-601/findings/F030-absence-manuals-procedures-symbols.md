---
id: F030
query_id: Q030
type: grep
intent: Absence proof — ManualCard|ProceduresToolkit|ProcedureRetrieval|procedures.ontology|knowledge/manuals|knowledge.manuals|start_guided|guided_mode|ChecklistBlock|StepsBlock in packages (*.py, *.yaml)
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F030 — Every procedure/manual symbol is absent; only the display-only infographic StepsBlock/ChecklistBlock exist

## Summary
There are zero hits for ManualCard, ProceduresToolkit, ProcedureRetrieval, procedures.ontology, knowledge/manuals, knowledge.manuals, start_guided and guided_mode anywhere under `packages/` (*.py, *.yaml, *.yml). The only hits are `ChecklistBlock` and `StepsBlock`. They are defined in `parrot/models/infographic.py`, re-exported from `parrot/models/__init__.py`, and rendered by `infographic_html.py`. These are pure display models. Stale copies also exist under `packages/ai-parrot/build/lib.linux-x86_64-cpython-312/` and should be ignored.

## Citations
- path: `packages/ai-parrot/src/parrot/models/infographic.py`
  lines: 933, 962 (item models 247, 282; 1008-1011)
  symbol: `ChecklistBlock`, `StepsBlock`
  excerpt: |
    933: class ChecklistBlock(BaseModel):
    962: class StepsBlock(BaseModel):
- path: `packages/ai-parrot/src/parrot/models/__init__.py`
  lines: 47, 52, 179, 184
  symbol: re-exports of ChecklistBlock / StepsBlock
  excerpt: |
    ChecklistBlock, StepsBlock re-exported in parrot.models
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/infographic_html.py`
  lines: 59, 65, 95, 99, 1359-1363, 1600-1604
  symbol: `_render_checklist`, `_render_steps`
  excerpt: |
    95:    "checklist": ChecklistBlock,
    99:    "steps": StepsBlock,
    1600:    def _render_steps(self, block: StepsBlock) -> str:

## Notes
- The absence claim is confirmed. The names `StepsBlock`/`ChecklistBlock` are taken by the infographic models, so new procedure models must not reuse them in `parrot.models`.
