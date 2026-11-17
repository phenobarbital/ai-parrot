---
id: FW-002
query_id: Q006
type: wiki_query
intent: "Orient: existing CLI/device-code identity bootstrap and its spec (FEAT-266 O365 homologation) — what 'CLI identity' means today."
executed_at: 2026-10-30T15:20:30Z
duration_ms: 1600
parent_id: null
depth: 1
---

# FW-002 — `parrot/cli/identity.py`: the only CLI identity is an Entra principal from `O365_PRINCIPAL`, device-code only

## Summary

`parrot.cli.identity` (wiki 1.00) is the FEAT-266 bootstrap: `resolve_cli_o365_principal()` reads `O365_PRINCIPAL` (email or Entra OID), normalizes it through `CanonicalIdentityMapper.to_canonical({"oid": raw, "email": raw})` and fails closed; `build_cli_permission_context()` wraps it in `UserSession(user_id=canonical, tenant_id=O365_TENANT_ID or "unset-cli-tenant", roles=frozenset())` → `PermissionContext(session, channel="cli")`; `bot_declares_o365_device_code(bot)` gates the bootstrap to bots whose `_credentials` declare `provider="o365", auth="device_code"`. `wikitoolkit related` shows the ONLY production caller is `agent_repl.py` (plus two test files); the module references `parrot.auth.identity` and `parrot.auth.permission` only. The module docstring states the CLI is the only device-code surface (Telegram excluded). The key is Entra-canonical, not the Navigator bigint `user_id` that FEAT-773 U1 makes primary.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: 1-13
  symbol: module docstring
  excerpt: |
    CLI identity bootstrap for the O365 device-code broker seam (FEAT-266).
    ... The CLI is the only surface for device-code (Telegram explicitly excluded), so this module
    reads the explicit Entra principal from the ``O365_PRINCIPAL`` environment variable ...

- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: 22-42
  symbol: `O365_PRINCIPAL_ENV_VAR`
  excerpt: |
    O365_PRINCIPAL_ENV_VAR: str = "O365_PRINCIPAL"
    CLI_CHANNEL: str = "cli"
    O365_TENANT_ID_ENV_VAR: str = "O365_TENANT_ID"
    UNSET_CLI_TENANT: str = "unset-cli-tenant"

- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: 45-69
  symbol: `resolve_cli_o365_principal`
  excerpt: |
    def resolve_cli_o365_principal() -> str:
        raw = (os.environ.get(O365_PRINCIPAL_ENV_VAR) or "").strip()
        if not raw: raise RuntimeError(...)
        canonical = CanonicalIdentityMapper.to_canonical({"oid": raw, "email": raw})

- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: 72-105
  symbol: `build_cli_permission_context`
  excerpt: |
    def build_cli_permission_context(user_id: Optional[str] = None) -> PermissionContext:
        canonical = user_id or resolve_cli_o365_principal()
        tenant_id = (os.environ.get(O365_TENANT_ID_ENV_VAR) or "").strip() or UNSET_CLI_TENANT
        session = UserSession(user_id=canonical, tenant_id=tenant_id, roles=frozenset())
        return PermissionContext(session=session, channel=CLI_CHANNEL)

- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: 108-126
  symbol: `bot_declares_o365_device_code`
  excerpt: |
    for cfg in getattr(bot, "_credentials", None) or []:
        if getattr(cfg, "provider", None) == "o365" and getattr(cfg, "auth", None) == "device_code":
            return True

## Notes

Wiki: `file:packages/ai-parrot/src/parrot/cli/identity.py` (1.00); `sym:...#resolve_cli_o365_principal` (0.79); `sym:...#build_cli_permission_context` (0.56); tests `packages/ai-parrot/tests/cli/test_identity.py`, `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py`; task `TASK-1685`, `TASK-1687` (tenant sentinel). Line ranges are from the full-file read done in the parent session (file is ~126 lines) — treat as ±3. `wikitoolkit related` (Q012) inbound edges: `agent_repl.py`, the two tests, `dir:parrot/cli`. The module comment notes `roles=frozenset()` is inert because no CLI path wires a `ToolManager._resolver` — a PBAC gap S-4 inherits.
[cross-lane: type=git_log, intent=history of parrot/cli/identity.py — FEAT-266/267 dates]
