---
id: FC-001
query_id: Q014
type: grep
intent: "Callers of the CLI identity bootstrap"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-001 — CLI identity bootstrap has one caller: standalone parrot agent

## Summary

`build_cli_permission_context` / `bot_declares_o365_device_code` are called from exactly one production site, `parrot agent` standalone mode, and only when the loaded bot declares an `o365`/`device_code` credential. No other CLI entry (mcp-local, agentd, toolkits) builds a CLI permission context. Matches under `packages/ai-parrot/build/` are stale build copies, not source.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 23, 218-224
  symbol: `build_cli_permission_context`
  excerpt: |
    from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context
    ...
    permission_context = None
    if not server and bot_declares_o365_device_code(bot):
        try:
            permission_context = build_cli_permission_context()
        except RuntimeError as exc:
            console.print(f"[bold red]O365 device-code identity error:[/bold red] {exc}")

- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: 27, 45, 76, 104-105, 108
  symbol: `CLI_CHANNEL`
  excerpt: |
    CLI_CHANNEL: str = "cli"
    def resolve_cli_o365_principal() -> str:
    def build_cli_permission_context(user_id: Optional[str] = None) -> PermissionContext:
        session = UserSession(user_id=canonical, tenant_id=tenant_id, roles=frozenset())
        return PermissionContext(session=session, channel=CLI_CHANNEL)
    def bot_declares_o365_device_code(bot: object) -> bool:

- path: `packages/ai-parrot/tests/cli/test_identity.py`
  lines: 1-51
  symbol: `test_identity`
  excerpt: |
    tests cover tenant sentinel + channel


## Notes

Tests: tests/cli/test_identity.py, tests/cli/test_agent_command.py:28, tests/integration/test_cli_devicecode_e2e.py:24-180.
