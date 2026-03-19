# TASK-254: Integration Tests — Whitelist Full Flow

**Feature**: Integration User/Channel Whitelisting (FEAT-037)
**Spec**: `sdd/specs/integration-user-limit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-250, TASK-252, TASK-253
**Assigned-to**: unassigned

---

## Context

> End-to-end integration tests that verify whitelist authorization through the full message processing flow for both MS Teams and Slack.
> Implements spec Section 4 — Integration Tests.

---

## Scope

### Test Files

**`tests/integrations/msteams/test_msteams_whitelist_integration.py`** (CREATE):
- `test_message_blocked_by_conversation_whitelist` — message from non-whitelisted conversation gets denial
- `test_message_blocked_by_user_whitelist` — message from non-whitelisted user gets denial
- `test_message_allowed_by_whitelist` — message from whitelisted conversation + user is processed
- `test_no_whitelist_allows_all` — no whitelist config allows all messages through

**`tests/integrations/slack/test_slack_whitelist_integration.py`** (CREATE):
- `test_event_blocked_by_user_whitelist` — event with unauthorized user ignored silently
- `test_command_blocked_by_user_whitelist` — slash command returns ephemeral "Unauthorized" error
- `test_event_allowed_with_both_whitelists` — authorized channel + user processes normally
- `test_no_user_whitelist_allows_all_users` — only channel whitelist, any user passes

**NOT in scope**: Live API calls (all mocked).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integrations/msteams/test_msteams_whitelist_integration.py` | CREATE | MS Teams integration tests |
| `tests/integrations/slack/test_slack_whitelist_integration.py` | CREATE | Slack integration tests |

---

## Implementation Notes

- Mock MS Teams `TurnContext`, `Activity`, `ConversationAccount`, `ChannelAccount` for full flow
- Mock Slack `aiohttp.web.Request` with proper event payloads
- Test the handler methods directly with mock objects
- Verify both the authorization check AND the downstream behavior (denial message sent / processing skipped)

---

## Acceptance Criteria

- [ ] All 8 integration tests implemented and passing
- [ ] Full message flow tested for both block and allow scenarios
- [ ] Backward compatibility verified (no whitelist = all allowed)
- [ ] No network calls in tests

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-250, TASK-252, TASK-253 are complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** integration test files
4. **Run** `pytest tests/integrations/msteams/ tests/integrations/slack/ -v`
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. All 8 integration tests implemented and passing:

- `tests/integrations/msteams/test_msteams_whitelist_integration.py` — 4 tests:
  - Blocked by conversation whitelist (denial message sent)
  - Blocked by user whitelist (denial message sent)
  - Allowed with both whitelists (no denial, proceeds to processing)
  - No whitelist allows all messages through
- `tests/integrations/slack/test_slack_whitelist_integration.py` — 4 tests:
  - Event blocked by user whitelist (silently ignored, HTTP 200)
  - Event allowed with both whitelists (message processed)
  - No user whitelist allows all users in channel
  - Command blocked by user whitelist (ephemeral "Unauthorized" response)

All 203 tests pass across MS Teams and Slack integration suites. No network calls. Backward compatibility verified.
