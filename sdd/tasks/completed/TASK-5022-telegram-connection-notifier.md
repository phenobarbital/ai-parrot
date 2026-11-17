# TASK-5022: `TelegramConnectionNotifier` (generic Telegram `ChannelNotifier` + session hooks)

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Notifier", §3 Module 7, AC-10/11. FEAT-773's `TelegramJiraNotifierAdapter` only handles Jira and only
`completed`. This task builds the replacement as a standalone module: one notifier per aiohttp app, delivering
`connection.completed` / `connection.revoked` / `connection.refresh_failed` for any provider through the bot
that issued the flow, plus per-provider session hooks. Wiring (registry, startup, removal of the old adapter and
app keys) is TASK-5023; correlated combined-login dispatch is TASK-5028.

---

## Scope

- Create `telegram/connection_notifier.py` with `SessionHook`, `TelegramConnectionNotifier`,
  `get_or_create_telegram_notifier(app)`.
- Target resolution: `state_payload["extra"]["chat_id"]` + `["bot_id"]` when present; else the Telegram id from the
  principal's `telegram` identity row (`identity_service.get_identity(event.user_id, "telegram")` →
  `provider_user_id`; private chat id == user id), sent through the bot recorded by the latest `/connect` for that
  principal (`record_connect_bot(user_id, bot_id)`), else the only attached bot, else warning + no send.
- Texts: completed → "<Provider> connected as <display_name>."; revoked → "<Provider> disconnected.";
  refresh_failed → "<Provider> access expired — /connect <id> to reconnect.". `parse_mode=None`.
- Session hooks: `on_completed` for completed; `on_revoked` for revoked and refresh_failed.
- Log every failure; never raise; idempotent on duplicate events (same kind+provider+user+occurred_at → one send).
- Tests `test_notifier_targets_state_chat_then_identity_row`, `test_notifier_texts_per_kind_plain_text`,
  `test_notifier_never_raises`, `test_jira_session_hook_stamps_and_clears` (hook called with the right args — the
  real Jira hook lives in the wrapper, TASK-5023).

**NOT in scope**: registering in `ChannelNotifierRegistry` from startup, removing the old adapter (TASK-5023);
`extra_state.combined` handling (TASK-5028).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py` | CREATE | notifier |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_notifier.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.events import ChannelNotifier, ChannelNotifierRegistry, ConnectionEvent   # verified: oauth2/events.py:33, :41, :17
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                                    # verified: registry.py:69
```

### Existing Signatures to Use
```python
# oauth2/events.py
class ConnectionEvent(BaseModel):   # :17
    kind: ConnectionEventKind; user_id: str; canonical_identity: Optional[str]; tenant_id: Optional[str]
    provider: str; account_id: str = ""; display_name: str = ""; channel: str; occurred_at: float; reason: Optional[str]
class ChannelNotifier(Protocol):    # :33  channel: str ; async def notify(self, event, state_payload: Dict[str, Any]) -> None
class ChannelNotifierRegistry:      # :41  singleton; register(notifier) :57 ; get(channel) :61 ; _reset() :54

# IdentityMappingService (ai-parrot-server, injected, duck-typed):
async def get_identity(self, nav_user_id: str, auth_provider: str) -> Optional[Dict[str, Any]]    # identity_mapping.py:270
#   dict keys include provider_user_id, auth_data, display_name, email (_GET_SQL :75)

# Current state_payload shape used by FEAT-773 adapters (core/auth/notifiers.py:23-30):
#   state_payload["extra"] → dict ; state_payload["connection_meta"]["site_url"/"cloud_id"]
```
aiogram `Bot.send_message(chat_id, text, parse_mode=None, ...)`.

### Does NOT Exist
- ~~`TelegramConnectionNotifier`, `get_or_create_telegram_notifier`, `app["telegram_connection_notifier"]`~~ — created here.
- ~~`IdentityMappingService.find_by_provider_user_id`~~ — not a method; use `get_identity(nav_user_id, "telegram")`.
- ~~`ConnectionEvent.chat_id`~~ — delivery data only travels in `state_payload["extra"]`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_notifier.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_notifier.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEvent",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ChannelNotifierRegistry",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#OAuth2ProviderRegistry"
  ]
}
```

---

## Implementation Notes

- Provider display name: `OAuth2ProviderRegistry().get(event.provider).display_name`, fallback `event.provider`.
- Never put token material in text; `event.display_name` is the account display name.
- `get_or_create_telegram_notifier` is idempotent: returns `app["telegram_connection_notifier"]` when present;
  on first creation registers in `ChannelNotifierRegistry()` (replaces whatever "telegram" entry exists).
- `identity_service` is optional; when absent and no state chat → warning, no send.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module skeleton below — *why*: §3 M7 skeleton.
2. Fill target resolution and text per kind — *why*: AC-10.
3. Tests with the spec's `fake_bot` and `fake_identity_service` fixtures.

### `telegram/connection_notifier.py` (CREATE)
```python
"""Generic Telegram ChannelNotifier for connection events (FEAT-776 M7)."""
from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, MutableMapping, Optional, Tuple

from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEvent
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry

if TYPE_CHECKING:  # pragma: no cover
    from aiogram import Bot

SessionHook = Callable[[int, ConnectionEvent], "Awaitable[None] | None"]
_APP_KEY = "telegram_connection_notifier"


class TelegramConnectionNotifier:
    """Deliver connection events to Telegram chats; log failures, never raise."""

    channel: str = "telegram"

    def __init__(self, *, identity_service: Optional[Any] = None) -> None:
        self._identity_service = identity_service
        self._bots: Dict[str, "Bot"] = {}
        self._last_connect_bot: Dict[str, str] = {}      # principal user_id → bot_id
        self._hooks: Dict[str, Tuple[Optional[SessionHook], Optional[SessionHook]]] = {}
        self._seen: set = set()
        self.logger = logging.getLogger(__name__)

    def attach(self, bot_id: str, bot: "Bot") -> None:
        """Make ``bot`` available for deliveries recorded with ``bot_id``."""
        self._bots[str(bot_id)] = bot

    def record_connect_bot(self, user_id: str, bot_id: str) -> None:
        """Remember the bot of the latest /connect for a principal (revoke/refresh fallback)."""
        self._last_connect_bot[str(user_id)] = str(bot_id)

    def register_session_hook(self, provider_id: str, *, on_completed: Optional[SessionHook] = None,
                              on_revoked: Optional[SessionHook] = None) -> None:
        """Register provider-specific session effects (e.g. the Jira ``<jira>`` block)."""
        self._hooks[provider_id] = (on_completed, on_revoked)

    async def _resolve_target(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> Optional[Tuple[int, "Bot"]]:
        # FILL IN: state extra chat_id/bot_id → identity row → last /connect bot → only bot → None (warn) — spec §2 order
        raise NotImplementedError

    def _text(self, event: ConnectionEvent) -> Optional[str]:
        # FILL IN: three fixed texts; unknown kind → None
        raise NotImplementedError

    async def _run_hook(self, telegram_id: int, event: ConnectionEvent) -> None:
        # FILL IN: pick on_completed / on_revoked; await when awaitable; log exceptions
        raise NotImplementedError

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Resolve target, send plain text, run the session hook. Never raises."""
        try:
            # FILL IN: dedupe key; target; bot.send_message(chat_id, text, parse_mode=None); hook(telegram_id, event)
            raise NotImplementedError
        except Exception:  # noqa: BLE001 - notifier contract: log, never raise
            self.logger.exception("Telegram connection notification failed (provider=%s kind=%s)", event.provider, event.kind)


def get_or_create_telegram_notifier(app: MutableMapping[str, Any], *, identity_service: Optional[Any] = None
                                    ) -> TelegramConnectionNotifier:
    """Return ``app["telegram_connection_notifier"]``; create and register it once."""
    notifier = app.get(_APP_KEY)
    if notifier is None:
        notifier = TelegramConnectionNotifier(identity_service=identity_service)
        app[_APP_KEY] = notifier
        ChannelNotifierRegistry().register(notifier)
    return notifier
```
**Why this shape**: `record_connect_bot` and the `identity_service` keyword on the factory are the minimal
additions needed to implement the spec's fallback order; keep every other signature as in §3 M7.

### `tests/integrations/telegram/test_connection_notifier.py` (CREATE)
```python
"""FEAT-776 M7 notifier tests."""
import pytest

@pytest.mark.asyncio
async def test_notifier_targets_state_chat_then_identity_row() -> None: ...
@pytest.mark.asyncio
async def test_notifier_texts_per_kind_plain_text() -> None: ...
@pytest.mark.asyncio
async def test_notifier_never_raises() -> None: ...
@pytest.mark.asyncio
async def test_jira_session_hook_stamps_and_clears() -> None: ...   # FILL IN: fake hooks receive (telegram_id, event) per kind
```

### FILL IN checklist
- [ ] Every `NotImplementedError` body
- [ ] `ChannelNotifierRegistry._reset()` in test teardown
- [ ] Four test bodies (plus a duplicate-event test)

---

## Acceptance Criteria

- [ ] AC-10 texts/plain text/never-raise for any provider; hooks run per kind
- [ ] `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_notifier.py -q`

---

## Test Specification

Blueprint test file; names fixed by spec §4 (M7 rows).

---

## Agent Instructions

1. Work in the feature worktree; verify the Codebase Contract
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5022 connections-telegram verified`

---

## Completion Note

**Completed by**: gpt-5.6-sol (codex), commit on branch TASK-5022-a1
**Date**: 2026-10-31
**Notes**: Merge-tier run: this task's tests passed; the only failures are the 12 pre-existing reds in other Telegram test files, which fail identically on unmodified dev. The engine labels the run 'failed', so finalize_task was not used. Review coder-review:6e6d2de285c7e4f9321656fa. Deferred minor: dedupe set unbounded (issue:9f3df2dc4871).

**Deviations from spec**: none
