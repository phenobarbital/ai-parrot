---
id: F002
query_id: Q005,Q006,Q008
type: read
intent: are infographic templates Jinja/HTML or Pydantic?
executed_at: 2026-09-04T19:45:00Z
parent_id: null
depth: 0
---
# F002 — "Templates" are Pydantic block-order specs, not Jinja/HTML
## Summary
There is no `parrot/outputs/infographic` package. `InfographicTemplate` (`parrot/models/infographic_templates.py`) is a Pydantic model: an ordered `block_specs: List[BlockSpec]`, `default_theme`, optional `js_bundles`. Its only behaviour is `to_prompt_instruction()` — it renders LLM prompt text ("The infographic MUST contain the following blocks IN THIS EXACT ORDER"). Ten built-ins are registered on `infographic_registry`: basic, executive, dashboard, comparison, timeline, minimal, financial_variance, multi_tab, crew_report (+ an echarts JSBundle). No Jinja anywhere in these models. A grep for jinja/Environment/.html over the models returned nothing.
## Citations
- path: `packages/ai-parrot/src/parrot/models/infographic_templates.py`
  lines: 21-45
  symbol: `BlockSpec`
  excerpt: |
    block_type: BlockType; required: bool = True; description; min_items; max_items; constraints: Dict[str,str]
- path: `packages/ai-parrot/src/parrot/models/infographic_templates.py`
  lines: 47-68
  symbol: `InfographicTemplate`
  excerpt: |
    name, description, block_specs: List[BlockSpec], default_theme: Optional[str], js_bundles: Optional[List[JSBundle]]
- path: `packages/ai-parrot/src/parrot/models/infographic_templates.py`
  lines: 69-110
  symbol: `InfographicTemplate.to_prompt_instruction`
- path: `packages/ai-parrot/src/parrot/models/infographic_templates.py`
  lines: 169,202,251,289,323,354,375,453,482
  symbol: registered template names (basic … crew_report)
- path: `packages/ai-parrot/src/parrot/models/infographic_templates.py`
  lines: 512-587
  symbol: `InfographicTemplateRegistry`, `infographic_registry`
- path: `packages/ai-parrot/src/parrot/helpers/infographics.py`
  lines: 1-15, 18-47, 82-112
  symbol: `list_templates`, `get_template`, `list_themes`, `get_theme` (façade)
