# TASK-249: MS Teams Config — Whitelist Fields

**Feature**: Integration User/Channel Whitelisting (FEAT-037)
**Spec**: `sdd/specs/integration-user-limit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Add `allowed_conversation_ids` and `allowed_user_ids` fields to `MSTeamsAgentConfig`, with env var fallback support.
> Implements spec Module 1.

---

## Scope

### Config Model Updates (`MSTeamsAgentConfig`)
- Add `allowed_conversation_ids: Optional[List[str]] = None`
- Add `allowed_user_ids: Optional[List[str]] = None`
- Update `__post_init__()` to resolve from env vars:
  - `{NAME}_ALLOWED_CONVERSATION_IDS` — comma-separated string
  - `{NAME}_ALLOWED_USER_IDS` — comma-separated string
- Update `from_dict()` to parse both fields from YAML config

**NOT in scope**: Wrapper authorization logic (TASK-250).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/msteams/models.py` | MODIFY | Add whitelist fields, env var resolution, from_dict parsing |

---

## Implementation Notes

- Follow the same pattern as `TelegramAgentConfig.allowed_chat_ids`
- Env var resolution: split comma-separated string into list, strip whitespace
- If env var is empty or not set, leave as `None` (allow all)
- Import `List` from typing (already imported in file)

---

## Acceptance Criteria

- [ ] `allowed_conversation_ids` field exists, defaults to `None`
- [ ] `allowed_user_ids` field exists, defaults to `None`
- [ ] `__post_init__()` resolves both fields from env vars when not provided
- [ ] `from_dict()` parses both fields from YAML dict
- [ ] Existing configs without these fields still work (backward compat)

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/msteams/models.py`
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** config model changes
4. **Run** `pytest tests/integrations/msteams/ -v` (if tests exist)
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Modified `parrot/integrations/msteams/models.py`:
- Added `allowed_conversation_ids: Optional[List[str]] = None` and `allowed_user_ids: Optional[List[str]] = None` fields
- Added env var resolution in `__post_init__()`: `{NAME}_ALLOWED_CONVERSATION_IDS` and `{NAME}_ALLOWED_USER_IDS` (comma-separated)
- Updated `from_dict()` to parse both fields from YAML config
- All 10 existing MS Teams model tests still pass. Backward compatible — None defaults allow all.
