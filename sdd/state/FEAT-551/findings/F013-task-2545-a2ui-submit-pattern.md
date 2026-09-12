---
id: F013
query_id: Q012
type: read
intent: Teams native-input pattern + a2ui_action envelope
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F013 — TASK-2545 / A2UI Adaptive Cards renderer — envelope-in-Submit pattern

## Summary
The A2UI Adaptive Cards renderer (ai-parrot-visualizations) is the shipped precedent for a card whose `Action.Submit.data` carries a routing envelope (`{"a2ui_action": <v1.0 action envelope>, "surfaceId": ...}`) that a receiver (the Teams wrapper) unwraps; input ids are RFC 6901 tilde-escaped because some Teams clients reject `/` in ids (FormDesigner field_ids have no `/`, so no encoding is needed there). `Button{openUrl}` → `Action.OpenUrl`. It builds elements through the typed `parrot.outputs.cards` models.

## Citations
- path: `sdd/tasks/completed/TASK-2545-adaptive-cards-native-inputs-teams-submit.md`
  lines: 20-24
  excerpt: |
    Button{action.event}→Action.Submit{data:{a2ui_action:<sobre action v1.0>, surfaceId}}, Button{openUrl}→Action.OpenUrl;
    Input.id = path del binding (codificado si Teams rechaza `/`)
    msteams/wrapper.py: rama a2ui_action → turno estructurado {"type":"a2ui_action","action":<sobre>,"values":{...}}
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`
  lines: 15-40
  symbol: module docstring (TASK-2545 native inputs + actions)
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`
  lines: 112-136
  symbol: `_encode_binding_id`, `_decode_binding_id`
- path: `packages/ai-parrot-visualizations/src/parrot/outputs/a2ui_renderers/adaptive_cards.py`
  lines: 608-650
  symbol: `AdaptiveCardsRenderer._render_Button`
  excerpt: |
    state.actions.append(ActionSubmit(title=title, data={"a2ui_action": serialize_a2ui_message(message), "surfaceId": state.surface_id}))
    elif action.function_call.call == "openUrl": state.actions.append(ActionOpenUrl(title=title, url=url))
