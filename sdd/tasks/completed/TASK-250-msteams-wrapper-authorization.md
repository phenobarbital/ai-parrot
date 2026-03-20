# TASK-250: MS Teams Wrapper — Authorization Check

**Feature**: Integration User/Channel Whitelisting (FEAT-037)
**Spec**: `sdd/specs/integration-user-limit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-249
**Assigned-to**: claude-session

---

## Context

> Add `_is_authorized()` method to `MSTeamsWrapper` and apply authorization checks at all handler entry points.
> Implements spec Module 2.

---

## Scope

### Authorization Method
- Add `_is_authorized(self, conversation_id: str, user_id: str) -> bool`:
  - If `allowed_conversation_ids` is not None and `conversation_id` not in list → `False`
  - If `allowed_user_ids` is not None and `user_id` not in list → `False`
  - Otherwise → `True`
  - Both filters apply with AND logic

### Handler Entry Points
- `on_message_activity()` — check before processing text/voice messages
  - Extract `conversation_id` from `turn_context.activity.conversation.id`
  - Extract `user_id` from `turn_context.activity.from_property.id`
- `_handle_card_submission()` — check before processing card submissions

### Denial Behavior
- Send generic message: "You are not authorized to use this bot."
- Return early (do not process the message)
- Log at WARNING level with user and conversation details for audit

**NOT in scope**: Slack changes (TASK-251, TASK-252).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/wrapper.py` | MODIFY | Add `_is_authorized()`, apply at handler entry points |

---

## Implementation Notes

- Follow the Telegram pattern: check at the top of each handler, return early if unauthorized
- Use `self.logger.warning()` for audit logging with user_id and conversation_id
- Send denial via `await turn_context.send_activity("You are not authorized to use this bot.")`
- Keep the denial message generic — no details about why access was denied

---

## Acceptance Criteria

- [ ] `_is_authorized(conversation_id, user_id)` method implemented with AND logic
- [ ] Authorization check at `on_message_activity()` entry point
- [ ] Authorization check at `_handle_card_submission()` entry point
- [ ] Unauthorized access sends generic denial message
- [ ] Unauthorized access logged at WARNING level with user/conversation details
- [ ] No whitelist (None) allows all users (backward compat)

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/msteams/wrapper.py` (especially `on_message_activity`, `_handle_card_submission`)
2. **Verify** TASK-249 is complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** authorization logic
5. **Run** `pytest tests/integrations/msteams/ -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Modified `parrot/integrations/msteams/wrapper.py`:
- Added `_is_authorized(conversation_id, user_id)` with AND logic for both whitelists
- Authorization check at top of `on_message_activity()` — before any processing
- Authorization check at top of `_handle_card_submission()` — before form handling
- Unauthorized access sends "You are not authorized to use this bot." and returns early
- WARNING-level audit logging with user_id and conversation_id on unauthorized attempts
- All 14 existing MS Teams tests pass. Backward compatible — None defaults allow all.
