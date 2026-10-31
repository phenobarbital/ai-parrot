# TASK-4978: REPL identity regimes: login principal in standalone, bearer in --server, O365 bootstrap hard cut

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4974, TASK-4973
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (G2, S12, AC-3, AC-4, AC-13, §8 Q5) and the identity.py half of Module 2. Three regimes:
(1) standalone + login → `user_id` = Navigator id, `PermissionContext(channel="cli")` with server roles + tenant, and a
CLI broker for the bot's declared `credential_provider`s; `--user` together with a login is refused (exit 2);
(2) `--server` → the login's access token is the default bearer, no local principal, and a 401 triggers one
`refresh_login` + retry (Q5); (3) no login → exactly today (`cli-user`, no gate). The `O365_PRINCIPAL` /
`O365_TENANT_ID` bootstrap in `cli/identity.py` is removed (hard cut, no shim).

---

## Scope

- `agent_repl.py`: `_run` identity logic + `_declared_providers(bot)`; import from `parrot.cli.principal`.
- `repl.py`: `REPLConfig.login_user_id: Optional[str] = None` (shown by `/info` is optional — leave `/info` alone).
- `identity.py`: reduce to `CLI_CHANNEL` + re-export of `build_cli_permission_context` from `parrot.cli.principal`.
- `loaders.py`: `ServerAgentProxy(..., *, token=None, login_store=None)`; on 401 refresh once then retry; a failed
  refresh prints "Session expired — run 'parrot login' again" and exits 2.
- Tests: new identity-matrix test; update `test_identity.py`, `test_agent_command.py`, `test_loaders_server.py`;
  drop the three `O365_PRINCIPAL` bootstrap tests (and the import) from `test_cli_devicecode_e2e.py` so it still imports.

**NOT in scope**: rewriting `test_cli_devicecode_e2e.py` to the `parrot connect o365 --device` path (TASK-4981); `TurnRunner._identity_kwargs` (unchanged shape); slash commands (TASK-4977).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/agent_repl.py` | MODIFY | identity regimes in _run |
| `packages/ai-parrot/src/parrot/cli/repl.py` | MODIFY | REPLConfig.login_user_id |
| `packages/ai-parrot/src/parrot/cli/identity.py` | MODIFY | hard cut of the O365 bootstrap |
| `packages/ai-parrot/src/parrot/cli/loaders.py` | MODIFY | ServerAgentProxy login_store + 401 refresh |
| `packages/ai-parrot/tests/cli/test_repl_identity_matrix.py` | CREATE | (login, --user, --server) matrix |
| `packages/ai-parrot/tests/cli/test_identity.py` | MODIFY | assert bootstrap removed |
| `packages/ai-parrot/tests/cli/test_agent_command.py` | MODIFY | drop the _credentials pin comment/use |
| `packages/ai-parrot/tests/cli/test_loaders_server.py` | MODIFY | 401 refresh once |
| `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` | MODIFY | remove bootstrap tests/import |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.cli.login import LoginExpired, LoginFileError, LoginStore, refresh_login        # TASK-4968
from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context          # TASK-4974
from parrot.auth.oauth2.remote_client import ServerConnectionsClient                         # TASK-4972
from parrot.auth.oauth2.local_cache import build_cli_broker                                  # TASK-4973
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/agent_repl.py
from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context   # :23 (REPLACE)
async def _run(name, list_agents, server, no_stream, ui="auto", session=None, user_id=None, token=None, no_history=False)   # :134
        loader = ServerAgentProxy(server, token=token)                    # :162
    if server and user_id:  # Q8 / AC27 ... raise SystemExit(2)          # :186-191 (pattern for the new refusal)
    permission_context = None                                             # :218 ; O365 block :219-224 (REMOVE)
    config = REPLConfig(..., server_token=token, ..., user_id=None if server else (user_id or "cli-user"))   # :238-248 (:247)
    runner = TurnRunner(bot, config)                                      # :252
# packages/ai-parrot/src/parrot/cli/repl.py
class REPLConfig(BaseModel): ... user_id: Optional[str] = "cli-user" (:64); permission_context (:65); server_token (:68); history_enabled: bool = True (:69)
# packages/ai-parrot/src/parrot/cli/identity.py — REMOVE: O365_PRINCIPAL_ENV_VAR (:22), O365_TENANT_ID_ENV_VAR (:33),
#   UNSET_CLI_TENANT (:40), resolve_cli_o365_principal (:45), build_cli_permission_context(user_id) (:76),
#   bot_declares_o365_device_code (:108); KEEP CLI_CHANNEL (:27)
# callers of identity.py (grep): agent_repl.py:23, tests/cli/test_identity.py:10, tests/integration/test_cli_devicecode_e2e.py:22-25,
#   tests/cli/test_agent_command.py:28 (comment about bot_declares_o365_device_code)
# packages/ai-parrot/src/parrot/cli/loaders.py
class ServerAgentProxy:                                                   # :471
    def __init__(self, server_url: str, timeout: int = 30, *, token: Optional[str] = None) -> None   # :483-488 ; `self._token = token` :500
    def _get_session(self) -> aiohttp.ClientSession   # :505 — Bearer header baked into the session at creation (:510-513)
    # HTTP sites: ServerAgentProxy session.get (:532, :558, raise_for_status); _ServerBotProxy self._session.post (:287, :333)
    #   _ServerBotProxy receives the proxy's session in its __init__ (:243)
# packages/ai-parrot/src/parrot/tools/manager.py: ToolManager.set_broker(broker) (:518) ; get_all_tools() -> list (:1421)
# AbstractBot.tool_manager attribute (bots/abstract.py:398) ; AbstractTool.credential_provider (abstract.py:306)
```

### Does NOT Exist
- ~~`resolve_cli_o365_principal`, `bot_declares_o365_device_code`, `O365_PRINCIPAL_ENV_VAR`, `O365_TENANT_ID_ENV_VAR`,
  `UNSET_CLI_TENANT` after this task~~ — removed (hard cut, project policy: no shims for internal APIs).
- ~~`ServerAgentProxy(login_store=...)`~~ — added here (Q5).
- ~~`REPLConfig.login_user_id`~~ — added here.
- ~~sending `user_id` in `--server` mode~~ — never (S12, AC-14); `_ServerBotProxy` already never sends it (`loaders.py:280`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/cli/agent_repl.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/repl.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/identity.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/loaders.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_repl_identity_matrix.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_identity.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_agent_command.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_loaders_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/agent_repl.py#_run",
    "sym:packages/ai-parrot/src/parrot/cli/repl.py#REPLConfig",
    "sym:packages/ai-parrot/src/parrot/cli/loaders.py#ServerAgentProxy",
    "sym:packages/ai-parrot/src/parrot/cli/identity.py#build_cli_permission_context"
  ]
}
```

---

## Implementation Notes

- `_run` order: `store = LoginStore()`; `login = await asyncio.to_thread(_safe_load, store)` where a `LoginFileError`
  prints the error and exits 2 (fail closed — do not silently ignore a tampered login file).
  `if not server and login and user_id:` → "--user is not allowed when logged in; identity comes from `parrot login`"
  exit 2 (mirror :186-191). Server mode: `ServerAgentProxy(server, token=token or (login.access_token if login else
  None), login_store=store if (login and not token) else None)` — an explicit `--token` wins and is never refreshed.
- Standalone + login (after the bot loads): `async with ServerConnectionsClient(store) as client:` resolve with
  `CliPrincipalResolver(store, client).resolve_with_roles("cli", login.user_id)`; `None` → warn and continue as today;
  else `permission_context = build_cli_permission_context(principal, roles=roles)` and, when `_declared_providers(bot)`
  is non-empty, `bot.tool_manager.set_broker(build_cli_broker(store, providers))` (its own client — the resolver's client
  is closed after the block).
- `REPLConfig(..., user_id=None if server else (principal.user_id if principal else (user_id or "cli-user")),
  login_user_id=login.user_id if login else None)`.
- `_declared_providers(bot)`: `{t.credential_provider for t in bot.tool_manager.get_all_tools() if getattr(t,
  "credential_provider", None)}`; tolerate a bot without `tool_manager` (return empty set).
- `ServerAgentProxy` 401: refresh once with `refresh_login(record, session)` (fresh short-lived `aiohttp.ClientSession`),
  `store.save`, set `self._token`, close the old session so `_get_session()` rebuilds the header, retry once. `LoginExpired`
  or a second 401 → `click.echo("Session expired — run 'parrot login' again", err=True)`; `raise SystemExit(2)`. Apply to
  every request site (both classes) — a small `_send(method, url, **kw)` helper on the proxy that `_ServerBotProxy` calls
  is the simplest shape.
- `test_agent_command.py:28` only has a comment + `bot._credentials = []`; keep the pin harmless or drop it, and make
  every test isolate `PARROT_LOGIN_FILE` to a missing tmp path so a developer's real login never changes results.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Hard-cut `identity.py` and update its three test callers — *why*: AC-13; must land with its only caller.
2. Rewrite the identity section of `_run` — *why*: AC-3/AC-4 regimes, S12.
3. Add `REPLConfig.login_user_id` — *why*: §3 M7.
4. Add `login_store` + 401 refresh to `ServerAgentProxy` — *why*: §8 Q5.
5. Write the identity-matrix test; run all validation commands.

### `packages/ai-parrot/src/parrot/cli/identity.py` (MODIFY — whole-file replacement)
```python
"""CLI identity constants (FEAT-774 hard cut of the FEAT-266 O365_PRINCIPAL bootstrap).

The CLI principal now comes from `parrot login` (see :mod:`parrot.cli.principal`).
"""
from __future__ import annotations

from parrot.cli.principal import build_cli_permission_context

#: Surface channel used for every CLI-originated permission context.
CLI_CHANNEL: str = "cli"

__all__ = ["CLI_CHANNEL", "build_cli_permission_context"]
```

### `packages/ai-parrot/src/parrot/cli/agent_repl.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context' cli/agent_repl.py)
# REPLACE that line (verified: agent_repl.py:23) with:
from parrot.cli.login import LoginFileError, LoginStore
from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context

# occurrences: 1 (verified: grep -c '        loader = ServerAgentProxy(server, token=token)' cli/agent_repl.py)
# BEFORE `    if server:` (verified: agent_repl.py:161) insert the login load, and REPLACE :162 with:
        loader = ServerAgentProxy(
            server, token=token or (login.access_token if login else None),
            login_store=store if (login and not token) else None,
        )

# occurrences: 1 (verified: grep -c '    permission_context = None' cli/agent_repl.py)
# REPLACE the FEAT-266 block (verified: agent_repl.py:215-224, comment + `permission_context = None` + O365 if-block) with:
    permission_context = None
    principal = None
    if not server and login is not None:
        # FILL IN: async with ServerConnectionsClient(store) as client → resolve_with_roles("cli", login.user_id);
        #          None → console warning, keep today's behaviour; else permission_context = build_cli_permission_context(...)
        #          and bot.tool_manager.set_broker(build_cli_broker(store, providers)) when _declared_providers(bot) — AC-3
        pass

# occurrences: 1 (verified: grep -c '        user_id=None if server else (user_id or "cli-user"),' cli/agent_repl.py)
# REPLACE that line (verified: agent_repl.py:247) with:
        user_id=None if server else (principal.user_id if principal else (user_id or "cli-user")),
        login_user_id=login.user_id if login else None,

# APPEND a module-level helper:
def _declared_providers(bot: object) -> set[str]:
    """Credential providers declared by the bot's tools (AbstractTool.credential_provider, abstract.py:306)."""
    manager = getattr(bot, "tool_manager", None)
    if manager is None:
        return set()
    return {t.credential_provider for t in manager.get_all_tools() if getattr(t, "credential_provider", None)}
# FILL IN: also the `--user` + login refusal (exit 2) next to the existing --server/--user guard (:186-191), and the
#          login load: store = LoginStore(); LoginFileError → console error + SystemExit(2)
```

### `packages/ai-parrot/src/parrot/cli/repl.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    history_enabled: bool = True' cli/repl.py)
# AFTER — insert below `    history_enabled: bool = True` (verified: repl.py:69); document it in the class docstring
    login_user_id: Optional[str] = None
```

### `packages/ai-parrot/src/parrot/cli/loaders.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._token = token' cli/loaders.py)
# In ServerAgentProxy.__init__ add the keyword `login_store: Optional["LoginStore"] = None` after `token` (:487) and,
# AFTER `        self._token = token` (verified: loaders.py:500):
        self._login_store = login_store
        self._refreshed = False
# FILL IN: a `_send(method, url, **kw)` helper used by every HTTP site of ServerAgentProxy and _ServerBotProxy:
#          on 401 and self._login_store and not self._refreshed → refresh_login + save + reset session + retry once;
#          LoginExpired / second 401 → "Session expired — run 'parrot login' again" to stderr + SystemExit(2) — Q5
```

### `packages/ai-parrot/tests/cli/test_repl_identity_matrix.py` (CREATE)
```python
"""(login, --user, --server) identity matrix (FEAT-774 M7, AC-3, AC-4)."""
import pytest


@pytest.mark.parametrize("has_login,user,server,expect", [
    (True, None, None, "navigator_id"),
    (True, "bob", None, "refused"),
    (True, None, "http://x", "bearer_default_no_principal"),
    (False, None, None, "cli-user"),
])
async def test_repl_identity_matrix(has_login, user, server, expect, tmp_path, monkeypatch):
    # FILL IN: PARROT_LOGIN_FILE → tmp; patch loaders + CliPrincipalResolver.resolve_with_roles + TurnRunner to capture
    #          REPLConfig; assert user_id / permission_context / server bearer per `expect`; refusal → SystemExit(2)
    ...

def test_identity_o365_bootstrap_removed():
    import parrot.cli.identity as identity
    assert not hasattr(identity, "resolve_cli_o365_principal")
    assert not hasattr(identity, "bot_declares_o365_device_code")
```

### FILL IN checklist
- [ ] `_run` principal resolution + broker wiring; bounded by AC-3/AC-4
- [ ] `_run` `--user` + login refusal and login-file load (fail closed on LoginFileError)
- [ ] `ServerAgentProxy._send` 401 refresh-once; bounded by §8 Q5
- [ ] test updates in `test_identity.py`, `test_agent_command.py`, `test_loaders_server.py`, `test_cli_devicecode_e2e.py`

---

## Acceptance Criteria

- [ ] Standalone + login: every turn uses the Navigator id and a `PermissionContext(channel="cli")` with server roles + tenant (AC-3)
- [ ] `--user` with a login → exit 2; `--server` uses the login token as default bearer and builds no local principal (AC-3, S12)
- [ ] No login → identical to today (`cli-user`, no broker) (AC-4)
- [ ] `O365_PRINCIPAL` / `O365_TENANT_ID` bootstrap gone from `cli/identity.py` (AC-13)
- [ ] `--server` 401 → one refresh + retry; failure → exit 2 with the session-expired message (Q5)
- [ ] All listed CLI tests green; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_repl_identity_matrix.py -q`
- `pytest packages/ai-parrot/tests/cli/test_identity.py -q`
- `pytest packages/ai-parrot/tests/cli/test_agent_command.py -q`
- `pytest packages/ai-parrot/tests/cli/test_loaders_server.py -q`
- `pytest packages/ai-parrot/tests/cli/test_session.py -q`
- `pytest packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/cli/test_repl_identity_matrix.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex) (3 attempts luna/terra; merged manually after task tests run by orchestrator (28 passed)), orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Task tests green apart from sandbox-only test_session failure. Merge-tier reds are pre-existing/environmental only (tests/mcp/test_toolkit_server.py, issue:203c75e0c1ac; sandbox read-only ~/.parrot/cli in test_session).
