---
id: F022
query_id: Q016
type: grep
intent: How A2UI renderers emit actions (client half)
executed_at: 2026-09-10T00:39:55Z
duration_ms: null
parent_id: F016
depth: 1
---

# F022 — Visualization renderers: supports_actions and a2ui_action payload

## Summary

Only `adaptive_cards` declares `supports_actions=True`; `ssr_html` and `interactive_html` declare `supports_actions=False` (they render Button/TextField/CheckBox/ChoicePicker/DateTimeInput but do not dispatch). Adaptive Cards lowers `Button{action.event}` to `Action.Submit` with data `{"a2ui_action": <serialized action envelope>, "surfaceId": ...}`; the MS Teams wrapper unwraps `a2ui_action` and injects `{"type":"a2ui_action","action":...,"values":...}` as a structured agent turn. Deep links (`deeplink.py`) mint one-shot Redis tokens resumed at `/api/v1/a2ui/resume/{channel}`; `a2ui_resume.build_structured_message` uses the same tag.

## Citations

- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  lines: 603-628
  excerpt: |
    RendererCapabilities(interactive=True, supports_actions=False, supports_updates=False, output="text/html", ...)
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/interactive_html.py`
  lines: 1020-1039
  symbol: `_render_prim_TextField / _render_prim_CheckBox / _render_prim_ChoicePicker / _render_prim_DateTimeInput`
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/ssr_html.py`
  lines: 151
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`
  lines: 21-32,216,641
  excerpt: |
    "a2ui_action": serialize_a2ui_message(message),
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 414-428
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/deeplink.py`
  lines: 92-171
  symbol: `DeepLinkService`
- path: `packages/ai-parrot/src/parrot/outputs/a2ui/renderers/__init__.py`
  lines: 51-75
  symbol: `RendererCapabilities`
