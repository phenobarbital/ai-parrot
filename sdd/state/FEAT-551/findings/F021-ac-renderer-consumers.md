---
id: F021
query_id: Q009
type: grep
intent: Who consumes AdaptiveCardRenderer today
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F021 — Teams dialog presets depend on AdaptiveCardRenderer and strip underscore keys

## Summary
`msteams/dialogs/presets/base.py` imports `AdaptiveCardRenderer` from `parrot_formdesigner.renderers` and instantiates it per step (`_get_card_renderer`); it merges submitted values into form_data skipping keys that start with `_` (control keys like `_action`). The legacy `dialogs/card_builder.py` no longer exists. Therefore any change to the default Submit `data` of `AdaptiveCardRenderer` is consumed by the in-dialog Teams flow too — additive underscore-prefixed keys are safe, renaming `_action` is not.

## Citations
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/presets/base.py`
  lines: 13-14
  excerpt: |
    from parrot_formdesigner.renderers import AdaptiveCardRenderer
    from parrot_formdesigner.services.validators import FormValidator
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/presets/base.py`
  lines: 160-176
  symbol: submitted-value merge + `_get_card_renderer`
  excerpt: |
    for key, value in submitted.items():
        if not key.startswith('_'):
            form_data[key] = value
    def _get_card_renderer(self) -> AdaptiveCardRenderer: return AdaptiveCardRenderer()
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/presets/base.py`
  lines: 182-196
  symbol: `send_card` — `CardFactory.adaptive_card(card)` + `MessageFactory.attachment`
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/orchestrator.py`
  lines: 765
  excerpt: |
    "data": {"_action": "dismiss"},
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/card_builder.py`
  symbol: DOES NOT EXIST (migrated away by TASK-524)
