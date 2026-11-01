# TASK-5024: Telegram generic connection handlers (`connection_commands.py`) + `connection_providers` config

**Feature**: FEAT-776 — Connections on Telegram
**Spec**: `sdd/specs/connections-telegram.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5021
**Assigned-to**: unassigned

---

## Context

Spec §2 "Telegram commands", §3 Module 6 (new module half), AC-4/6. This task creates the Telegram handlers for
`/connect [<provider>]`, `/disconnect <provider>`, `/connections` and the `conn:<provider_id>` inline-picker
callback, as a standalone module driven by injected callables, plus the `connection_providers` allowlist on
`TelegramAgentConfig`. Wiring them into the wrapper and turning the Jira/Office365 commands into aliases is
TASK-5025.

---

## Scope

- Create `telegram/connection_commands.py` with `PrincipalSource`, `ContextSource`, `ExtraStateFactory`,
  `connect_handler`, `disconnect_handler`, `connections_handler`, `render_connect_outcome`,
  `register_connection_commands`.
- Every handler: private chat only ("Please use a private chat with the bot to manage connections."); principal or
  "Please /login first to link your Telegram account." with **no** service call and no OAuth state; then
  `ConnectionCommandService`; reply with `parse_mode=None`.
- `/connect` without argument → inline keyboard of `connectable_providers()` with `callback_data="conn:<id>"`.
- `render_connect_outcome`: `auth_url` → inline URL button "Connect <Provider>"; `denied` → "Connecting <Provider> is not
  allowed for your account."; other kinds → their plain message.
- `TelegramAgentConfig.connection_providers: Optional[List[str]] = None`, read by `from_dict`.
- Tests: `test_connect_requires_private_chat`, `test_connect_without_principal_creates_no_state`,
  `test_connect_picker_and_callback`, `test_extra_state_carries_chat_and_bot`.

**NOT in scope**: wrapper registration, aliases, command menu (TASK-5025); needs-auth prompts (TASK-5026).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py` | CREATE | handlers |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | `connection_providers` |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_commands.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiogram import F, Router                                                     # verified: Router at jira_commands.py:20
from aiogram.filters import Command, CommandObject                               # verified: Command at jira_commands.py:21
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message   # verified: jira_commands.py:22 (+CallbackQuery: aiogram.types)
from parrot.auth.principal import Principal                                      # verified: principal.py:18
from parrot.auth.permission import PermissionContext                             # verified: permission.py:81
from parrot.integrations.core.auth.connections import (ConnectionCommandService, ConnectOutcome,
                                                       ConnectionStatusLine)      # TASK-5021
```

### Existing Signatures to Use
```python
# telegram/models.py
@dataclass class TelegramAgentConfig:                                             # :42
    post_auth_actions: List[PostAuthAction] = field(default_factory=list)         # :111
    @classmethod def from_dict(cls, name: str, data: Dict[str, Any]) -> "TelegramAgentConfig"   # :235
#   ...  suggestion_button_ttl_s=int(data.get("suggestion_button_ttl_s", 86400)),   # :306 (inside cls(...) call)

# Pattern for a plain-text reply with a URL button (jira_commands.py:45-50, :95-99):
#   InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=..., url=url)]]) ; message.reply(..., parse_mode=None)
```
`message.chat.type` is `"private"` for private chats (aiogram `ChatType`).

### Does NOT Exist
- ~~`Command("connect")`, `Command("disconnect")`, `Command("connections")` under `integrations/telegram/`~~ — created here.
- ~~`TelegramAgentConfig.connection_providers`~~ — created here.
- ~~Scopes in command arguments~~ — the only user input is the provider name.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/connection_commands.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_commands.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig.from_dict"
  ]
}
```

---

## Implementation Notes

- The spec skeleton passes a `principal_source`; every service call also needs a fresh `PermissionContext` built from
  the principal and validated session claims (spec M6 comment). Add a `context_source: ContextSource` keyword
  (`Callable[[Message | CallbackQuery, Principal], PermissionContext]`) next to `principal_source` on every handler and on
  `register_connection_commands` — the wrapper supplies `_connection_permission_context` (TASK-5020). This is the only
  signature addition to the spec skeleton; record it in the Completion Note.
- `extra_state_factory` returns exactly `{"chat_id": <chat id>, "bot_id": <issuing bot id>}`.
- `on_connect_started: Optional[Callable[[str, str], None]]` is NOT needed: the wrapper records the issuing bot via
  `extra_state` only. Keep the skeleton's `on_disconnected` callback (wrapper clears Jira session on disconnect).
- Callback handler must `await callback.answer()` and reply to `callback.message`; private-chat rule applies to the
  callback's chat too.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module from the block below — *why*: §3 M6 skeleton plus `context_source`.
2. Fill guards, picker, rendering — *why*: AC-4/AC-6.
3. Add the config field and `from_dict` key; write tests with fake `ConnectionCommandService`.

### `telegram/connection_commands.py` (CREATE)
```python
"""Generic Telegram connection commands: /connect, /disconnect, /connections (FEAT-776 M6)."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal
from parrot.integrations.core.auth.connections import ConnectionCommandService, ConnectOutcome

logger = logging.getLogger(__name__)

Update = Union[Message, CallbackQuery]
PrincipalSource = Callable[[Update], Awaitable[Optional[Principal]]]
ContextSource = Callable[[Update, Principal], PermissionContext]
ExtraStateFactory = Callable[[Update], Dict[str, Any]]

PRIVATE_ONLY = "Please use a private chat with the bot to manage connections."
LOGIN_FIRST = "Please /login first to link your Telegram account."
CALLBACK_PREFIX = "conn:"


def render_connect_outcome(outcome: ConnectOutcome) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    """Plain text (+ optional URL button) for an outcome."""
    # FILL IN: auth_url → ("Click below to connect <name>.", keyboard[[Button(text=f"Connect {name}", url=...)]]);
    # denied → fixed text; needs_login → LOGIN_FIRST; others → outcome.message or a short default
    raise NotImplementedError


async def connect_handler(message: Message, provider_arg: str, *, commands: ConnectionCommandService,
                          principal_source: PrincipalSource, context_source: ContextSource,
                          extra_state_factory: ExtraStateFactory) -> None:
    """``/connect [<provider>]`` — picker when no argument; else connect routine."""
    # FILL IN: private-chat guard → principal guard (no service call) → picker or commands.connect(...) → render
    raise NotImplementedError


async def disconnect_handler(message: Message, provider_arg: str, *, commands: ConnectionCommandService,
                             principal_source: PrincipalSource, context_source: ContextSource,
                             on_disconnected: Optional[Callable[[int, str], None]] = None) -> None:
    """``/disconnect <provider>``; calls ``on_disconnected(telegram_id, provider_id)`` on success."""
    # FILL IN
    raise NotImplementedError


async def connections_handler(message: Message, *, commands: ConnectionCommandService,
                              principal_source: PrincipalSource, context_source: ContextSource,
                              only: Optional[str] = None) -> None:
    """``/connections`` — one line per connectable provider (``only`` filters, used by /jira_status)."""
    # FILL IN
    raise NotImplementedError


def register_connection_commands(router: Router, *, commands: ConnectionCommandService,
                                 principal_source: PrincipalSource, context_source: ContextSource,
                                 extra_state_factory: ExtraStateFactory,
                                 on_disconnected: Optional[Callable[[int, str], None]] = None) -> List[Tuple[str, str]]:
    """Register /connect, /disconnect, /connections and the ``conn:`` callback; return menu entries."""
    # FILL IN: closures reading CommandObject.args; router.callback_query.register(_on_pick, F.data.startswith(CALLBACK_PREFIX))
    return [
        ("connect", "Connect an account"),
        ("disconnect", "Disconnect an account"),
        ("connections", "Show your connections"),
    ]
```
**Why this shape**: handlers are module functions with injected collaborators so aliases (TASK-5025) and
needs-auth prompts (TASK-5026) reuse them without the wrapper.

### `telegram/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    post_auth_actions: List[PostAuthAction] = field(default_factory=list)' .../telegram/models.py)
# AFTER — insert below that line (verified: models.py:111)
    # FEAT-776: optional allowlist of connectable providers for /connect (None = every connectable provider).
    connection_providers: Optional[List[str]] = None

# from_dict — occurrences: 1 (verified: grep -c '            post_auth_actions=post_auth_actions,' .../telegram/models.py)
# AFTER that keyword argument (verified: models.py:299):
            connection_providers=list(data["connection_providers"]) if data.get("connection_providers") is not None else None,
```

### `tests/integrations/telegram/test_connection_commands.py` (CREATE)
```python
"""FEAT-776 M6 handler tests."""
import pytest

@pytest.mark.asyncio
async def test_connect_requires_private_chat() -> None: ...
@pytest.mark.asyncio
async def test_connect_without_principal_creates_no_state() -> None: ...
@pytest.mark.asyncio
async def test_connect_picker_and_callback() -> None: ...
@pytest.mark.asyncio
async def test_extra_state_carries_chat_and_bot() -> None: ...
```

### FILL IN checklist
- [ ] All handler bodies and `render_connect_outcome`
- [ ] Callback route + `callback.answer()`
- [ ] Four tests (aiogram `Message`/`CallbackQuery` doubles; pattern in `tests/integrations/telegram/conftest.py`)

---

## Acceptance Criteria

- [ ] AC-4 (only connectable providers offered/accepted), AC-6 (no state without principal / outside private chat)
- [ ] Every reply built here uses `parse_mode=None`; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_connection_commands.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_config_validation_multi_auth.py -q`

---

## Test Specification

Blueprint test file; names fixed by spec §4 (M6 rows).

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5021 is `done`
2. Implement from the blueprint; validate with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5024 connections-telegram verified`

---

## Completion Note

**Completed by**: sdd-worker; coded by gpt-5.6-terra (codex), attempt 2 (attempt 1 was retried by the engine), reviewed by the worker
**Date**: 2026-11-01
**Notes**:
- `connection_commands.py`: `connect_handler`, `disconnect_handler`, `connections_handler`, `render_connect_outcome`, `register_connection_commands` (menu entries for `/connect`, `/disconnect`, `/connections`, plus the `conn:` picker callback). All replies use `parse_mode=None`; non-private chats get the fixed private-chat message; no principal -> "/login first" with no OAuth state.
- `models.py`: `TelegramAgentConfig.connection_providers` (None = all connectable providers), read by `from_dict`.
- Signature note: every handler takes a `context_source(update, principal) -> PermissionContext` argument besides the skeleton's `principal_source`, so the wrapper builds the fresh context (TASK-5025 already lists it). The picker callback reuses `connect_handler` with the clicker's own principal and context.
- Review correction: the coder also added a `login_multi.html` check to config validation to turn the baseline-red `test_multi_auth_wrong_login_page_url_errors` green. That is outside the task; removed in `88bb67b82f`. Recorded as `coder-feedback:5ebd8a475a7397d37e1a5fe5`. The test stays red exactly as on `dev`.
- Tests: 4 in `test_connection_commands.py` pass. Review `coder-review:bd1df4d9ac7f4ccd57a8ba66`, 1 correction.

**Deviations from spec**: the extra `context_source` argument (see above).
