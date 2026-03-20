# TASK-251: Slack Config — User Whitelist Field

**Feature**: Integration User/Channel Whitelisting (FEAT-037)
**Spec**: `sdd/specs/integration-user-limit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Add `allowed_user_ids` field to `SlackAgentConfig` to complement the existing `allowed_channel_ids`, with env var fallback support.
> Implements spec Module 3.

---

## Scope

### Config Model Updates (`SlackAgentConfig`)
- Add `allowed_user_ids: Optional[List[str]] = None`
- Update `__post_init__()` to resolve from env var:
  - `{NAME}_SLACK_ALLOWED_USER_IDS` — comma-separated string
- Update `from_dict()` to parse the new field from YAML config

**NOT in scope**: Wrapper authorization changes (TASK-252).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/models.py` | MODIFY | Add `allowed_user_ids` field, env var resolution, from_dict parsing |

---

## Implementation Notes

- Follow the same env var resolution pattern as the existing `bot_token` and `signing_secret` fields
- Env var: split comma-separated string, strip whitespace per item
- If env var is empty or not set, leave as `None` (allow all)
- The existing `allowed_channel_ids` field does NOT have env var resolution — keep it as-is for backward compat

---

## Acceptance Criteria

- [ ] `allowed_user_ids` field exists, defaults to `None`
- [ ] `__post_init__()` resolves from `{NAME}_SLACK_ALLOWED_USER_IDS` env var
- [ ] `from_dict()` parses the field from YAML dict
- [ ] Existing configs without `allowed_user_ids` still work unchanged

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/slack/models.py`
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** config model changes
4. **Run** `pytest tests/integrations/slack/ -v` (if tests exist)
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Added `allowed_user_ids: Optional[List[str]] = None` to `SlackAgentConfig`:
- Field defaults to `None` (allow all users)
- `__post_init__()` resolves from `{NAME}_SLACK_ALLOWED_USER_IDS` env var (comma-separated, whitespace-stripped)
- `from_dict()` parses the field from YAML config dicts
- Explicit values take precedence over env var; empty env var stays `None`
- Full backward compatibility — existing configs without the field work unchanged
- 11 unit tests pass in `tests/integrations/slack/test_slack_config_whitelist.py`
