# TASK-243: OAuth2 Provider Registry

**Feature**: Telegram Integration OAuth2 Auth (FEAT-036)
**Spec**: `sdd/specs/telegram-integrations-auth.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Create the OAuth2 provider registry with pluggable provider configs. Google is the first provider. Adding future providers (GitHub, Microsoft) should require only a new dict entry.
> Implements spec Module 2.

---

## Scope

- Create new file `parrot/integrations/telegram/oauth2_providers.py`
- Define `OAuth2ProviderConfig` dataclass:
  ```python
  @dataclass
  class OAuth2ProviderConfig:
      name: str
      authorization_url: str
      token_url: str
      userinfo_url: str
      default_scopes: list[str]
  ```
- Define `OAUTH2_PROVIDERS` dict with Google config:
  - `authorization_url`: `https://accounts.google.com/o/oauth2/v2/auth`
  - `token_url`: `https://oauth2.googleapis.com/token`
  - `userinfo_url`: `https://www.googleapis.com/oauth2/v3/userinfo`
  - `default_scopes`: `["openid", "email", "profile"]`
- Define `get_provider(name: str) -> OAuth2ProviderConfig` — raises `ValueError` for unknown providers

**NOT in scope**: OAuth2 strategy implementation (TASK-244).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/oauth2_providers.py` | CREATE | Provider registry with Google config |

---

## Implementation Notes

- Keep it simple — just a dataclass and a dict lookup
- No external dependencies needed
- Provider URLs must be exact (verify against Google's OAuth2 docs)

---

## Acceptance Criteria

- [x] `OAuth2ProviderConfig` dataclass is defined with all 5 fields
- [x] `OAUTH2_PROVIDERS` dict contains Google with correct endpoints
- [x] `get_provider("google")` returns correct config
- [x] `get_provider("unknown")` raises `ValueError`
- [x] Unit tests: `test_oauth2_provider_google_config`, `test_oauth2_provider_unknown_raises`

---

## Agent Instructions

When you pick up this task:

1. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
2. **Create** `parrot/integrations/telegram/oauth2_providers.py`
3. **Write tests** in `tests/integrations/telegram/test_oauth2_providers.py`
4. **Run** `pytest tests/integrations/telegram/test_oauth2_providers.py -v`
5. **Move this file** to `sdd/tasks/completed/`
6. **Update index** → `"done"`

---

## Completion Note

Completed 2026-03-09. Created `parrot/integrations/telegram/oauth2_providers.py` with frozen
`OAuth2ProviderConfig` dataclass, `OAUTH2_PROVIDERS` registry (Google), and case-insensitive
`get_provider()` lookup. 8 unit tests pass in `tests/integrations/telegram/test_oauth2_providers.py`.
