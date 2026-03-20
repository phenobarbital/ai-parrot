# TASK-253: Unit Tests — Whitelist Config & Authorization

**Feature**: Integration User/Channel Whitelisting (FEAT-037)
**Spec**: `sdd/specs/integration-user-limit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-249, TASK-250, TASK-251, TASK-252
**Assigned-to**: claude-session

---

## Context

> Comprehensive unit tests for whitelist config fields, env var resolution, and authorization logic for both MS Teams and Slack.
> Implements spec Section 4 — Unit Tests.

---

## Scope

### Test Files

**`tests/integrations/msteams/test_msteams_config_whitelist.py`** (CREATE):
- `test_config_allowed_conversation_ids_default_none`
- `test_config_allowed_user_ids_default_none`
- `test_config_from_dict_with_whitelist`
- `test_config_from_dict_without_whitelist`
- `test_config_env_var_resolution_conversation_ids`
- `test_config_env_var_resolution_user_ids`

**`tests/integrations/msteams/test_msteams_authorization.py`** (CREATE):
- `test_authorized_when_no_whitelist`
- `test_authorized_conversation_in_list`
- `test_unauthorized_conversation_not_in_list`
- `test_authorized_user_in_list`
- `test_unauthorized_user_not_in_list`
- `test_both_filters_must_pass`
- `test_on_message_unauthorized_sends_denial`

**`tests/integrations/slack/test_slack_user_whitelist.py`** (CREATE):
- `test_config_allowed_user_ids_default_none`
- `test_config_from_dict_with_user_whitelist`
- `test_config_env_var_resolution_user_ids`
- `test_authorized_channel_and_user`
- `test_unauthorized_user`
- `test_channel_authorized_user_not`

**NOT in scope**: Integration tests (TASK-254).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/integrations/msteams/test_msteams_config_whitelist.py` | CREATE | Config model tests |
| `tests/integrations/msteams/test_msteams_authorization.py` | CREATE | Authorization logic tests |
| `tests/integrations/slack/test_slack_user_whitelist.py` | CREATE | Slack user whitelist tests |

---

## Implementation Notes

- Use `unittest.mock.patch` to mock env vars in config tests
- Mock `TurnContext` and `Activity` for MS Teams authorization tests
- Mock `aiohttp.web.Request` for Slack handler tests
- Ensure tests don't require network access

---

## Acceptance Criteria

- [ ] All 19 unit tests defined in spec Section 4 implemented
- [ ] All tests pass
- [ ] No network calls in tests
- [ ] Backward compatibility verified (None = allow all)

---

## Agent Instructions

When you pick up this task:

1. **Verify** TASK-249, TASK-250, TASK-251, TASK-252 are complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** all test files
4. **Run** `pytest tests/integrations/msteams/ tests/integrations/slack/ -v`
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

All 36 unit tests implemented and passing across 4 test files:

- `tests/integrations/msteams/test_msteams_config_whitelist.py` — 12 tests (field defaults, env var resolution, from_dict, backward compat)
- `tests/integrations/msteams/test_msteams_authorization.py` — 7 tests (_is_authorized AND logic, on_message denial)
- `tests/integrations/slack/test_slack_config_whitelist.py` — 11 tests (completed by user in parallel session / TASK-251)
- `tests/integrations/slack/test_slack_user_whitelist.py` — 6 tests (_is_authorized with user_id, backward compat with None user_id)

TASK-252 (Slack Wrapper Authorization) was also completed as a prerequisite during this session.
No network calls in any tests. Backward compatibility verified (None = allow all).
