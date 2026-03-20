# TASK-241: Config Model — Add OAuth2 Fields to TelegramAgentConfig

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Extend `TelegramAgentConfig` with new OAuth2 fields so bots can be configured for either Basic Auth or OAuth2 authentication. Must be fully backward compatible — existing YAML configs without `auth_method` must continue working.
> Implements spec Section 2 (Data Models) and Module 4.

---

## Scope

- Add the following fields to `TelegramAgentConfig` in `parrot/integrations/telegram/models.py`:
  - `auth_method: str = "basic"` — `"basic"` | `"oauth2"`
  - `oauth2_provider: str = "google"` — `"google"` | `"github"` | `"microsoft"` (future)
  - `oauth2_client_id: Optional[str] = None`
  - `oauth2_client_secret: Optional[str] = None`
  - `oauth2_scopes: Optional[list[str]] = None`
  - `oauth2_redirect_uri: Optional[str] = None`
- Update `__post_init__` to resolve `oauth2_client_id` and `oauth2_client_secret` from env vars (`{NAME}_OAUTH2_CLIENT_ID`, `{NAME}_OAUTH2_CLIENT_SECRET`) when `auth_method == "oauth2"`
- Update `from_dict()` to parse the new fields from YAML
- Update `validate()` to check OAuth2 credentials when `auth_method == "oauth2"`

**NOT in scope**: Auth strategy classes (TASK-242), wrapper changes (TASK-245).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/models.py` | MODIFY | Add OAuth2 fields, update `__post_init__`, `from_dict`, `validate` |

---

## Implementation Notes

- Default `auth_method` to `"basic"` so existing configs without this field work unchanged
- `from_dict()` must handle missing OAuth2 keys gracefully (they're all Optional)
- Use `navconfig.config.get()` for env var resolution (existing pattern in `__post_init__`)
- Never log `oauth2_client_secret` values

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig` has all 6 new fields with correct defaults
- [ ] `auth_method` defaults to `"basic"` when not specified
- [ ] `__post_init__` resolves OAuth2 client_id/secret from env vars
- [ ] `from_dict()` parses all new fields from YAML dict
- [ ] `validate()` reports errors when `auth_method="oauth2"` but `oauth2_client_id` is missing
- [ ] Existing configs without `auth_method` produce identical behavior
- [ ] Unit tests: `test_config_auth_method_default`, `test_config_oauth2_env_fallback`

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/integrations/telegram/models.py` fully
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** changes to `TelegramAgentConfig`
4. **Run** `pytest tests/integrations/telegram/ -v` (create tests if needed)
5. **Move this file** to `sdd/tasks/completed/TASK-241-config-model-oauth2-fields.md`
6. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Added 6 new fields to `TelegramAgentConfig` in `parrot/integrations/telegram/models.py`:
- `auth_method: str = "basic"` — selects `"basic"` or `"oauth2"`
- `oauth2_provider: str = "google"` — provider selection
- `oauth2_client_id: Optional[str] = None` — resolved from `{NAME}_OAUTH2_CLIENT_ID` env var
- `oauth2_client_secret: Optional[str] = None` — resolved from `{NAME}_OAUTH2_CLIENT_SECRET` env var
- `oauth2_scopes: Optional[List[str]] = None`
- `oauth2_redirect_uri: Optional[str] = None`

Updated `__post_init__()` for env var resolution, `from_dict()` for YAML parsing,
and `validate()` for OAuth2 credential checking.

Fully backward compatible — existing configs without `auth_method` default to `"basic"`.

16 tests pass in `tests/integrations/telegram/test_config_oauth2.py`. No lint errors.
