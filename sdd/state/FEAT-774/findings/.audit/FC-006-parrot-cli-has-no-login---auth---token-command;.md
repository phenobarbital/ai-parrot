---
id: FC-006
query_id: Q019
type: grep
intent: "CLI sub-commands and login state"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-006 — parrot CLI has no login / auth / token command; --token only for --server mode

## Summary

`parrot/cli/__init__.py` registers lazy Click commands (`LazyGroup`, :103) but grep finds no `login`, `auth_token`, `session_token`, `api_key` or `NAVIGATOR*` handling in `__init__.py`, `commands.py` or `session.py`. The only identity inputs are `parrot agent --user USER_ID` (standalone only) and `--token` / `PARROT_SERVER_TOKEN` (bearer for `--server` mode); `--user` with `--server` is refused (identity comes from the bearer token).

## Citations

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 103
  symbol: `LazyGroup`
  excerpt: |
    @click.group(cls=LazyGroup)

- path: `packages/ai-parrot/src/parrot/cli/agent_repl.py`
  lines: 78-90, 186-191, 247
  symbol: `agent (click options)`
  excerpt: |
    @click.option("--user", "user_id", ... help="Identity sent with each request (standalone only; refused with --server).")
    @click.option("--token", envvar="PARROT_SERVER_TOKEN", ... help="Bearer token for --server mode.")
    if server and user_id:  # Q8 / AC27
        console.print("--user is not allowed with --server; identity comes from the bearer token ...")
    user_id=None if server else (user_id or "cli-user"),


## Notes

Standalone default identity is the literal `"cli-user"` (agent_repl.py:247) — not a platform principal.
