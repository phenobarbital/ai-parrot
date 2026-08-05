# TASK-2136: Environment selector on WorkdayConfig + `WORKDAY_*` conf settings

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the first half of **Module 1** of the spec. ai-parrot's
`WorkdayConfig` has no notion of a target environment: it always resolves
the production `WORKDAY_*` credentials. flowtask added a `WORKDAY_ENV`
selector plus a parallel `WORKDAY_*_IMPL` credential set for the
implementation/sandbox tenant.

This task ports that selector **without** porting flowtask's hardcoded
tenant values. flowtask pins `tenant="troc"`,
`report_owner="jtorres@trocglobal.com"` and a `_PROD_WORKDAY_URL` constant;
ai-parrot deliberately replaced all three with `None` + conf-resolved
computed fields. That vendor-neutrality must survive.

Per the spec's resolved open question, selecting sandbox **without** the
`_IMPL` credentials must **raise**, never fall back to production
credentials — a silent fallback would send sandbox-intended writes to the
live tenant.

---

## Scope

- Add five settings to `packages/ai-parrot/src/parrot/conf.py`, appended
  after the existing `WORKDAY_*` block: `WORKDAY_ENV`,
  `WORKDAY_CLIENT_ID_IMPL`, `WORKDAY_CLIENT_SECRET_IMPL`,
  `WORKDAY_REFRESH_TOKEN_IMPL`, `WORKDAY_TOKEN_URL_IMPL`.
- Add an `env: str | None = None` field to `WorkdayConfig`.
- Add `resolved_env` (plain `@property`) returning the effective environment
  (`self.env` → `WORKDAY_ENV` → `"prod"`, stripped and lowercased).
- Add `resolved_is_sandbox` (plain `@property`) — `True` when
  `resolved_env` is in `{"sandbox", "impl", "implementation"}`.
- Make the four credential `@computed_field` properties environment-aware:
  `resolved_client_id`, `resolved_client_secret`, `resolved_token_url`,
  `resolved_refresh_token` select the `_IMPL` variant when sandbox is active.
- **Fail loudly**: when `resolved_is_sandbox` is `True` and the
  corresponding `_IMPL` setting is unset/empty, raise with a message naming
  the missing setting. Never fall back to the production value.
- Add the `_align_workday_url_to_env` model validator (`mode="after"`) that
  points `workday_url` at the sandbox host when sandbox is selected.
- Extend `_WSDL_ROUTING` only if new operation keys are required — otherwise
  leave it untouched.
- Write unit tests for all of the above.

**NOT in scope**:
- The `bind_service()` SOAP endpoint rewrite — that is TASK-2137.
- `WorkdayRestClient` — TASK-2138.
- Any handler, parser or model change.
- Touching `parrot_tools/workday/tool.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Append 5 settings after the existing `WORKDAY_*` block (ends ~line 698) |
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py` | MODIFY | `env` field, `resolved_env`, `resolved_is_sandbox`, env-aware credential resolution, URL alignment validator |
| `packages/ai-parrot-tools/tests/workday/test_env_selector.py` | CREATE | Unit tests for env resolution and fail-loud behaviour |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# verified: packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
from pydantic import BaseModel, computed_field   # model_validator MUST BE ADDED to this import
from parrot.conf import (
    WORKDAY_CLIENT_ID,        # verified: packages/ai-parrot/src/parrot/conf.py:638
    WORKDAY_CLIENT_SECRET,    # verified: conf.py:639
    WORKDAY_TOKEN_URL,        # verified: conf.py:640
    WORKDAY_REFRESH_TOKEN,    # verified: conf.py:681
    WORKDAY_DEFAULT_TENANT,   # verified: conf.py:637
    WORKDAY_REPORT_OWNER,     # verified: conf.py:687
    WORKDAY_URL,              # verified: conf.py:688
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
_WSDL_ROUTING: dict[str, Any] = { ... }        # line 58 — EXTEND ONLY, do not restructure

class WorkdayConfig(BaseModel):                # line 112
    client_id: str | None = None               # line 129
    client_secret: str | None = None           # line 130
    token_url: str | None = None               # line 131
    refresh_token: str | None = None           # line 132
    report_username: str | None = None         # line 133
    report_password: str | None = None         # line 134
    tenant: str | None = None                  # line 135  <-- KEEP None (vendor-neutral)
    report_owner: str | None = None            # line 136  <-- KEEP None (vendor-neutral)
    workday_url: str | None = None             # line 137  <-- KEEP None (vendor-neutral)
    timeout: int = 300                         # line 138

    # @computed_field @property — MAKE THESE FOUR ENVIRONMENT-AWARE:
    def resolved_client_id(self) -> str | None:       # line 146
    def resolved_client_secret(self) -> str | None:   # line 152
    def resolved_token_url(self) -> str | None:       # line 158
    def resolved_refresh_token(self) -> str | None:   # line 164
    # LEAVE THESE FIVE UNCHANGED:
    def resolved_report_username(self) -> str | None: # line 170
    def resolved_report_password(self) -> str | None: # line 176
    def resolved_tenant(self) -> str | None:          # line 182
    def resolved_report_owner(self) -> str | None:    # line 188
    def resolved_workday_url(self) -> str | None:     # line 194
```

```python
# packages/ai-parrot/src/parrot/conf.py — existing WORKDAY_* block spans 637-698
WORKDAY_DEFAULT_TENANT = config.get('WORKDAY_DEFAULT_TENANT', fallback='nav')   # line 637
WORKDAY_REPORT_OWNER = config.get("WORKDAY_REPORT_OWNER", fallback=None)        # line 687
WORKDAY_URL = config.get("WORKDAY_URL", fallback="https://services1.wd501.myworkday.com")  # line 688
WORKDAY_WSDL_PATHS = { ... }                                                     # line 690
```

### Reference Source (flowtask — READ ONLY, do not copy verbatim)

`../flowtask/flowtask/interfaces/workday/config.py` holds the original
implementation. Port the **logic**, not the constants. Specifically DO NOT
port: `_PROD_WORKDAY_URL`, `tenant: str = "troc"`,
`report_owner: str = "jtorres@trocglobal.com"`.
The sandbox-env set in flowtask is `_SANDBOX_ENVS = {"sandbox", "impl", "implementation"}`.

### Does NOT Exist

- ~~`parrot.conf.WORKDAY_ENV`~~ — must be added by this task
- ~~`parrot.conf.WORKDAY_CLIENT_ID_IMPL`~~ — must be added by this task
- ~~`parrot.conf.WORKDAY_CLIENT_SECRET_IMPL`~~ — must be added by this task
- ~~`parrot.conf.WORKDAY_REFRESH_TOKEN_IMPL`~~ — must be added by this task
- ~~`parrot.conf.WORKDAY_TOKEN_URL_IMPL`~~ — must be added by this task
- ~~`WorkdayConfig.env`~~ / ~~`.resolved_env`~~ / ~~`.resolved_is_sandbox`~~ — do not exist yet
- ~~`_PROD_WORKDAY_URL` in ai-parrot's config.py~~ — flowtask-only constant, **do NOT port it**
- ~~`model_validator` in config.py's current pydantic import~~ — only `BaseModel, computed_field` are imported today; add it

---

## Implementation Notes

### Key Constraints
- `tenant`, `report_owner` and `workday_url` MUST stay `None`-defaulted and conf-resolved. Never hardcode a customer value.
- The fail-loud check belongs in credential resolution, and its message must name the missing setting (e.g. `WORKDAY_CLIENT_SECRET_IMPL`).
- `resolved_env` / `resolved_is_sandbox` are plain `@property` (NOT `@computed_field`) — they are helpers, not serialized fields, matching flowtask.
- Google-style docstrings and strict type hints on everything new.
- Do not restructure `_WSDL_ROUTING`; existing routing keys keep their targets.

### References in Codebase
- `packages/ai-parrot/src/parrot/conf.py:637-698` — the block to append to; note `WORKDAY_REPORT_PASSWORD_BASE64` at 684-686 as the pattern for derived settings.
- `packages/ai-parrot-tools/tests/workday/test_homologation_read.py` — established mocking/fixture pattern.

---

## Acceptance Criteria

- [ ] Five new settings exist in `parrot/conf.py`, appended (not restructured)
- [ ] `WorkdayConfig(env="sandbox").resolved_is_sandbox is True`; `WorkdayConfig().resolved_env == "prod"`
- [ ] Sandbox resolves `WORKDAY_*_IMPL` credentials; production resolves `WORKDAY_*`
- [ ] Sandbox with an unset `_IMPL` credential **raises**, naming the missing setting — never falls back to production
- [ ] `_align_workday_url_to_env` points `workday_url` at the sandbox host when sandbox is selected
- [ ] `grep -rn "troc\|jtorres@trocglobal.com" packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/` returns nothing
- [ ] No hardcoded production-URL default added to `WorkdayConfig`
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py packages/ai-parrot/src/parrot/conf.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_env_selector.py
import pytest
from parrot_tools.interfaces.workday.config import WorkdayConfig


class TestEnvResolution:
    def test_defaults_to_prod(self):
        assert WorkdayConfig().resolved_env == "prod"
        assert WorkdayConfig().resolved_is_sandbox is False

    @pytest.mark.parametrize("value", ["sandbox", "impl", "implementation", "SANDBOX", " sandbox "])
    def test_sandbox_aliases(self, value):
        assert WorkdayConfig(env=value).resolved_is_sandbox is True

    def test_sandbox_selects_impl_credentials(self, monkeypatch):
        """env=sandbox resolves WORKDAY_*_IMPL, not the production values."""

    def test_sandbox_missing_impl_raises(self, monkeypatch):
        """Unset _IMPL credential must raise, naming the setting — NEVER fall back to prod."""
        with pytest.raises(ValueError, match="WORKDAY_CLIENT_SECRET_IMPL"):
            ...

    def test_explicit_value_wins_over_conf(self):
        assert WorkdayConfig(client_id="explicit").resolved_client_id == "explicit"


class TestVendorNeutrality:
    def test_no_hardcoded_tenant_defaults(self):
        cfg = WorkdayConfig()
        assert cfg.tenant is None
        assert cfg.report_owner is None
        assert cfg.workday_url is None
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2136-workday-env-selector-conf.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**: Added `env`/`resolved_env`/`resolved_is_sandbox` to `WorkdayConfig`,
made the four credential `@computed_field` properties (`resolved_client_id`,
`resolved_client_secret`, `resolved_token_url`, `resolved_refresh_token`)
environment-aware with fail-loud raises naming the missing `WORKDAY_*_IMPL`
setting, and added `_align_workday_url_to_env` (`model_validator(mode="after")`)
to point `workday_url` at the sandbox host (derived from `resolved_token_url`)
when `workday_url` is left `None` in sandbox. Five settings appended to
`parrot/conf.py` after the existing `WORKDAY_*` block (not restructured).
`tenant`, `report_owner`, `workday_url` remain `None`-defaulted;
`resolved_workday_url` unchanged. 22 new tests in
`test_env_selector.py`; full `tests/workday/` suite (77 tests) passes;
`ruff check` clean on all changed files; grep for `troc`/
`jtorres@trocglobal.com` returns nothing.

**Deviations from spec**: none. Note: the URL-alignment validator eagerly
resolves `resolved_token_url` during construction when sandbox + no explicit
`workday_url`, so a missing `WORKDAY_TOKEN_URL_IMPL` raises at construction
time (via Pydantic's `ValidationError` wrapping the `ValueError`) rather than
only on later property access — this is stricter than, but consistent with,
the "fail loudly ... never fall back to production" requirement.
