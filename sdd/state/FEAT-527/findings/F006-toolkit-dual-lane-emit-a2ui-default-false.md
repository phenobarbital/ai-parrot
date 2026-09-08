---
id: F006
query_id: Q012
type: read
intent: InfographicToolkit render path and its A2UI wiring
executed_at: 2026-09-04T19:45:00Z
parent_id: null
depth: 0
---
# F006 — InfographicToolkit is HTML-first; A2UI is an opt-in additive lane (emit_a2ui=False) that no production caller enables
## Summary
`InfographicToolkit.render()` always: validates template/blocks/theme → `self._renderer.render_to_html()` (the deprecated `InfographicHTMLRenderer`, constructed in `__init__` via `get_infographic_html_renderer()()`, so every toolkit construction trips the FEAT-273 DeprecationWarning) → optional LLM "enhance" pass → persist HTML artifact → returns `InfographicRenderResult` (html_url/html_inline/template_name/theme/a2ui_envelope). Only when `emit_a2ui=True` does `_build_a2ui_envelope()` call the adapter and serialise a v1.0 envelope; failure degrades to HTML-only ("A2UI lane is additive (spec G7)"). A repo-wide grep for `emit_a2ui=True` hits ONLY `examples/agents/a2ui/a2ui_dashboard_walkthrough.py`. All production constructors use the default: `InfographicAuthoringMixin`, `InfographicTalk._get_render_toolkit`, `ResultAgent`; AgentStudio passes arbitrary `**params` (could enable it per agent). A second tool, `render_template`, fills trusted HTML+Jinja templates via `TemplateEngine` — this is the only Jinja in the infographic stack.
## Citations
- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 1-13, 159-172
  symbol: `InfographicRenderResult`
  excerpt: |
    artifact_id, html_url, html_inline, template_name, theme, data_variables, enhanced, a2ui_envelope: Optional[Dict]
- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 213-264
  symbol: `InfographicToolkit.__init__`
  excerpt: |
    emit_a2ui: bool = False  # "When True, the render tools additionally produce a validated A2UI CreateSurface (FEAT-273 Module 11, D1a lane)"
    self._renderer = get_infographic_html_renderer()()
    self._template_engine = TemplateEngine(template_dirs=template_dirs)  # trusted HTML+Jinja for render_template
- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 402-522
  symbol: `InfographicToolkit.render`
  excerpt: |
    skeleton = self._renderer.render_to_html(infographic_response, theme=validated_theme)
    ...
    a2ui_envelope = None
    if self._emit_a2ui:
        a2ui_envelope = self._build_a2ui_envelope(infographic_response, artifact_id)
- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 524-560
  symbol: `InfographicToolkit.render_template` (HTML+Jinja lane)
- path: `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py`
  lines: 846-899
  symbol: `InfographicToolkit._build_a2ui_envelope`
- path: `packages/ai-parrot/src/parrot/bots/mixins/infographic_authoring.py`
  lines: 84-89
  excerpt: |
    infographic_toolkit = InfographicToolkit(artifact_store=..., recipe_store=..., template_dirs=...)  # no emit_a2ui
- path: `packages/ai-parrot-server/src/parrot/handlers/infographic.py`
  lines: 535-538
- path: `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py`
  lines: 436
  excerpt: |
    toolkit = InfographicToolkit(artifact_store=artifact_store, **params)
- path: `packages/ai-parrot/src/parrot/bots/flows/result_agent.py`
  lines: 142, 171
- path: `examples/agents/a2ui/a2ui_dashboard_walkthrough.py`
  lines: 9, 195-197
  excerpt: |
    toolkit = InfographicToolkit(artifact_store=artifact_store, emit_a2ui=True)
- path: `packages/ai-parrot/tests/tools/test_infographic_toolkit_a2ui_wiring.py`
  lines: 1-11
