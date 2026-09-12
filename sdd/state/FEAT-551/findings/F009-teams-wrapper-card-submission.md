---
id: F009
query_id: Q009
type: read
intent: Teams wrapper: how Action.Submit payloads are routed
executed_at: 2026-09-10T22:27:13Z
duration_ms: 0
parent_id: null
depth: 0
---

# F009 — Teams wrapper _handle_card_submission routing branches

## Summary
In Teams an `Action.Submit` never hits an HTTP URL — the Bot Framework delivers all input values plus `data` as `turn_context.activity.value` to the bot. `_handle_card_submission` routes by key: `a2ui_token` (deep-link resume), `a2ui_action` (TASK-2545 → structured turn into `form_orchestrator.process_message`), `command` (slash router), then `_action` (`cancel` → cancel dialogs; otherwise `dialog_context.continue_dialog()`). With no active dialog (`DialogTurnStatus.Empty`) it replies "I received your submission but wasn't expecting it" — i.e. a standalone card rendered by the FormDesigner API and posted to Teams has NO receiver today.

## Citations
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 359-372
  symbol: `MSTeamsAgentWrapper._handle_card_submission`
  excerpt: |
    submitted_data = turn_context.activity.value
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 384-411
  symbol: a2ui_token branch
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 413-443
  symbol: a2ui_action branch
  excerpt: |
    a2ui_action = submitted_data.get("a2ui_action")
    values = {self._decode_a2ui_input_id(key): value for key, value in submitted_data.items()
              if key not in ("a2ui_action", "surfaceId")}
    result = await self.form_orchestrator.process_message(message=query, conversation_id=..., context=...)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/wrapper.py`
  lines: 451-491
  symbol: command + _action branches
  excerpt: |
    action = submitted_data.get("_action", "submit")
    if action == "cancel": await dialog_context.cancel_all_dialogs() ...
    results = await dialog_context.continue_dialog()
    elif results.status == DialogTurnStatus.Empty:
        self.logger.warning("Card submission but no active dialog")
        await self.send_text("I received your submission but wasn't expecting it. Please try again.", turn_context)
