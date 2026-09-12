---
id: F008
query_id: Q008
type: grep
intent: Where Adaptive Card Input.*/Action.Submit code lives
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — Adaptive Card input/action builders across the repo

## Summary
Five code sites emit `Input.*`/`Action.Submit`: (1) core typed models `parrot.outputs.cards` (`inputs.py`, `actions.py`) — Pydantic AC 1.5 element models used by the shared card builder; (2) the A2UI Adaptive Cards renderer in ai-parrot-visualizations (TASK-2545); (3) `msteams/hitl_cards.py` (`TeamsCardRenderer`, InteractionType → card, every Submit carries `interaction_id`); (4) `msagentsdk/cards.py` (semantic UI → card, `_ui_action_to_ac_action`); (5) the FormDesigner `AdaptiveCardRenderer` (raw dicts). The "input tools as adaptive cards" code the request refers to is (2)+(3)+(1).

## Citations
- path: `packages/ai-parrot/src/parrot/outputs/cards/inputs.py`
  lines: 17-75
  symbol: `InputText`, `InputNumber`, `InputToggle`, `InputDate`, `InputTime`, `InputChoiceSet`, `InputChoice`
- path: `packages/ai-parrot/src/parrot/outputs/cards/actions.py`
  lines: 17-39
  symbol: `ActionSubmit`, `ActionOpenUrl`, `ActionToggleVisibility`, `ActionShowCard`
  excerpt: |
    class ActionSubmit(ACAction): action_type: Literal["Action.Submit"] = "Action.Submit"
    class ActionOpenUrl(ACAction): action_type: Literal["Action.OpenUrl"]; url: str
- path: `packages/ai-parrot/src/parrot/outputs/cards/attachment.py`
  lines: 10-24
  symbol: `build_attachment`, `build_attachment_from_spec`
- path: `packages/ai-parrot/src/parrot/outputs/cards/renderer.py`
  lines: 273-280
  symbol: `_expand_form`, `_build_form_field`
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/hitl_cards.py`
  lines: 1-36
  symbol: `TeamsCardRenderer` (module docstring)
  excerpt: |
    every Action.Submit.data payload carries {"hitl": true, "interaction_id": "<uuid>", ...}
    form_schema -> Input.* mapping: string->Input.Text, number->Input.Number, boolean->Input.Toggle,
    choice->Input.ChoiceSet, date->Input.Date, time->Input.Time, unknown->Input.Text
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/cards.py`
  lines: 64-69
  symbol: `_ui_action_to_ac_action`
  excerpt: |
    prompt_template actions render as Action.Submit ...; url actions as Action.OpenUrl
- path: `packages/ai-parrot-integrations/src/parrot/human/channels/teams.py`
  lines: 1-20
  symbol: Teams HITL Human Channel (uses `TeamsCardRenderer`)
