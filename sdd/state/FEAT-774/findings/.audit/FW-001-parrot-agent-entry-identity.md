---
id: FW-001
query_id: Q001
type: wiki_query
intent: "Orient: the console CLI agents surface (AgentREPL, REPL session, permission context) in the knowledge graph."
executed_at: 2026-10-30T15:20:00Z
duration_ms: 1800
parent_id: null
depth: 1
---

# FW-001 — `parrot agent` entry: identity enters as `--user` / `--token` / O365 device-code context only

## Summary

Wiki ranks `TASK-3413` (FEAT-573 `parrot agent` entry, score 1.00) and `TurnRunner._identity_kwargs` (0.67) first. `parrot agent` (`parrot/cli/agent_repl.py`) has three identity inputs: `--user USER_ID` (standalone only, refused with `--server`, AC27), `--token` / `PARROT_SERVER_TOKEN` (bearer for `--server` mode, handed to `ServerAgentProxy`), and a `PermissionContext` built **only** when the bot declares an O365 `device_code` credential (`bot_declares_o365_device_code` → `build_cli_permission_context()`). Otherwise `REPLConfig.user_id` defaults to the literal `"cli-user"` and `permission_context=None`. `TurnRunner._identity_kwargs` forwards `session_id`, `output_mode`, `permission_context` and `user_id` (omitted when None) to `bot.ask()`. There is no login state, no Navigator `user_id`, and no connection-aware principal on this surface.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 23
  symbol: `build_cli_permission_context`
  excerpt: |
    from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context

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

Wiki pages: `file:sdd/tasks/completed/TASK-3413-agent-command-entry-point.md` (1.00), `sym:...cli/session.py#TurnRunner._identity_kwargs` (0.67), `sym:...cli/repl.py#REPLConfig` (0.33), `file:...cli/agent_repl.py` (0.15). Line numbers confirmed by grep on the live file. `REPLConfig.user_id` is typed `Optional[str] = "cli-user"` per TASK-3413's contract (repl.py). For S-4 this means: the only principal a CLI agent carries today is a free-form `--user` string or an Entra OID/email from env — neither is a Navigator `user_id`.
[cross-lane: type=read, intent=confirm REPLConfig.user_id default and permission_context field in parrot/cli/repl.py]
