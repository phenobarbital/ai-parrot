---
id: F002
queries: [Q005, Q006, Q007]
confidence: high
---

# Named infographic templates already drive LLM prompt generation

`InfographicTemplate` (models/infographic_templates.py:47-152) carries:
- `name: str` — e.g. `"basic"`, `"dashboard"`
- `description: str`
- `block_specs: List[BlockSpec]` — ordered slots, each with `block_type`,
  `required`, `description`, `min_items`, `max_items`, `constraints` dict
- `default_theme: Optional[str]`

`to_prompt_instruction()` (line 60-152) generates the exact LLM prompt:
"Generate an infographic using the 'X' layout. ... contain the following
blocks IN THIS EXACT ORDER: ..." with per-slot REQUIRED/OPTIONAL markers,
item counts, and per-slot description text. Tab_view layouts get extended
instructions.

**Built-in templates** (lines 155-391): `basic`, `executive`, `dashboard`
(very close to user's mockup — 6-8 hero cards + line chart + pie chart +
table), `comparison`, `timeline`, `minimal`, `multi_tab`.

`InfographicTemplateRegistry` (lines 398-467) is a singleton at
`infographic_registry` (line 471). It supports `register(template)`,
`get(name)`, `list_templates()`, `list_templates_detailed()`.

**Templates can be registered programmatically** via the SDK helper at
`packages/ai-parrot/src/parrot/helpers/infographics.py:50-79`
(`register_template(InfographicTemplate | dict)`) or via the dedicated
HTTP endpoint `POST /api/v1/agents/infographic/templates`
(handlers/infographic.py:352-400) — gated on PBAC `agent:configure`.

`BlockType` enum (models/infographic.py:45-61) has 15 members including
`title`, `hero_card`, `chart`, `bullet_list`, `table`, `image`, `quote`,
`callout`, `divider`, `timeline`, `progress`, `accordion`, `checklist`,
`tab_view`. `ChartType` enum (lines 64-77) has 12 members including bar,
line, area, waterfall, gauge.

Theme system (models/infographic.py:751-929): `ThemeConfig` + singleton
`theme_registry` with built-ins `light`, `dark`, `corporate`, `midnight`.

## Citations
- packages/ai-parrot/src/parrot/models/infographic_templates.py:47-152 —
  `InfographicTemplate.to_prompt_instruction()`
- packages/ai-parrot/src/parrot/models/infographic_templates.py:241-276 —
  TEMPLATE_DASHBOARD (closest match to the user's finance mockup)
- packages/ai-parrot/src/parrot/models/infographic_templates.py:398-471 —
  `InfographicTemplateRegistry`
- packages/ai-parrot/src/parrot/helpers/infographics.py:50-79 — programmatic
  template registration
