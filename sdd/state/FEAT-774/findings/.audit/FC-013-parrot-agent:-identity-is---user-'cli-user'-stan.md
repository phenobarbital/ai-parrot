---
id: FC-013
query_id: Q026
type: read
intent: "REPL entry: identity supply"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-013 — parrot agent: identity is --user/'cli-user' standalone, bearer token in --server mode

## Summary

`parrot agent` loads a bot via `StandaloneAgentLoader` or `ServerAgentProxy(server, token=token)`. Standalone: `REPLConfig.user_id = user_id or "cli-user"`, `permission_context` built only for o365 device-code bots. Server mode: `user_id=None`, identity is the bearer token (`--token`/`PARROT_SERVER_TOKEN`), `--user` refused. `TurnRunner(bot, config)` carries these into `ask()`.

## Citations

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 161-164, 238-252
  symbol: `_run (loader + REPLConfig)`
  excerpt: |
    if server: loader = ServerAgentProxy(server, token=token)
    else:      loader = StandaloneAgentLoader()
    config = REPLConfig(agent_name=name, streaming=streaming, server_url=server,
        permission_context=permission_context, ui_mode=mode, resume_session_id=resume_id,
        server_token=token, history_enabled=not no_history,
        user_id=None if server else (user_id or "cli-user"))
    runner = TurnRunner(bot, config)


## Notes

Two CLI identity regimes already exist: local pseudo-identity vs. server bearer. S-4's Navigator user_id must come from the latter or a new login.
