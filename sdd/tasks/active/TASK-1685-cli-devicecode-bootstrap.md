# TASK-1685: CLI device-code bootstrap + identity wiring + end-to-end integration test

**Feature**: FEAT-266 — O365 Auth Homologation
**Spec**: `sdd/specs/o365-auth-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1683, TASK-1684
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. Closes the loop so a CLI-run agent with an o365-credentialed tool
actually triggers the device-code flow. The broker is built in `AbstractBot.configure()` from
`self._credentials`; `ToolManager` injects `_broker` + `_cred_channel`/`_cred_user_id` (read
from `permission_context.channel`/`.user_id`). The CLI must supply a permission context with
`channel="cli"` and `user_id=<canonical principal>` (from env `O365_PRINCIPAL`, normalized by
`CanonicalIdentityMapper`) and declare the o365 `device_code` provider in the agent's credentials.

> **First sub-step (verify before building):** confirm the exact CLI agent-run entry where the
> `permission_context` is constructed (spec §8 open question — seam verified at
> `manager.py:1305-1316`). If no CLI entry threads a permission context today, add the minimal
> bootstrap that does.

---

## Scope

- Add a CLI bootstrap that:
  - reads `O365_PRINCIPAL` from env, normalizes via `CanonicalIdentityMapper.to_canonical(...)`,
    fails closed (clear error) if absent/unmappable;
  - supplies a permission context carrying `channel="cli"` + `user_id=<canonical>` into the
    agent run so `ToolManager` propagates it to the tool seam;
  - ensures the agent's `_credentials` includes a `ProviderCredentialConfig(provider="o365",
    auth="device_code", options={...scopes...})` so `configure()` builds the broker with the
    device-code deps (`o365_client`/`o365_interface`, `o365_oauth_manager`, `vault`).
- Add the end-to-end integration test(s) from spec §4.

**NOT in scope**: chat surfaces, new `parrot ... login` command (entry point is the existing
agent/tool run path — spec §1/§8), Gen 1 deletion (TASK-1686).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| CLI agent-run entry (confirm exact path) | MODIFY | thread `permission_context(channel="cli", user_id=<canonical>)` + env principal |
| agent credentials config (manifest or AgentDefinition) | MODIFY/CREATE | declare o365 `device_code` provider + broker deps |
| `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` | CREATE | end-to-end + WorkIQ-OBO interop test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.identity import CanonicalIdentityMapper             # identity.py:57 (__all__:14)
from parrot.auth.credentials import ProviderCredentialConfig         # credentials.py:46
from parrot.auth.broker import CredentialBroker                      # broker.py:42
```

### Existing Signatures to Use
```python
# parrot/auth/identity.py:57
class CanonicalIdentityMapper:
    @staticmethod
    def to_canonical(raw_identity: Dict[str, Any]) -> Optional[str]: ...   # line 75 (OID → email → None)

# parrot/tools/manager.py  (credential-context propagation — DO NOT re-implement, just feed it)
#   self._broker set via ToolManager.set_broker(broker)                    # line 320
#   exec_kwargs['_broker'] = self._broker                                  # line 1306
#   exec_kwargs.setdefault('_cred_channel', getattr(permission_context, 'channel', 'unknown'))   # line 1308-1312
#   exec_kwargs.setdefault('_cred_user_id', getattr(permission_context, 'user_id', None))        # line 1313-1316

# parrot/bots/abstract.py  (broker build in configure)
#   broker = CredentialBroker.from_config(self._credentials, **_broker_deps)   # line 1401
#   self.tool_manager.set_broker(broker)                                       # line 1402
```

### Does NOT Exist
- ~~A dedicated `parrot o365 login` CLI command~~ — not the chosen entry point (resolver fires inline).
- ~~A pre-existing `channel="cli"` permission context~~ — confirm/create the minimal one.
- Do NOT modify the `ToolManager` propagation logic — it already exists; only FEED it `channel`/`user_id`.

### Integration Point to PROVE (interop)
- `WorkIQOBOCredentialResolver.resolve` reads `o365:access_token` via `VaultTokenSync`
  (`workiq_provider.py:140`) — the e2e test asserts a device-code-written token is consumed by it.

---

## Implementation Notes

### Key Constraints
- Fail closed: no `O365_PRINCIPAL` (or unmappable) → clear error, no anonymous vault key.
- Use the EXISTING propagation seam; the bootstrap's only job is to construct + pass a
  permission context and the credentials config.
- The integration test may mock the Entra device + token endpoints and the SessionVault backend.

### References in Codebase
- `parrot/tools/manager.py:1305-1316` — propagation seam.
- `parrot/bots/abstract.py:1389-1402` — broker build from `_credentials`.
- `env/integrations_bots.yaml` — example manifest form for per-agent provider config (if used).

---

## Acceptance Criteria

- [ ] A CLI run of an agent with a `credential_provider="o365"` tool, with `O365_PRINCIPAL` set,
      triggers the device-code flow inline and resolves a token without raising `CredentialRequired`.
- [ ] The token is persisted to `VaultTokenSync` `o365:*` and a second resolve is a cache hit.
- [ ] Missing `O365_PRINCIPAL` fails closed with a clear message.
- [ ] Interop test: a device-code-obtained `o365:access_token` is consumable by `WorkIQOBOCredentialResolver` (mocked OBO).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py -v`.
- [ ] No secret in logs/audit; audit entry appended on success.

---

## Test Specification

```python
import pytest

async def test_cli_device_code_end_to_end(monkeypatch, fake_entra, fake_vault):
    monkeypatch.setenv("O365_PRINCIPAL", "user@corp.com")
    # build agent with o365 device_code config + permission_context(channel="cli", user_id="user@corp.com")
    # run a tool with credential_provider="o365"; assert token resolved + persisted; 2nd call cache-hits
    ...

async def test_devicecode_token_consumable_by_workiq_obo(fake_vault, fake_o365):
    # after device-code persists o365:access_token, WorkIQOBOCredentialResolver.resolve performs OBO
    ...

async def test_missing_principal_fails_closed(monkeypatch):
    monkeypatch.delenv("O365_PRINCIPAL", raising=False)
    with pytest.raises((ValueError, RuntimeError)):
        ...
```

---

## Agent Instructions
Standard SDD flow. Verify TASK-1683 + TASK-1684 are in `completed/` first. Start by confirming
the CLI entry/permission-context seam (spec §8) before writing the bootstrap.

## Completion Note
*(Agent fills this in when done)*
