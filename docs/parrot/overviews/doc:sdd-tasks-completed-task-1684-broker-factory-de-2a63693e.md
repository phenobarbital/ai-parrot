---
type: Wiki Overview
title: 'TASK-1684: Wire `device_code` into `CredentialResolverFactory`'
id: doc:sdd-tasks-completed-task-1684-broker-factory-device-code-branch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 4. The broker builds resolvers declaratively from
relates_to:
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.oauth2.o365_devicecode_provider
  rel: mentions
---

# TASK-1684: Wire `device_code` into `CredentialResolverFactory`

**Feature**: FEAT-266 — O365 Auth Homologation
**Spec**: `sdd/specs/o365-auth-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1683
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4. The broker builds resolvers declaratively from
`ProviderCredentialConfig` via `CredentialResolverFactory.build()`. This task adds the
`device_code` dispatch branch + a `_build_device_code()` builder that constructs the resolver
from TASK-1683 using injected deps.

---

## Scope

- Add a `_build_device_code(self, cfg, opts)` method to `CredentialResolverFactory` that builds
  `O365DeviceCodeCredentialResolver` from deps: `o365_interface`/`o365_client`,
  `o365_oauth_manager`, `vault`, and opts: `scopes` (default to `DEFAULT_O365_SCOPES`).
- Add the `if kind == "device_code": return self._build_device_code(cfg, opts)` branch in
  `build()`, and include `device_code` in the "unknown kind" error message's supported list.
- Follow the exact pattern of `_build_obo` (deps lookup + `ImportError`/`KeyError` on missing).
- Write unit tests.

**NOT in scope**: the resolver itself (TASK-1683), CLI bootstrap (TASK-1685).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/broker.py` | MODIFY | `_build_device_code` + dispatch branch |
| `packages/ai-parrot/tests/auth/test_broker_devicecode.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.broker import CredentialResolverFactory, CredentialBroker  # broker.py:42 __all__
from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver  # CREATED by TASK-1683
```

### Existing Signatures to Use
```python
# parrot/auth/broker.py
class CredentialResolverFactory:                                   # line 66
    def __init__(self, deps: Optional[Dict[str, Any]] = None) -> None: ...   # line 98 (self._deps)
    def build(self, cfg: ProviderCredentialConfig) -> CredentialResolver:    # line 101
        # dispatch at 114-129: obo/oauth2/static_key/mcp -> ValueError on unknown
    def _build_obo(self, cfg, opts) -> CredentialResolver: ...      # line 135 (pattern to mirror)
        # reads self._deps.get("o365_interface"/"o365_oauth_manager"/"vault")
class CredentialBroker:                                            # line 280
    def register(self, provider, resolver, auth_kind="oauth2") -> None: ...   # line 329
    @classmethod def from_config(cls, configs, strict=True, **deps): ...      # line 355 (registers with auth_kind=str(cfg.auth))
```

### Does NOT Exist
- ~~`_build_device_code`~~ — added by THIS task.
- ~~`device_code` in the `build()` dispatch~~ — added by THIS task.
- `from_config` already passes `auth_kind=str(cfg.auth)` to `register` (broker.py:~398) — so
  `NeedsAuth.auth_kind` will be `"device_code"` automatically; no extra wiring needed there.

---

## Implementation Notes

### Pattern to Follow
```python
def _build_device_code(self, cfg, opts):
    """Build an O365DeviceCodeCredentialResolver. Expected deps: o365_interface/o365_client,
    o365_oauth_manager, vault. Expected opts: scopes."""
    from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver
    o365 = self._deps.get("o365_client") or self._deps.get("o365_interface")
    manager = self._deps.get("o365_oauth_manager")
    vault = self._deps.get("vault")
    scopes = opts.get("scopes")  # resolver defaults to DEFAULT_O365_SCOPES if None
    return O365DeviceCodeCredentialResolver(o365_client=o365, o365_oauth_manager=manager,
                                            vault_token_sync=vault, scopes=scopes)
```

### Key Constraints
- Match the deps-lookup + error style of `_build_obo` (raise `KeyError`/`ImportError` on missing dep/class).
- Update the unknown-kind `ValueError` message at broker.py:126-129 to list `device_code`.

---

## Acceptance Criteria

- [ ] `CredentialResolverFactory(deps={...}).build(ProviderCredentialConfig(provider="o365", auth="device_code"))` returns an `O365DeviceCodeCredentialResolver`.
- [ ] Missing required dep raises `KeyError` (consistent with `_build_obo`).
- [ ] `CredentialBroker.from_config([...device_code cfg...], **deps)` registers the provider with `auth_kind="device_code"`.
- [ ] Existing `obo|oauth2|static_key|mcp` dispatch unaffected.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/auth/test_broker_devicecode.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/broker.py` clean.

---

## Test Specification

```python
import pytest
from parrot.auth.broker import CredentialResolverFactory, CredentialBroker
from parrot.auth.credentials import ProviderCredentialConfig
from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver

def test_factory_builds_device_code(fake_o365, fake_manager, fake_vault):
    f = CredentialResolverFactory(deps={"o365_client": fake_o365,
        "o365_oauth_manager": fake_manager, "vault": fake_vault})
    r = f.build(ProviderCredentialConfig(provider="o365", auth="device_code"))
    assert isinstance(r, O365DeviceCodeCredentialResolver)

def test_factory_device_code_missing_dep_raises():
    f = CredentialResolverFactory(deps={})
    with pytest.raises((KeyError, Exception)):
        f.build(ProviderCredentialConfig(provider="o365", auth="device_code"))
```

---

## Agent Instructions
Standard SDD flow. Verify TASK-1683 is in `completed/` first.

## Completion Note
Added `_build_device_code(cfg, opts)` to `CredentialResolverFactory` mirroring
`_build_obo`'s deps-lookup/error style (`o365_client` dep with
`o365_interface` fallback, `o365_oauth_manager`, `vault`; raises `KeyError`
on any missing required dep). Added the `device_code` dispatch branch in
`build()` and updated the unknown-kind `ValueError` message to list
`device_code`. 7 new tests in `test_broker_devicecode.py` cover the happy
path, the `o365_interface` alias fallback, missing/partial deps,
`CredentialBroker.from_config` registering `auth_kind="device_code"`, and
that the existing `obo|oauth2|static_key|mcp` dispatch is unaffected. All
pass; existing `test_credential_broker.py` (14 tests) unaffected; `ruff
check` clean. No deviations from spec.
