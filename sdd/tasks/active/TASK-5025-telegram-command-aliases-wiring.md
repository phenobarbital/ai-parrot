# TASK-5025: Wire generic commands into the wrapper; Jira/Office365 commands become aliases

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5024, TASK-5023, TASK-5020
**Assigned-to**: unassigned

---

## Context

Spec §2 "Telegram commands", §3 Module 6 (wiring half), AC-4/5/10/17. Replaces `_register_jira_commands` and
`_register_office365_commands` (wrapper.py:400-504) with `_register_connection_commands`, reduces
`jira_commands.py` to three aliases (deleting the per-provider handlers, `_telegram_principal` and
`TelegramOAuthNotifier`), and makes `/connect_office365` & co. alias the generic handlers only when an `o365`
provider is connectable — otherwise today's session-copy handlers stay unchanged.

---

## Scope

- `jira_commands.py`: keep `register_jira_commands(router, *, commands, principal_source, context_source,
  extra_state_factory, on_disconnected=None)` registering `/connect_jira` → `connect_handler(…, "jira")`,
  `/disconnect_jira` → `disconnect_handler(…, "jira")`, `/jira_status` → `connections_handler(…, only="jira")`.
  Delete `connect_jira_handler`, `disconnect_jira_handler`, `jira_status_handler`, `_telegram_principal`,
  `TelegramOAuthNotifier`, `_auth_keyboard`. Keep `_TELEGRAM_CHANNEL` (imported by `post_auth_jira.py:27`).
- `office365_commands.py`: `register_office365_commands(router, session_provider, *, commands=None, principal_source=None,
  context_source=None, extra_state_factory=None)` → aliases when `commands and commands.resolve_provider("o365")`, else today's handlers.
- `wrapper.py`: `_register_connection_commands()` builds `ConnectionCommandService(service=IntegrationsService(...),
  app=self.app, channel="telegram", allowlist=self.config.connection_providers)`; registers generic + Jira aliases +
  Office365; `principal_source` = `_ensure_principal_link` then `principal_for_session`; `context_source` =
  `_connection_permission_context`; `extra_state_factory` = `{"chat_id", "bot_id": self._bot_id}`; `on_disconnected`
  clears the Jira session for jira. Skip entirely when no provider is connectable and no `o365` fallback applies
  (`auth_methods` contains `"oauth2"`). No DB pool ⇒ commands reply "Connections are not available on this bot".
  Move the `_register_jira_session_hook()` call (TASK-5023) here. Menu: `connect`, `disconnect`, `connections` plus
  the aliases shown today.
- The `IntegrationsService` instance: `IntegrationsService(vault, authorizer=app.get("connection_authorizer"))`,
  read per call like Slack/Teams (verified wiring in TASK-5018's Completion Note). No authorizer ⇒ service
  denies ⇒ "not allowed" (AC-7). Never `permission_evaluator` — removed by FEAT-775 TASK-5091 (issue:782f6c990de1).
- Update tests: `test_telegram_jira_commands.py`, `test_telegram_office365_commands.py`,
  `test_wrapper_register_command_menu.py`, `test_integration_menu_parity.py`, and
  `tests/integration/oauth2/test_e2e_telegram_regression.py` (alias parity + new e2e cases).

**NOT in scope**: needs-auth prompts (TASK-5026); combined login (TASK-5027–5029).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` | MODIFY | aliases only |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py` | MODIFY | conditional aliases |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | `_register_connection_commands` |
| `packages/ai-parrot/tests/unit/test_telegram_jira_commands.py` | MODIFY | alias tests |
| `packages/ai-parrot/tests/unit/test_telegram_office365_commands.py` | MODIFY | o365 alias / fallback |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_wrapper_register_command_menu.py` | MODIFY | menu entries |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_integration_menu_parity.py` | MODIFY | parity |
| `tests/integration/oauth2/test_e2e_telegram_regression.py` | MODIFY | e2e alias/any-provider cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.connection_commands import (register_connection_commands, connect_handler,
    disconnect_handler, connections_handler)                                       # TASK-5024
from parrot.integrations.core.auth.connections import ConnectionCommandService     # TASK-5021
from parrot.auth.oauth2.service import IntegrationsService                         # verified: service.py:65
```

### Existing Signatures to Use
```python
# telegram/jira_commands.py (276 lines)
_TELEGRAM_CHANNEL = "telegram"                                     # :39 (keep — post_auth_jira.py:27 imports it)
def _auth_keyboard(url) / async def connect_jira_handler(...) :53 / async def _telegram_principal(...) :102
async def disconnect_jira_handler(...) :115 / async def jira_status_handler(...) :158
def register_jira_commands(router, oauth_manager, session_clearer=None, session_lookup=None) -> None   # :192
class TelegramOAuthNotifier                                        # :235

# telegram/office365_commands.py
SessionProvider = Callable[[int], TelegramUserSession]             # :18
def register_office365_commands(router: Router, session_provider: SessionProvider) -> None   # :106

# telegram/wrapper.py
def _add_platform_commands(self, entries) -> None                  # :387
def _register_jira_commands(self) -> None                          # :400 (gate app["jira_oauth_manager"] :408)
def _register_office365_commands(self) -> None                     # :480 (gate "oauth2" in auth_methods :486-487)
# callers of both: `self._register_jira_commands()` :286 and `self._register_office365_commands()` :287 (in __init__) — replace with one call
```

### Does NOT Exist
- ~~`_register_connection_commands`~~ — created here.
- ~~A Telegram-id-keyed fallback for unlinked users~~ — unlinked ⇒ "/login first" (U3).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_telegram_jira_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_telegram_office365_commands.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_wrapper_register_command_menu.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_integration_menu_parity.py", "action": "MODIFY"},
    {"path": "tests/integration/oauth2/test_e2e_telegram_regression.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py#register_jira_commands",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py#TelegramOAuthNotifier",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/office365_commands.py#register_office365_commands",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._register_jira_commands",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._register_office365_commands"
  ]
}
```

---

## Implementation Notes

- Run `wikitoolkit symbols blast register_jira_commands` and `... TelegramOAuthNotifier` before deleting; fix every caller.
- Office365 fallback must be byte-identical to today when `o365` is not connectable (AC-5).
- Commands with a missing pool: still register (so the user gets a clear reply) but reply "Connections are not available on this bot".

---

## Implementation Blueprint

### Steps (in order)
1. Blast-radius check; rewrite `jira_commands.py` to the alias block below.
2. Add the conditional alias branch to `office365_commands.py`.
3. Replace the two wrapper registration methods with `_register_connection_commands` and update its caller(s).
4. Update the five test files; add the spec's e2e cases to the regression file.

### `telegram/jira_commands.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def register_jira_commands(' .../telegram/jira_commands.py)
# REPLACE the module body below `_TELEGRAM_CHANNEL = "telegram"` with:
def register_jira_commands(router: Router, *, commands: "ConnectionCommandService", principal_source: "PrincipalSource",
                           context_source: "ContextSource", extra_state_factory: "ExtraStateFactory",
                           on_disconnected: Optional[Callable[[int, str], None]] = None) -> None:
    """Register /connect_jira, /disconnect_jira and /jira_status as aliases of the generic handlers."""
    from parrot.integrations.telegram.connection_commands import (
        connect_handler, connections_handler, disconnect_handler,
    )

    async def _connect(message: Message) -> None:
        await connect_handler(message, "jira", commands=commands, principal_source=principal_source,
                              context_source=context_source, extra_state_factory=extra_state_factory)

    # FILL IN: _disconnect (disconnect_handler(..., "jira", on_disconnected=...)), _status (connections_handler(..., only="jira"))
    router.message.register(_connect, Command("connect_jira"))
    # FILL IN: register _disconnect / _status
# also update the module docstring (no TelegramOAuthNotifier mention)
```

### `telegram/office365_commands.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def register_office365_commands(' .../telegram/office365_commands.py)
# REPLACE the signature + add a first branch:
def register_office365_commands(router: Router, session_provider: SessionProvider, *, commands: Optional[Any] = None,
                                principal_source: Optional[Any] = None, context_source: Optional[Any] = None,
                                extra_state_factory: Optional[Any] = None) -> None:
    """Alias the generic handlers when ``o365`` is connectable; else today's session-copy handlers."""
    if commands is not None and commands.resolve_provider("o365") is not None:
        # FILL IN: register connect_office365/disconnect_office365/office365_status → generic handlers with "o365"
        return
    # existing body unchanged below
```

### `telegram/wrapper.py` (MODIFY)
```python
# occurrences: 1 each (verified: grep -c '    def _register_jira_commands(self) -> None:' and
# grep -c '    def _register_office365_commands(self) -> None:' .../telegram/wrapper.py)
# REPLACE both methods (:400-504) with:
    def _register_connection_commands(self) -> None:
        """Register /connect, /disconnect, /connections plus Jira/Office365 aliases (FEAT-776 M6)."""
        # FILL IN: build ConnectionCommandService (or None when app is None);
        # skip when no connectable provider and "oauth2" not in auth_methods;
        # principal_source = async lambda update → session via self._user_sessions / _get_user_session-equivalent,
        #   await self._ensure_principal_link(session); return await principal_for_session(session, tenant_id=self.config.tenant)
        # register_connection_commands(...), register_jira_commands(...) when "jira" connectable,
        # register_office365_commands(...); self._add_platform_commands(menu entries); self._register_jira_session_hook()
```

### FILL IN checklist
- [ ] Callers (:286-287) switched to `_register_connection_commands`
- [ ] `IntegrationsService` `authorizer=` wiring copied from TASK-5018
- [ ] Test updates: `test_jira_aliases_route_to_generic`, `test_office365_alias_only_when_registered`, `test_command_menu_entries`;
      e2e: `test_e2e_telegram_connect_any_provider`, `test_e2e_telegram_jira_parity` (alias), `test_e2e_cross_channel_from_telegram`,
      `test_e2e_unlinked_user_forced_reconnect`, `test_telegram_disconnect_routes_revoked`

---

## Acceptance Criteria

- [ ] AC-4, AC-5, AC-6, AC-7 (via the shared `ConnectionAuthorizer`), AC-10 (no `TelegramOAuthNotifier` left in `packages/`), AC-17 (disconnect → revoke with telegram channel/principal, Jira session cleared)
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_telegram_jira_commands.py -q`
- `pytest packages/ai-parrot/tests/unit/test_telegram_office365_commands.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_wrapper_register_command_menu.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_integration_menu_parity.py -q`
- `pytest tests/integration/oauth2/test_e2e_telegram_regression.py -q`

---

## Test Specification

Test names fixed by spec §4 (M6 rows + listed integration tests).

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5024, TASK-5023, TASK-5020 are `done`
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src:packages/ai-parrot-server/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5025 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
