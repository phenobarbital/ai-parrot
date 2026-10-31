# TASK-5023: Wire `TelegramConnectionNotifier` (startup registration, attach, Jira hook; drop the Jira adapter)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5022, TASK-5020
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (wiring half), AC-10/11/17. Today `_register_channel_notifiers(app)` (manager.py:134) registers
`TelegramJiraNotifierAdapter` and is reached only from the Teams/Slack startup paths (`_connection_publisher`,
manager.py:438/:999); Telegram-only deployments never register a notifier. The wrapper exposes a Jira session
stamper as `app["telegram_jira_session_stamper"]` (wrapper.py:448-478). This task replaces both with the generic
notifier from TASK-5022 and a registered Jira session hook.

**Cross-feature note**: FEAT-775 M7 also edits `_register_channel_notifiers` (replacing the Teams adapter).
Re-anchor against `origin/dev` before editing; keep the Slack/Teams lines untouched.

---

## Scope

- `core/auth/notifiers.py`: delete `TelegramJiraNotifierAdapter` (and only it; `_JiraAdapterBase`, Slack and
  Teams adapters stay).
- `integrations/manager.py`: `_register_channel_notifiers` registers the generic Telegram notifier via
  `get_or_create_telegram_notifier(app, identity_service=...)` instead of the adapter; `_start_telegram_bot`
  explicitly calls `_connection_publisher(app)` (which registers notifiers) after obtaining the app and before
  polling starts, then `notifier.attach(wrapper's bot_id, bot)`. Repeated bot starts reuse one notifier; no
  duplicate registration. Telegram-only startup must work.
- `telegram/wrapper.py`: remove the `telegram_jira_session_stamper` block; register the Jira session hook on the
  app notifier: `on_completed` → today's stamping logic (`set_jira_authenticated` from the event), `on_revoked` →
  `clear_jira_auth()` on the session for that Telegram id. Hooks must never create an *authenticated* session.
- Update `tests/test_jira_notifier_adapters.py` (drop Telegram adapter cases; keep Slack/Teams) and
  `tests/integration/oauth2/test_e2e_telegram_regression.py` (`test_telegram_notifier_adapter_isolated_from_callback`
  uses the real `TelegramConnectionNotifier` with a failing bot instead of a double).
- New test `test_telegram_only_startup_registers_notifier`.

**NOT in scope**: `TelegramOAuthNotifier` in `jira_commands.py` (TASK-5025 deletes it with the handlers);
combined-login dispatch (TASK-5028); Slack/Teams adapters.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | MODIFY | drop Telegram adapter |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | register + attach |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Jira hook, remove stamper |
| `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` | MODIFY | drop Telegram adapter cases |
| `tests/integration/oauth2/test_e2e_telegram_regression.py` | MODIFY | real notifier |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_notifier_startup_registration.py` | CREATE | startup test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.telegram.connection_notifier import TelegramConnectionNotifier, get_or_create_telegram_notifier  # TASK-5022
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher   # verified: manager.py:23
```

### Existing Signatures to Use
```python
# integrations/manager.py
from parrot.integrations.core.auth.notifiers import (... TelegramJiraNotifierAdapter, ...)   # :31-35
def _register_channel_notifiers(app: Any) -> ChannelNotifierRegistry:   # :134  guard app["connection_channel_notifiers_registered"] :137
    registry.register(TelegramJiraNotifierAdapter(app))                 # :139
def _connection_publisher(app: Any) -> ConnectionEventPublisher:        # :146 (calls _register_channel_notifiers)
async def _start_telegram_bot(self, name: str, config: TelegramAgentConfig):   # :331
#   app = self.bot_manager.get_app() (RuntimeError → None) :351-354 ; wrapper = TelegramAgentWrapper(agent, bot, config, app=app) :355
#   polling task created :396
# telegram/manager.py:188 — second construction path (TelegramBotManager); FILL IN: apply the same registration there if it has an app

# core/auth/notifiers.py
class _JiraAdapterBase  # :14 ; class TelegramJiraNotifierAdapter(_JiraAdapterBase)  # :38-83 ; Slack :84 ; Teams after

# telegram/wrapper.py
self._bot_id: Optional[str]                                            # :151
def _register_jira_commands(self) -> None                              # :400 ; stamper block :443-478
# TelegramUserSession.set_jira_authenticated(account_id, email, display_name, cloud_id) :139 ; clear_jira_auth() :170
```

### Does NOT Exist
- ~~`app["jira_oauth_notifier"]` assignment~~ — never assigned in production (dead lookup removed with the adapter).
- ~~`ChannelNotifierRegistry.unregister`~~ — not a method; registration replaces by channel.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py", "action": "MODIFY"},
    {"path": "tests/integration/oauth2/test_e2e_telegram_regression.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_notifier_startup_registration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#_register_channel_notifiers",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#_connection_publisher",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py#TelegramJiraNotifierAdapter",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py#TelegramAgentWrapper._register_jira_commands"
  ]
}
```

---

## Implementation Notes

- AC-10 grep: after this task and TASK-5025, `grep -rn 'TelegramJiraNotifierAdapter\|telegram_jira_session_stamper\|"jira_oauth_notifier"' packages/`
  returns nothing. The exact quoted key `"jira_oauth_notifier"` — `slack_jira_oauth_notifier` / `msteams_jira_oauth_notifier` stay.
- Jira hook stamping reads `event.account_id` / `event.display_name` and `state_payload` is not available to hooks;
  email/cloud_id: FILL IN — keep what the event carries; do not re-introduce a token read.
- Hook lookup of the session: `self._user_sessions.get(telegram_id)`; if absent, do nothing (do not create a shell
  session — the old stamper did; that could fabricate state for an unauthenticated user).

---

## Implementation Blueprint

### Steps (in order)
1. Delete the adapter class from `notifiers.py` and its import/registration in `manager.py`.
2. In `_register_channel_notifiers`, register `get_or_create_telegram_notifier(app, identity_service=<lazy IdentityMappingService(pool) or None>)`.
3. In `_start_telegram_bot`, when `app` is not None: `_connection_publisher(app)`; after the wrapper is built:
   `app["telegram_connection_notifier"].attach(wrapper._bot_id, bot)` — *why*: Telegram-only startup (AC-17).
4. In the wrapper, replace the stamper block with hook registration (when `self.app` has the notifier).
5. Update the two existing tests and add the startup test.

### `integrations/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    registry.register(TelegramJiraNotifierAdapter(app))' .../integrations/manager.py)
# REPLACE that line with:
    from parrot.integrations.telegram.connection_notifier import get_or_create_telegram_notifier

    get_or_create_telegram_notifier(app, identity_service=_identity_mapping_service(app))
# FILL IN: `_identity_mapping_service(app)` — small module helper: pool = app.get("authdb") or app.get("database");
# lazy-import IdentityMappingService; None on ImportError/no pool (pattern: the IdentityPrincipalResolver helper above :120-131)

# occurrences: 1 (verified: grep -c '        wrapper = TelegramAgentWrapper(agent, bot, config, app=app)' .../integrations/manager.py)
# AFTER that line:
        if app is not None:
            _connection_publisher(app)
            notifier = app.get("telegram_connection_notifier")
            if notifier is not None and wrapper._bot_id:
                notifier.attach(wrapper._bot_id, bot)
```

### `telegram/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if self.app is not None and "telegram_jira_session_stamper" not in self.app:' .../telegram/wrapper.py)
# REPLACE the whole stamper block (:443-478, from the comment "# Expose a stamper ..." through
# `self.app["telegram_jira_session_stamper"] = _stamp`) with a call:
        self._register_jira_session_hook()

# new method on TelegramAgentWrapper:
    def _register_jira_session_hook(self) -> None:
        """Keep the ``<jira>`` prompt block in sync through the generic notifier (FEAT-776 M7)."""
        notifier = self.app.get("telegram_connection_notifier") if self.app is not None else None
        if notifier is None:
            return
        # FILL IN: on_completed(tg_id, event) → session.set_jira_authenticated(account_id=event.account_id,
        # display_name=event.display_name, ...) when the session exists; on_revoked(tg_id, event) → session.clear_jira_auth()
        notifier.register_session_hook("jira", on_completed=..., on_revoked=...)
```
**Why**: TASK-5025 later moves this call out of `_register_jira_commands` into `_register_connection_commands`;
keep it a separate method so that move is one line.

### `tests/integrations/telegram/test_notifier_startup_registration.py` (CREATE)
```python
"""FEAT-776 AC-17: Telegram-only startup registers the generic notifier once."""
import pytest

@pytest.mark.asyncio
async def test_telegram_only_startup_registers_notifier() -> None: ...
# FILL IN: dict app; call _register_channel_notifiers twice (+ simulate two bot starts via attach);
# ChannelNotifierRegistry().get("telegram") is the single TelegramConnectionNotifier; app key set once
```

### FILL IN checklist
- [ ] `_identity_mapping_service` helper
- [ ] Jira hook bodies
- [ ] `telegram/manager.py:188` path: decide (document in Completion Note) whether it has an app to register against
- [ ] Updated tests: Telegram adapter cases removed from `test_jira_notifier_adapters.py`; regression test uses the real notifier

---

## Acceptance Criteria

- [ ] AC-10 (adapter + stamper key gone), AC-11 (hook keeps `<jira>` block), AC-17 (Telegram-only registration once)
- [ ] Slack/Teams adapter tests still pass; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_notifier_startup_registration.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py -q`
- `pytest tests/integration/oauth2/test_e2e_telegram_regression.py -q`

---

## Test Specification

Blueprint test file; `test_telegram_only_startup_registers_notifier` fixed by spec §4.

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5022 and TASK-5020 are `done`; re-anchor `manager.py` against `origin/dev` (FEAT-775 may have edited it)
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src:packages/ai-parrot-server/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5023 connections-telegram verified`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
