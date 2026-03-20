# Feature Specification: Integration User/Channel Whitelisting

**Feature ID**: FEAT-037
**Date**: 2026-03-09
**Author**: AI-Parrot Team
**Status**: approved
**Target version**: 1.6.0

---

## 1. Motivation & Business Requirements

> Extend user/channel whitelisting to MS Teams and ensure consistent authorization enforcement across all integration wrappers.

### Problem Statement

The integration wrappers have inconsistent authorization filtering:

| Wrapper | Config Field | Authorization Check | Granularity |
|---------|-------------|-------------------|-------------|
| **Telegram** | `allowed_chat_ids: List[int]` | `_is_authorized()` on every handler | Chat/user level |
| **Slack** | `allowed_channel_ids: List[str]` | `_is_authorized()` on events + commands | Channel level |
| **MS Teams** | **None** | **No filtering** | N/A |

**MS Teams** has no mechanism to restrict which conversations, channels, or users can interact with the bot. Any authenticated user in the Teams tenant/organization can use the bot. This is a security gap for bots handling sensitive operations (finance, HR, compliance) where access should be limited to specific teams or users.

Additionally, while Slack has `allowed_channel_ids`, it lacks **user-level** filtering — any user in an allowed channel can interact with the bot. This may be insufficient for sensitive bots.

### Goals

1. Add `allowed_conversation_ids` to `MSTeamsAgentConfig` — whitelist specific Teams conversations/channels
2. Add `allowed_user_ids` to `MSTeamsAgentConfig` — whitelist specific Teams users
3. Add `allowed_user_ids` to `SlackAgentConfig` — whitelist specific Slack users (complement to existing `allowed_channel_ids`)
4. Implement `_is_authorized()` in `MSTeamsWrapper` with consistent behavior
5. Apply authorization checks at all handler entry points
6. Ensure backward compatibility — `None` (default) means "allow all" for every field

### Non-Goals

- Changing Telegram's existing `allowed_chat_ids` behavior (already working correctly)
- Role-based access control (RBAC) — whitelists are simple allow-lists
- Dynamic whitelist management (add/remove at runtime) — config-driven only
- Integration with external identity providers for authorization decisions
- Adding `allowed_user_ids` to Telegram (Telegram's `allowed_chat_ids` covers this since private chats have user-specific IDs)

---

## 2. Architectural Design

### Overview

Follow the same pattern established by Telegram: an optional list field on the config dataclass, a simple `_is_authorized()` method on the wrapper, and checks at every handler entry point. The authorization logic is: if the whitelist is `None`, allow all; if set, the identifier must be in the list.

### Authorization Logic

```
_is_authorized(*, conversation_id, user_id) -> bool:
    if allowed_conversation_ids is not None:
        if conversation_id not in allowed_conversation_ids:
            return False
    if allowed_user_ids is not None:
        if user_id not in allowed_user_ids:
            return False
    return True
```

Both filters apply independently (AND logic): a request must pass both the conversation whitelist **and** the user whitelist to be authorized.

### Integration Points

| Component | Change | Description |
|-----------|--------|-------------|
| `parrot/integrations/msteams/models.py` | MODIFY | Add `allowed_conversation_ids`, `allowed_user_ids` fields |
| `parrot/integrations/msteams/wrapper.py` | MODIFY | Add `_is_authorized()`, apply at handler entry points |
| `parrot/integrations/slack/models.py` | MODIFY | Add `allowed_user_ids` field |
| `parrot/integrations/slack/wrapper.py` | MODIFY | Extend `_is_authorized()` to also check user IDs |

### Data Models

#### MS Teams — `MSTeamsAgentConfig` (new fields)

```python
# Whitelist of Teams conversation IDs. None = allow all.
allowed_conversation_ids: Optional[List[str]] = None
# Whitelist of Teams user IDs. None = allow all.
allowed_user_ids: Optional[List[str]] = None
```

#### Slack — `SlackAgentConfig` (new field)

```python
# Whitelist of Slack user IDs (e.g., "U0123ABC"). None = allow all.
allowed_user_ids: Optional[List[str]] = None
```

---

## 3. Module Breakdown

### Module 1: MS Teams Config Updates

**File**: `parrot/integrations/msteams/models.py`

- Add `allowed_conversation_ids: Optional[List[str]] = None` field
- Add `allowed_user_ids: Optional[List[str]] = None` field
- Update `from_dict()` to parse both new fields from YAML config

### Module 2: MS Teams Wrapper Authorization

**File**: `parrot/integrations/msteams/wrapper.py`

- Add `_is_authorized(self, conversation_id: str, user_id: str) -> bool` method
- Add authorization checks at:
  - `on_message_activity()` — before processing any text/voice message
  - `_handle_card_submission()` — before processing card submissions
- On unauthorized access, send a polite denial message and return early
- Log unauthorized access attempts at WARNING level

### Module 3: Slack Config Updates

**File**: `parrot/integrations/slack/models.py`

- Add `allowed_user_ids: Optional[List[str]] = None` field
- Update `from_dict()` to parse the new field from YAML config

### Module 4: Slack Wrapper Authorization Extension

**File**: `parrot/integrations/slack/wrapper.py`

- Extend `_is_authorized()` to accept and check `user_id` parameter
- Update call sites in `_handle_events()` and `_handle_command()` to pass user ID
- On unauthorized user, return a silent `{"ok": true}` (events) or ephemeral "Unauthorized" message (commands)

---

## 4. Testing Strategy

### Unit Tests

**`tests/integrations/msteams/test_msteams_config_whitelist.py`** (CREATE):
- `test_config_allowed_conversation_ids_default_none` — default is None (allow all)
- `test_config_allowed_user_ids_default_none` — default is None (allow all)
- `test_config_from_dict_with_whitelist` — `from_dict()` parses both fields
- `test_config_from_dict_without_whitelist` — backward compat, fields default to None

**`tests/integrations/msteams/test_msteams_authorization.py`** (CREATE):
- `test_authorized_when_no_whitelist` — None lists allow all
- `test_authorized_conversation_in_list` — conversation ID in whitelist passes
- `test_unauthorized_conversation_not_in_list` — conversation ID not in whitelist blocked
- `test_authorized_user_in_list` — user ID in whitelist passes
- `test_unauthorized_user_not_in_list` — user ID not in whitelist blocked
- `test_both_filters_must_pass` — conversation OK + user blocked = unauthorized
- `test_on_message_unauthorized_sends_denial` — unauthorized message gets denial response

**`tests/integrations/slack/test_slack_user_whitelist.py`** (CREATE):
- `test_config_allowed_user_ids_default_none` — default is None
- `test_config_from_dict_with_user_whitelist` — `from_dict()` parses field
- `test_authorized_channel_and_user` — both pass
- `test_unauthorized_user` — user not in whitelist blocked
- `test_channel_authorized_user_not` — channel OK + user blocked = unauthorized

### Integration Tests

**`tests/integrations/msteams/test_msteams_whitelist_integration.py`** (CREATE):
- `test_message_blocked_by_conversation_whitelist` — full message flow rejected
- `test_message_allowed_by_whitelist` — full message flow accepted

**`tests/integrations/slack/test_slack_whitelist_integration.py`** (CREATE):
- `test_event_blocked_by_user_whitelist` — event with unauthorized user ignored
- `test_command_blocked_by_user_whitelist` — slash command returns ephemeral error

---

## 5. YAML Configuration Examples

### MS Teams

```yaml
agents:
  FinanceBot:
    chatbot_id: finance_agent
    allowed_conversation_ids:
      - "19:abc123@thread.tacv2"
      - "19:def456@thread.tacv2"
    allowed_user_ids:
      - "29:1abc-2def-3ghi"
      - "29:4jkl-5mno-6pqr"
```

### Slack

```yaml
agents:
  HRBot:
    chatbot_id: hr_agent
    bot_token: xoxb-...
    allowed_channel_ids:
      - "C0123ABCDEF"
    allowed_user_ids:
      - "U0123ABCDEF"
      - "U9876ZYXWVU"
```

---

## 6. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing configs with no whitelist | High | All new fields default to `None` (allow all) — zero-change backward compat |
| Performance impact on large whitelists | Low | List membership check is O(n); for very large lists, could convert to set internally |
| Unauthorized denial message reveals bot existence | Low | Keep denial message generic; log details server-side only |
| MS Teams conversation IDs change format between versions | Medium | Document expected ID format; use string comparison (no parsing) |

---

## 7. Open Questions

1. **Denial behavior for MS Teams**: Should unauthorized users receive a message ("You are not authorized") or should the bot silently ignore? Telegram sends a message; Slack silently ignores events: Users needs a message but with no details, only an "You are not authorized" is sufficient.
2. **Should `allowed_user_ids` support env var resolution?** E.g., `{NAME}_ALLOWED_USER_IDS` as a comma-separated env var fallback: Yes
3. **Audit logging**: Should unauthorized access attempts be logged with user details for security audit?: Yes

---

## 8. Acceptance Criteria

- [ ] `MSTeamsAgentConfig` has `allowed_conversation_ids` and `allowed_user_ids` fields (default `None`)
- [ ] `MSTeamsWrapper._is_authorized()` checks both conversation and user whitelists
- [ ] Authorization check applied at `on_message_activity()` and `_handle_card_submission()`
- [ ] `SlackAgentConfig` has `allowed_user_ids` field (default `None`)
- [ ] `SlackWrapper._is_authorized()` checks both channel and user whitelists
- [ ] All `from_dict()` methods updated to parse new fields
- [ ] Existing configs without whitelist fields continue to work unchanged
- [ ] All unit tests pass
- [ ] All integration tests pass
