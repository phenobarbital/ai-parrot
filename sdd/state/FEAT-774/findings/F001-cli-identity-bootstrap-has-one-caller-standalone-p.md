---
id: F001
query_id: [Q014, Q001]
type: [grep, wiki_query]
intent: "Callers of the CLI identity bootstrap"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-001, FW-001]
---

# F001 — CLI identity bootstrap has one caller: standalone parrot agent

## Summary

**[FC-001]** `build_cli_permission_context` / `bot_declares_o365_device_code` are called from exactly one production site, `parrot agent` standalone mode, and only when the loaded bot declares an `o365`/`device_code` credential. No other CLI entry (mcp-local, agentd, toolkits) builds a CLI permission context. Matches under `packages/ai-parrot/build/` are stale build copies, not source.

**[FW-001]** Wiki ranks `TASK-3413` (FEAT-573 `parrot agent` entry, score 1.00) and `TurnRunner._identity_kwargs` (0.67) first. `parrot agent` (`parrot/cli/agent_repl.py`) has three identity inputs: `--user USER_ID` (standalone only, refused with `--server`, AC27), `--token` / `PARROT_SERVER_TOKEN` (bearer for `--server` mode, handed to `ServerAgentProxy`), and a `PermissionContext` built **only** when the bot declares an O365 `device_code` credential (`bot_declares_o365_device_code` → `build_cli_permission_context()`). Otherwise `REPLConfig.user_id` defaults to the literal `"cli-user"` and `permission_context=None`. `TurnRunner._identity_kwargs` forwards `session_id`, `output_mode`, `permission_context` and `user_id` (omitted when None) to `bot.ask()`. There is no login state, no Navigator `user_id`, and no connection-aware principal on this surface.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 23-23
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
- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 80-89
  symbol: `agent`
  excerpt: |
    "user_id",            # --user USER_ID  "Identity sent with each request (standalone only; refused with --server)."
    "--token",            # envvar PARROT_SERVER_TOKEN  "Bearer token for --server mode."
- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 162
  symbol: `_run`
  excerpt: |
    loader = ServerAgentProxy(server, token=token)
- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 186-189
  symbol: `_run`
  excerpt: |
    if server and user_id:  # Q8 / AC27
        ... "token (--token / PARROT_SERVER_TOKEN)."
- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 218-221
  symbol: `_run`
  excerpt: |
    permission_context = None
    if not server and bot_declares_o365_device_code(bot):
        permission_context = build_cli_permission_context()
- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 238-247
  symbol: `REPLConfig`
  excerpt: |
    config = REPLConfig(
        ...
        permission_context=permission_context,
        server_token=token,
        user_id=None if server else (user_id or "cli-user"),
- path: `packages/ai-parrot/src/parrot/cli/session.py`
  lines: 105-114
  symbol: `TurnRunner._identity_kwargs`
  excerpt: |
    kwargs = {"session_id": self.config.session_id, "output_mode": OutputMode.TERMINAL,
              "permission_context": self.config.permission_context}
    if self.config.user_id is not None:
        kwargs["user_id"] = self.config.user_id

## Notes

**[FC-001]** Tests: tests/cli/test_identity.py, tests/cli/test_agent_command.py:28, tests/integration/test_cli_devicecode_e2e.py:24-180.

**[FW-001]** Wiki pages: `file:sdd/tasks/completed/TASK-3413-agent-command-entry-point.md` (1.00), `sym:...cli/session.py#TurnRunner._identity_kwargs` (0.67), `sym:...cli/repl.py#REPLConfig` (0.33), `file:...cli/agent_repl.py` (0.15). Line numbers confirmed by grep on the live file. `REPLConfig.user_id` is typed `Optional[str] = "cli-user"` per TASK-3413's contract (repl.py). For S-4 this means: the only principal a CLI agent carries today is a free-form `--user` string or an Entra OID/email from env — neither is a Navigator `user_id`.
[cross-lane: type=read, intent=confirm REPLConfig.user_id default and permission_context field in parrot/cli/repl.py]
[citation-check: missing] packages/ai-parrot/tests/cli/test_identity.py — symbol `test_identity` is a file label, not a code symbol; file exists (probe c2)
