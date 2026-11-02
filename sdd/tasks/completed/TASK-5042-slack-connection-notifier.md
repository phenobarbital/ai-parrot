# TASK-5042: Provider-agnostic `SlackConnectionNotifier` replaces `SlackJiraNotifierAdapter`

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 2 and AC-6: completion, revocation and refresh failure must be DMed on Slack **for any provider**.
S-1 registered `SlackJiraNotifierAdapter` (Jira only) in the process-wide `ChannelNotifierRegistry`
(`integrations/manager.py:140`). That adapter also **writes a `slack` identity row with the bare
`slack_user_id`** whenever the OAuth state carries a `nav_user_id` (`core/auth/notifiers.py:97-112`) — an
un-locked Slack identity writer that the spec's exclusive-ownership contract forbids ("every in-tree Slack writer
must use the claim operation"). The new notifier therefore only notifies; Slack identity rows are created solely
by the link confirm route (TASK-5041 via TASK-5036).

`ChannelNotifierRegistry` is a singleton that keeps one notifier per channel (`register` replaces —
events.py:41-60). The notifier needs a bot token, which only the Slack wrapper has, so the wrapper registers it.

---

## Scope

- Create `packages/ai-parrot-integrations/src/parrot/integrations/slack/notifier.py` with
  `class SlackConnectionNotifier` (`channel = "slack"`; `__init__(self, bot_token: str)`;
  `async notify(event, state_payload)`) that DMs `extra.slack_user_id` for `connection.completed`,
  `connection.revoked`, `connection.refresh_failed`, any provider, using the provider's `display_name` from
  `OAuth2ProviderRegistry`. DM failures are logged, never raised past `notify` (the publisher also isolates).
- `slack/wrapper.py`: when `config.bot_token` is set, `ChannelNotifierRegistry().register(SlackConnectionNotifier(bot_token=config.bot_token))` — independent of `oauth_manager`.
- `integrations/manager.py`: stop importing/registering `SlackJiraNotifierAdapter` (keep Telegram + MS Teams).
- `core/auth/notifiers.py`: delete `SlackJiraNotifierAdapter` (and nothing else).
- Update `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` (remove the Slack-adapter cases) and add
  `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_notifier.py`.

**NOT in scope**: Telegram/MS Teams adapters (S-2/S-3b own them); Slack commands (TASK-5044); the dead
`handle_slack_jira_callback` (TASK-5043); keeping `app["slack_jira_oauth_notifier"]` — leave its wrapper line as is
(TASK-5044 / the callback still read it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/notifier.py` | CREATE | `SlackConnectionNotifier` |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | register the notifier |
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | drop Slack adapter registration |
| `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` | MODIFY | delete `SlackJiraNotifierAdapter` |
| `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` | MODIFY | drop Slack-adapter cases |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_notifier.py` | CREATE | notifier tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEvent   # verified: auth/oauth2/events.py:41, :17
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                     # verified: oauth2/registry.py:69
from slack_sdk.web.async_client import AsyncWebClient                              # verified pattern: slack/oauth_callback.py:86 (lazy import inside __init__)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/events.py
class ConnectionEvent(BaseModel):   # :17 — kind, user_id, canonical_identity, tenant_id, provider, account_id,
                                    #       display_name, channel, occurred_at, reason
class ChannelNotifier(Protocol):    # :33 — channel: str; async notify(event, state_payload) -> None
class ChannelNotifierRegistry:      # :41 — singleton (__new__); register(notifier) replaces by notifier.channel (:58-60)

# packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py
class _JiraAdapterBase:             # :14 — _extra(state_payload) → dict(state_payload.get("extra") or {}) (:24-26)
class SlackJiraNotifierAdapter(_JiraAdapterBase):   # :84-136 — DELETE (incl. its identity write :97-112)
class MSTeamsJiraNotifierAdapter(_JiraAdapterBase): # :139 (anchor for the deletion's end; keep)

# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
from parrot.integrations.core.auth.notifiers import (   # :31
    MSTeamsJiraNotifierAdapter,
    SlackJiraNotifierAdapter,                          # :33 (delete)
    TelegramJiraNotifierAdapter,
)
def _register_channel_notifiers(app) -> ChannelNotifierRegistry:   # :134
    registry.register(SlackJiraNotifierAdapter(app))                # :140 (delete)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
        self._command_router = SlackCommandRouter()                 # :125 (anchor)
        if oauth_manager is not None:                               # :127
            register_jira_commands(self._command_router, oauth_manager)  # :128
            if config.bot_token:
                app["slack_jira_oauth_notifier"] = SlackOAuthNotifier(bot_token=config.bot_token)  # :132

# packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py — DM idiom to copy
class SlackOAuthNotifier:            # :74; __init__ lazy AsyncWebClient (:84-95); chat_postMessage(channel=slack_user_id, text=...) (:113-125)

# OAuth2ProviderRegistry().get(provider_id) → provider with .display_name (used in oauth2/service.py:150-151)
```

### Does NOT Exist
- ~~`parrot.integrations.slack.notifier`~~ — created by this task.
- ~~A Slack notifier for non-Jira providers~~ — `SlackJiraNotifierAdapter.notify` returns early unless `event.provider == "jira"` (:88-89).
- ~~`state_payload["extra"]["nav_user_id"]` on Slack~~ — Slack never sends one; do not read it.
- ~~Identity writes in the new notifier~~ — forbidden (exclusive ownership, spec M2).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/notifier.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_notifier.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ChannelNotifierRegistry",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEvent",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py#SlackJiraNotifierAdapter",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/manager.py#_register_channel_notifiers",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py#SlackOAuthNotifier"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Shared with S-3b (MS Teams) and S-2 (Telegram)**: `integrations/manager.py` and `core/auth/notifiers.py` are edited
  by their specs too. Re-read both files from `origin/dev` before editing and touch only the Slack lines.
- Register the notifier **in the wrapper** because the token lives there; the registry is a singleton so any wrapper
  instance registering it wins. With several Slack bots, the last registered token is used — note this in the module
  docstring (v1 limitation).
- Messages: never include tokens, nonces or account secrets; `event.display_name` (connected account name) is fine.

### References in Codebase
- `slack/oauth_callback.py:74-150` — DM client and exception handling.

---

## Implementation Blueprint

### Steps (in order)
1. Create `slack/notifier.py` — *why*: one notifier for every provider (AC-6).
2. Register it in `wrapper.py` after the command router is built — *why*: the bot token is only known there.
3. Remove the adapter import + registration from `integrations/manager.py`, then delete the class — *why*: it is an un-locked Slack identity writer (spec M2) and Jira-only.
4. Update the adapter tests, add the new tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/notifier.py` (CREATE)
```python
"""Provider-agnostic Slack connection notifier (FEAT-777 M2, AC-6).

Registered in the process-wide ``ChannelNotifierRegistry`` by ``SlackAgentWrapper``. One notifier per
channel: with several Slack bots the last registered token wins (v1 limitation). Never writes identities.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from parrot.auth.oauth2.events import ConnectionEvent

logger = logging.getLogger(__name__)


class SlackConnectionNotifier:
    """DM a Slack user about connection lifecycle events for any provider."""

    channel = "slack"

    def __init__(self, bot_token: str) -> None:
        from slack_sdk.web.async_client import AsyncWebClient  # lazy, as SlackOAuthNotifier

        self._client = AsyncWebClient(token=bot_token)
        self.logger = logger

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Send the DM for ``completed`` / ``revoked`` / ``refresh_failed``; other kinds are ignored."""
        extra = dict(state_payload.get("extra") or {})
        slack_user_id = str(extra.get("slack_user_id") or state_payload.get("slack_user_id") or "")
        if not slack_user_id:
            self.logger.info("Skipping Slack connection notification without slack_user_id")
            return
        text = self._message(event, self._display_name(event.provider))
        if text is None:
            return
        try:
            await self._client.chat_postMessage(channel=slack_user_id, text=text)
        except Exception:  # noqa: BLE001 — DM failure must never break completion
            self.logger.exception("Failed to DM Slack user for %s %s", event.provider, event.kind)

    @staticmethod
    def _display_name(provider_id: str) -> str:
        from parrot.auth.oauth2.registry import OAuth2ProviderRegistry

        provider = OAuth2ProviderRegistry().get(provider_id)
        return getattr(provider, "display_name", None) or provider_id

    @staticmethod
    def _message(event: ConnectionEvent, name: str) -> Any:
        # FILL IN: completed → f"{name} connected as *{event.display_name}*."; revoked → f"{name} was disconnected.";
        # refresh_failed → f"{name} needs to be reconnected: use `/connect {event.provider}`." (append event.reason when set);
        # anything else → None — bounded by AC-6 and "no token material"
        raise NotImplementedError
```
**Why this shape**: spec skeleton fixes `channel`, `__init__(bot_token)` and `notify(event, state_payload)`.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self._command_router = SlackCommandRouter()' wrapper.py)
# AFTER — insert below `        self._command_router = SlackCommandRouter()` (verified: wrapper.py:125)
        if config.bot_token:
            from parrot.auth.oauth2.events import ChannelNotifierRegistry
            from .notifier import SlackConnectionNotifier

            ChannelNotifierRegistry().register(SlackConnectionNotifier(bot_token=config.bot_token))
```
**Why**: registration must not depend on a Jira `oauth_manager` — the notifier covers every provider.

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    SlackJiraNotifierAdapter,' manager.py) — DELETE line :33
# occurrences: 1 (verified: grep -c '    registry.register(SlackJiraNotifierAdapter(app))' manager.py) — DELETE line :140
# Update the docstring of _register_channel_notifiers (:135): "Register the Telegram and MS Teams Jira adapters;
# Slack registers SlackConnectionNotifier from SlackAgentWrapper."
```

### `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/notifiers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class SlackJiraNotifierAdapter(_JiraAdapterBase):' notifiers.py)
# DELETE from `class SlackJiraNotifierAdapter(_JiraAdapterBase):` (:84) up to, not including,
# `class MSTeamsJiraNotifierAdapter(_JiraAdapterBase):` (:139; occurrences: 1). Keep two blank lines between classes.
```

### `packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py` (MODIFY)
```python
# Remove SlackJiraNotifierAdapter from the import (:10) and the Slack blocks in
# test_notifier_adapters_delegate (:64), test_notifier_adapters_failure_and_non_jira_are_safe (:104)
# and test_identity_guards_are_preserved (:135). FILL IN: keep every Telegram/MS Teams assertion intact —
# bounded by "touch only the Slack lines"
```

### `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_notifier.py` (CREATE)
```python
"""SlackConnectionNotifier (FEAT-777 AC-6)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.integrations.slack.notifier import SlackConnectionNotifier


def _event(kind: str, provider: str) -> ConnectionEvent:
    return ConnectionEvent(kind=kind, user_id="1042", provider=provider, display_name="Jesus",
                           channel="slack", occurred_at=time.time())


@pytest.fixture
def notifier() -> SlackConnectionNotifier:
    n = SlackConnectionNotifier(bot_token="xoxb-test")
    n._client = AsyncMock()
    return n


@pytest.mark.parametrize("provider", ["jira", "o365"])
@pytest.mark.parametrize("kind", ["connection.completed", "connection.revoked", "connection.refresh_failed"])
async def test_dm_any_provider(notifier: SlackConnectionNotifier, kind: str, provider: str) -> None:
    await notifier.notify(_event(kind, provider), {"extra": {"slack_user_id": "U02", "team_id": "T01"}})
    notifier._client.chat_postMessage.assert_awaited_once()
    assert notifier._client.chat_postMessage.await_args.kwargs["channel"] == "U02"


async def test_no_slack_user_is_noop(notifier: SlackConnectionNotifier) -> None:
    # FILL IN: empty extra → chat_postMessage not awaited
    ...


async def test_dm_failure_is_swallowed(notifier: SlackConnectionNotifier) -> None:
    # FILL IN: chat_postMessage raising → notify returns normally
    ...


async def test_never_writes_identity(notifier: SlackConnectionNotifier) -> None:
    # FILL IN: the notifier has no app / identity service reference at all (no attribute _app) — bounded by spec M2
    ...
```
Check `ConnectionEvent`'s exact `kind` literal values before writing (`ConnectionEventKind` in events.py) and
use them verbatim.

### FILL IN checklist
- [ ] `SlackConnectionNotifier._message` — per-kind texts; AC-6.
- [ ] Adapter test file — Slack lines removed only.
- [ ] Three stub tests in the new test file.

---

## Acceptance Criteria

- [ ] Completed / revoked / refresh_failed DMs are sent for `jira` and `o365` (AC-6).
- [ ] `SlackJiraNotifierAdapter` no longer exists in `packages/`; `grep -rn SlackJiraNotifierAdapter packages/` is empty.
- [ ] No Slack identity write remains in `core/auth/notifiers.py`.
- [ ] Telegram and MS Teams adapter tests still pass.
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_notifier.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_jira_notifier_adapters.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py -q`

---

## Test Specification

See the CREATE block for `test_slack_connection_notifier.py` above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (Module 2; AC-6)
3. **Check dependencies** in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** — re-read `integrations/manager.py` and `core/auth/notifiers.py` from `origin/dev` first (S-2/S-3b edit them)
5. **Update status** → `"in-progress"`; commit only the index
6. **Implement** from the blueprint
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit** only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-5042 connections-web-slack verified`
10. **Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
