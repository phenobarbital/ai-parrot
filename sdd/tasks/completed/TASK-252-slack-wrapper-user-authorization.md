# TASK-252: Slack Wrapper — Extend Authorization to Users

**Feature**: Integration User/Channel Whitelisting (FEAT-037)
**Spec**: `sdd/specs/integration-user-limit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-251
**Assigned-to**: claude-session

---

## Context

> Extend `SlackWrapper._is_authorized()` to also check user IDs alongside the existing channel ID check.
> Implements spec Module 4.

---

## Scope

### Extend `_is_authorized()`
- Current signature: `_is_authorized(self, channel_id: str) -> bool`
- New signature: `_is_authorized(self, channel_id: str, user_id: str = None) -> bool`
  - Keep backward compat by defaulting `user_id` to `None`
  - If `allowed_user_ids` is not None and `user_id` not in list → `False`
  - AND logic with existing channel check

### Update Call Sites
- `_handle_events()` — pass `user_id` from `event.get("user")`
- `_handle_command()` — pass `user_id` from `data.get("user_id")`

### Denial Behavior
- Events: return silent `{"ok": true}` (unchanged for channel; same for user)
- Commands: return ephemeral "Unauthorized." message (unchanged for channel; same for user)
- Log at WARNING level with user and channel details for audit

**NOT in scope**: MS Teams changes (TASK-249, TASK-250).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/wrapper.py` | MODIFY | Extend `_is_authorized()`, update call sites |

---

## Implementation Notes

- Keep `user_id` parameter optional with default `None` to maintain backward compat
- When `user_id` is `None`, skip user check (only check channel)
- Use `self.logger.warning()` for audit logging
- The existing event handler already extracts `user_id` from the event but doesn't pass it to `_is_authorized()`

---

## Acceptance Criteria

- [ ] `_is_authorized()` checks both `allowed_channel_ids` and `allowed_user_ids`
- [ ] `user_id` parameter is optional (backward compat)
- [ ] `_handle_events()` passes user_id to authorization check
- [ ] `_handle_command()` passes user_id to authorization check
- [ ] Unauthorized user in events returns silent `{"ok": true}`
- [ ] Unauthorized user in commands returns ephemeral error
- [ ] Unauthorized access logged at WARNING level with details

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/slack/wrapper.py` (especially `_is_authorized`, `_handle_events`, `_handle_command`)
2. **Verify** TASK-251 is complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** wrapper changes
5. **Run** `pytest tests/integrations/slack/ -v`
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Modified `parrot/integrations/slack/wrapper.py`:
- Extended `_is_authorized(channel_id, user_id=None)` with AND logic for both channel and user whitelists
- `user_id` parameter is optional (backward compat — None skips user check)
- Updated `_handle_events()` to pass `user_id` from `event.get("user")` — unauthorized returns silent `{"ok": true}`
- Updated `_handle_command()` to pass `user_id` from `data.get("user_id")` — unauthorized returns ephemeral "Unauthorized."
- WARNING-level audit logging on unauthorized attempts with user and channel details
- All 11 Slack tests pass.
