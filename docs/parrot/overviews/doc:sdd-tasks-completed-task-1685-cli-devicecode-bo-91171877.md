---
type: Wiki Overview
title: 'TASK-1685: CLI device-code bootstrap + identity wiring + end-to-end integration
  test'
id: doc:sdd-tasks-completed-task-1685-cli-devicecode-bootstrap-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 5. Closes the loop so a CLI-run agent with an o365-credentialed
  tool
relates_to:
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.identity
  rel: mentions
---

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
**CLI entry confirmed (spec §8 open question resolved):** `parrot/cli/agent_repl.py`
`_run()` (the `parrot agent` Click command) → `AgentREPL` (`parrot/cli/repl.py`)
is the sole interactive CLI agent-run path. It calls `bot.ask()`/`bot.ask_stream()`
which already accept `permission_context` (verified: `bots/base.py:858` on `ask()`)
and forward it to `client._permission_context`, consumed by
`clients/base.py:1370-1372` → `tool_manager.execute_tool(..., permission_context=...)`
→ the existing `_cred_channel`/`_cred_user_id` injection in `tools/manager.py`.
**Gap found and fixed:** `ask_stream()` (the REPL's default path, `streaming=True`)
was missing the `client._permission_context = permission_context` propagation
that `ask()` already had — added the matching 2-line block plus the
`permission_context` parameter to `BaseBot.ask_stream()` (`bots/base.py`),
mirroring the existing pattern exactly; no other `ask_stream` behavior changed.

**Implementation:**
- `parrot/cli/identity.py` (NEW): `resolve_cli_o365_principal()` reads
  `O365_PRINCIPAL`, normalizes via `CanonicalIdentityMapper.to_canonical()`,
  raises `RuntimeError` when absent/unmappable (fail closed);
  `build_cli_permission_context()` wraps it into a
  `PermissionContext(channel="cli", user_id=<canonical>)`;
  `bot_declares_o365_device_code(bot)` inspects `bot._credentials` for an
  `o365`/`device_code` entry.
- `parrot/cli/repl.py`: `REPLConfig` gained an optional `permission_context`
  field (typed `Any`, not the concrete dataclass — see pitfall below);
  `AgentREPL.send()`/`send_stream()` now pass it to `bot.ask`/`ask_stream`.
- `parrot/cli/agent_repl.py`: after loading the agent (standalone mode only),
  calls `bot_declares_o365_device_code()`; only when True does it call
  `build_cli_permission_context()` (which enforces `O365_PRINCIPAL`) and
  attach it to `REPLConfig`. Agents that don't declare the o365 device-code
  provider are completely unaffected — no blanket `O365_PRINCIPAL`
  requirement for all CLI sessions.
- `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` (NEW):
  5 tests — fail-closed on missing principal, identity normalization,
  `PermissionContext` construction, full end-to-end (device flow → vault
  persist → cache hit on 2nd resolve) via a minimal `AbstractTool` subclass
  driving the broker gate directly (mirrors the existing
  `tests/unit/test_tool_credential_seam.py` pattern rather than a full
  LLM-backed bot harness), and the WorkIQ-OBO interop test proving a
  device-code-written `o365:access_token` is consumable by
  `WorkIQOBOCredentialResolver` via the same `VaultTokenSync` instance.

**Pitfall hit:** typing `REPLConfig.permission_context` as the concrete
`PermissionContext` dataclass broke pydantic model construction
(`PydanticUserError: REPLConfig is not fully defined` — pydantic tries to
resolve `PermissionContext`'s own `TYPE_CHECKING`-only `TraceContext`
forward ref even with `arbitrary_types_allowed=True`, since stdlib
dataclasses get special schema treatment). Fixed by typing the field as
`Optional[Any]`, matching how `bots/base.py` already types the same
parameter on `ask()`/`ask_stream()`. Caught by the existing
`tests/cli/test_integration.py` suite (43 tests total run — all pass; the
regression was found and fixed before finalizing this task).

**Known gap — flagged, not fixed here (no scope creep):** "agent
credentials config (manifest or AgentDefinition)" from the task's file
table was NOT created as a new concrete production file. A repo-wide grep
found **zero** existing production call sites that pass `credentials=[...]`
to an `AbstractBot` subclass — FEAT-264's broker is fully wired but no
concrete CLI-launched O365 agent exists yet to attach
`ProviderCredentialConfig(provider="o365", auth="device_code")` to.
Inventing one would be speculative scope creep beyond this task's mechanism-
wiring scope. The integration test proves the full chain works with a
representative test double; wiring a REAL O365 CLI agent is a natural
follow-up once one exists (tracked alongside the `post_auth_o365` bridge
noted in spec §8).

All 5 new integration tests pass; full `tests/cli/` + `test_tool_credential_seam.py`
regression suite (43 tests) passes; `test_credential_broker.py` (14) and
`test_agent_service.py` unaffected; `ruff check` clean on all
created/modified files (pre-existing unrelated lint findings in
`bots/base.py` confirmed present on `dev` before this feature).
