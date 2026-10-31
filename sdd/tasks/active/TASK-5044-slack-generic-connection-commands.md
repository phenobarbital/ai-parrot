# TASK-5044: Generic Slack `/login`, `/connect`, `/disconnect`, `/connections` (+ Jira aliases)

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5034, TASK-5038, TASK-5041, TASK-5042
**Assigned-to**: unassigned

---

## Context

Spec Module 2 (G4, AC-6, AC-14). After S-1 every Slack user gets `_LINK_FIRST` and has no way to link
(`jira_commands.py:29`, `:93-99`). This task adds the Slack surface of the link flow and provider-generic
connection commands:

- `/login` → opaque one-time link from `ChannelLinkIssuer.issue("slack", "T:U", {team_id, slack_user_id})` (TASK-5034);
  the user confirms it in the logged-in admin UI (TASK-5041 / TASK-5056).
- `/connect <provider>` → `resolve_principal("slack", "T:U")`; `None` → "link first: /login" and **no OAuth state**;
  else `IntegrationsService.start_connect(..., channel="slack", principal=p, ...)` with the injected authorizer (TASK-5038/TASK-5039).
- `/disconnect <provider>`, `/connections` → `disconnect` / `list_for_principal` with `principal=p`.
- `/connect_jira`, `/disconnect_jira`, `/jira_status` stay as aliases of the generic handlers with `provider="jira"` (AC-6).

The server publishes `app["channel_link_issuer"]` and `app["connection_authorizer"]` (wired by TASK-5041). The
wrapper is built in the integrations process and must never import server code, so it reads those app keys
**lazily, at command time** (wrapper `__init__` may run before server startup hooks).

---

## Scope

- Create `slack/commands/connection_commands.py` with the handlers and
  `register_connection_commands(router, *, link_issuer, service_factory) -> None` (spec signature, fixed).
- `link_issuer` may be any object with `async issue(...)`; the wrapper passes `AppLinkIssuer(app)`, a tiny proxy
  (in the same module) that resolves `app["channel_link_issuer"]` per call and raises `LookupError` when absent.
- `slack/wrapper.py`: always call `register_connection_commands(self._command_router, link_issuer=AppLinkIssuer(app),
  service_factory=lambda: IntegrationsService(authorizer=app.get("connection_authorizer")))`; stop calling
  `register_jira_commands` (the aliases now come from `register_connection_commands`). Keep the
  `app["slack_jira_oauth_notifier"]` registration as it is.
- Tests for the handlers; update `test_slack_wrapper_jira.py` (aliases are now always registered).

**NOT in scope**: the confirm route (TASK-5041); the notifier (TASK-5042); `jira_commands.py` — left unchanged so its
public functions keep working for existing importers (spec AC-6 only requires the aliases to keep working;
record this in the Completion Note); help text beyond adding the new commands to `_help_text` if one lists them.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/connection_commands.py` | CREATE | handlers, `AppLinkIssuer`, `register_connection_commands` |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` | MODIFY | register generic commands |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_commands.py` | CREATE | handler tests |
| `packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py` | MODIFY | alias expectations |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.principal import Principal, resolve_principal          # verified: auth/principal.py:18, :73
from parrot.auth.oauth2.service import IntegrationsService               # verified: auth/oauth2/service.py:65
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry           # verified: auth/oauth2/registry.py:69 (.all(), .get(id))
from parrot.auth.channel_link import ChannelLinkIssuer                   # created by TASK-5034 (TYPE_CHECKING import only)
from parrot.integrations.slack.commands import SlackCommandRouter        # verified: slack/commands/__init__.py:27 (TYPE_CHECKING)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py
class SlackCommandRouter:                                       # :27
    def register(self, command: str, handler: Callable) -> None  # :50 — strips "/", overwrites with a warning
    async def dispatch(self, command, payload) -> Optional[dict] # :68 — handler errors → generic ephemeral error
    registered_commands: list[str]                               # :97 (property)

# packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py
from .commands.jira_commands import register_jira_commands       # :17 (anchor; remove if unused afterwards)
        self._command_router = SlackCommandRouter()              # :125 (anchor; TASK-5042 inserts its notifier block right below)
        if oauth_manager is not None:                            # :127
            register_jira_commands(self._command_router, oauth_manager)   # :128 (anchor — delete this line only)
            if config.bot_token: app["slack_jira_oauth_notifier"] = SlackOAuthNotifier(bot_token=config.bot_token)  # :131-132 (keep)
    async def _handle_command(self, request) -> web.Response:   # :360 — builds command_payload {team_id, user_id,
        # channel_id, text, response_url} (:390-397); command_word = data["command"].lstrip("/") or first word of text (:401-402)
        # → router.dispatch(command_word, payload); for "/connect jira" Slack sends command="/connect", text="jira"

# packages/ai-parrot/src/parrot/auth/oauth2/service.py (after TASK-5038)
IntegrationsService(vault_token_sync=None, *, authorizer=None)
async start_connect(user_id, provider_id, return_origin=None, *, channel, principal, scopes=None, request=None,
                    extra_state=None) -> ConnectInitResponse    # :288 — PermissionError on deny; ValueError unknown provider
async list_for_principal(user_id, request=None, *, principal=None) -> List[IntegrationDescriptor]   # :81
async status(user_id, provider_id, request=None, *, principal=None) -> IntegrationDescriptor          # :360
async disconnect(user_id, provider_id, request=None, *, principal=None) -> DisconnectResponse         # :371
# ConnectInitResponse.auth_url (models.py:90); IntegrationDescriptor.provider/display_name/status/display_account_name (models.py:39-52)

# packages/ai-parrot/src/parrot/auth/channel_link.py (after TASK-5034)
ChannelLinkIssuer.issue(channel, channel_user_id, extra=None) -> str   # ValueError when base_url empty (D5)

# Existing Slack id convention (jira_commands.py:95, :142, :180): user_id = f"{team_id}:{slack_user_id}"
# Existing Slack button shape to reuse: jira_commands._build_connect_button(url) (:46-73) — copy the Block Kit layout, don't import the private helper
```

### Does NOT Exist
- ~~`parrot.integrations.slack.commands.connection_commands`~~, ~~`AppLinkIssuer`~~, ~~`register_connection_commands`~~ — created here.
- ~~A Slack login/session `nav_user_id`~~ — none under `integrations/slack/`; the principal comes only from `resolve_principal`.
- ~~`users.info` e-mail auto-link~~ — rejected (D2); never look up the Slack e-mail.
- ~~Server imports from integrations~~ — never `import parrot.services...` / `parrot.handlers...` here.
- ~~`IntegrationsService(request=...)` for Slack~~ — there is no HTTP request; never fabricate one (AC-14).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/connection_commands.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_commands.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/commands/__init__.py#SlackCommandRouter",
    "sym:packages/ai-parrot/src/parrot/auth/principal.py#resolve_principal",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#OAuth2ProviderRegistry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Fail closed** (spec M2, AC-14): unlinked → `/login` instruction and no `start_connect` call; `PermissionError` →
  "not permitted", nothing else disclosed; unknown provider → list of registered ids (`OAuth2ProviderRegistry().all()`).
- `/login` when already linked → "already linked to the platform"; when `issue` raises `ValueError` / `LookupError`
  → "Account linking is not configured." (D5) and a warning log. Never log the nonce or the URL.
- **Delivery of the link**: answer with a Slack *ephemeral* response (visible only to the invoking user), which is the
  same privacy as a DM and needs no extra token plumbing. Record this as the delivery mechanism in the Completion
  Note (spec text says "DMs"; flag it if a reviewer requires `chat.postMessage`).
- Provider argument: `text` is the provider for `command="/connect"`; when the command arrives as text
  (`"connect jira"`), drop the first word. Lower-case and strip it.
- All responses `{"response_type": "ephemeral", ...}`.

### References in Codebase
- `slack/commands/jira_commands.py:41-200` — handler style, ephemeral shapes, `_principal` helper.

---

## Implementation Blueprint

### Steps (in order)
1. Create `connection_commands.py` (helpers → handlers → `AppLinkIssuer` → `register_connection_commands`) — *why*: one module owns every Slack connection command.
2. Wire it in `wrapper.py` and drop the `register_jira_commands` call — *why*: aliases must not be registered twice (the router warns and overwrites).
3. Tests, then update the wrapper test expectations.

### `.../slack/commands/connection_commands.py` (CREATE)
```python
"""Provider-generic Slack connection commands (FEAT-777 M2).

``/login`` issues a one-time web link; ``/connect``, ``/disconnect``, ``/connections`` act on the principal
resolved from the team-qualified Slack id. ``/connect_jira``, ``/disconnect_jira``, ``/jira_status`` are aliases.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional

from parrot.auth.principal import resolve_principal

if TYPE_CHECKING:
    from parrot.auth.oauth2.service import IntegrationsService
    from parrot.auth.principal import Principal
    from parrot.integrations.slack.commands import SlackCommandRouter

logger = logging.getLogger(__name__)

_SLACK = "slack"
_LINK_FIRST = "Link your Slack account first: run `/login`."
_NOT_CONFIGURED = "Account linking is not configured."
_DENIED = "You are not permitted to do that."


def _ephemeral(text: str, **extra: Any) -> Dict[str, Any]:
    return {"response_type": "ephemeral", "text": text, **extra}


def _ids(payload: Mapping[str, Any]) -> tuple[str, str, str]:
    team_id = str(payload.get("team_id") or "")
    slack_user_id = str(payload.get("user_id") or "")
    return team_id, slack_user_id, f"{team_id}:{slack_user_id}"


def _provider_arg(payload: Mapping[str, Any], command: str) -> str:
    # FILL IN: words = text.split(); drop words[0] when it equals `command`; return the next word lower-cased or ""
    raise NotImplementedError


async def _principal(payload: Mapping[str, Any]) -> Optional["Principal"]:
    team_id, slack_user_id, composite = _ids(payload)
    if not team_id or not slack_user_id:
        return None
    return await resolve_principal(_SLACK, composite)


class AppLinkIssuer:
    """Resolve ``app["channel_link_issuer"]`` at call time (server startup may run after wrapper init)."""

    def __init__(self, app: Mapping[str, Any]) -> None:
        self._app = app

    async def issue(self, channel: str, channel_user_id: str, extra: Optional[Dict[str, str]] = None) -> str:
        issuer = self._app.get("channel_link_issuer")
        if issuer is None:
            raise LookupError("channel_link_issuer is not configured")
        return await issuer.issue(channel, channel_user_id, extra)


async def login_handler(payload: Dict[str, Any], link_issuer: Any) -> Dict[str, Any]:
    """``/login``: return a one-time link to confirm in the logged-in web UI."""
    team_id, slack_user_id, composite = _ids(payload)
    if await _principal(payload) is not None:
        return _ephemeral("Your Slack account is already linked to the platform.")
    try:
        url = await link_issuer.issue(_SLACK, composite, {"team_id": team_id, "slack_user_id": slack_user_id})
    except (ValueError, LookupError):
        logger.warning("Slack /login unavailable: channel linking is not configured")
        return _ephemeral(_NOT_CONFIGURED)
    # FILL IN: Block Kit section + button "Link account" → url, text says the link expires in 10 minutes and
    # must be opened while logged in — bounded by spec G4 (never log url)
    raise NotImplementedError


async def connect_handler(payload: Dict[str, Any], provider_id: str, service_factory: Callable[[], "IntegrationsService"]) -> Dict[str, Any]:
    """``/connect <provider>``: start a connection for the linked principal."""
    principal = await _principal(payload)
    if principal is None:
        return _ephemeral(_LINK_FIRST)
    # FILL IN: empty/unknown provider → registered ids list; service.start_connect(principal.user_id, provider_id,
    # channel=_SLACK, principal=principal, extra_state={"team_id": ..., "slack_user_id": ...}); PermissionError → _DENIED;
    # return a connect button with response.auth_url — bounded by AC-6 / AC-14 (no state when unlinked or denied)
    raise NotImplementedError


async def disconnect_handler(payload: Dict[str, Any], provider_id: str, service_factory: Callable[[], "IntegrationsService"]) -> Dict[str, Any]:
    # FILL IN: same principal/provider guards; service.disconnect(principal.user_id, provider_id, principal=principal);
    # PermissionError → _DENIED — bounded by AC-14
    raise NotImplementedError


async def status_handler(payload: Dict[str, Any], provider_id: str, service_factory: Callable[[], "IntegrationsService"]) -> Dict[str, Any]:
    # FILL IN: service.status(principal.user_id, provider_id, principal=principal) → "Connected as …" / "Not connected" — AC-6 (/jira_status alias)
    raise NotImplementedError


async def connections_handler(payload: Dict[str, Any], service_factory: Callable[[], "IntegrationsService"]) -> Dict[str, Any]:
    # FILL IN: service.list_for_principal(principal.user_id, principal=principal) → one line per provider
    # (display_name — status — account); empty list → "No connections available." — bounded by AC-14 (no data on deny)
    raise NotImplementedError


def register_connection_commands(router: "SlackCommandRouter", *, link_issuer: Any,
                                 service_factory: Callable[[], "IntegrationsService"]) -> None:
    """Register the generic commands and the Jira aliases on ``router``."""

    async def _login(p: Dict[str, Any]) -> Dict[str, Any]:
        return await login_handler(p, link_issuer)

    async def _connect(p: Dict[str, Any]) -> Dict[str, Any]:
        return await connect_handler(p, _provider_arg(p, "connect"), service_factory)

    async def _disconnect(p: Dict[str, Any]) -> Dict[str, Any]:
        return await disconnect_handler(p, _provider_arg(p, "disconnect"), service_factory)

    async def _connections(p: Dict[str, Any]) -> Dict[str, Any]:
        return await connections_handler(p, service_factory)

    async def _connect_jira(p: Dict[str, Any]) -> Dict[str, Any]:
        return await connect_handler(p, "jira", service_factory)

    async def _disconnect_jira(p: Dict[str, Any]) -> Dict[str, Any]:
        return await disconnect_handler(p, "jira", service_factory)

    async def _jira_status(p: Dict[str, Any]) -> Dict[str, Any]:
        return await status_handler(p, "jira", service_factory)

    for name, handler in (("login", _login), ("connect", _connect), ("disconnect", _disconnect),
                          ("connections", _connections), ("connect_jira", _connect_jira),
                          ("disconnect_jira", _disconnect_jira), ("jira_status", _jira_status)):
        router.register(name, handler)
    logger.info("Registered Slack connection commands")
```
**Why this shape**: spec skeleton fixes `register_connection_commands(router, *, link_issuer, service_factory)`;
one factory call per command keeps `IntegrationsService` per-request, as its docstring requires (service.py:66-70).

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/wrapper.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            register_jira_commands(self._command_router, oauth_manager)' wrapper.py)
# DELETE that line (wrapper.py:128). Keep the `if oauth_manager is not None:` block with its notifier lines.
# occurrences: 1 (verified: grep -c '        self._command_router = SlackCommandRouter()' wrapper.py)
# AFTER — insert below `        self._command_router = SlackCommandRouter()` (wrapper.py:125) and below
# TASK-5042's notifier block if present:
        from parrot.auth.oauth2.service import IntegrationsService
        from .commands.connection_commands import AppLinkIssuer, register_connection_commands

        register_connection_commands(
            self._command_router,
            link_issuer=AppLinkIssuer(app),
            service_factory=lambda: IntegrationsService(authorizer=app.get("connection_authorizer")),
        )
# occurrences: 1 (verified: grep -c 'from .commands.jira_commands import register_jira_commands' wrapper.py)
# DELETE line :17 once unused (ruff F401). Update the __init__ docstring for `oauth_manager` (:100-104).
```

### `.../tests/integrations/slack/test_slack_connection_commands.py` (CREATE)
```python
"""Slack generic connection commands (FEAT-777 AC-6, AC-14)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.principal import Principal
from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.slack.commands.connection_commands import register_connection_commands

PAYLOAD = {"team_id": "T01", "user_id": "U02", "channel_id": "C1", "text": "jira"}


@pytest.fixture
def principal() -> Principal:
    return Principal(user_id="1042", channel="slack", channel_user_id="T01:U02")


def _router(link_issuer=None, service=None) -> SlackCommandRouter:
    router = SlackCommandRouter()
    register_connection_commands(router, link_issuer=link_issuer or AsyncMock(), service_factory=lambda: service)
    return router


async def test_slack_connect_unlinked_replies_login(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MagicMock(start_connect=AsyncMock())
    monkeypatch.setattr("parrot.integrations.slack.commands.connection_commands.resolve_principal", AsyncMock(return_value=None))
    result = await _router(service=service).dispatch("connect", PAYLOAD)
    assert "/login" in result["text"]
    service.start_connect.assert_not_awaited()


async def test_slack_connect_linked_starts_with_principal(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: resolve_principal → principal; start_connect returns object with auth_url; assert awaited with
    # channel="slack", principal=principal, user_id "1042", extra_state team_id/slack_user_id; button url == auth_url
    ...


async def test_slack_jira_aliases_delegate(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: dispatch("connect_jira", {...text ""}) ≡ dispatch("connect", {...text "jira"}) → same start_connect args
    ...


async def test_login_issues_team_qualified_link(monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: unlinked; link_issuer.issue awaited with ("slack", "T01:U02", {"team_id": "T01", "slack_user_id": "U02"})
    ...


async def test_login_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: issue raises ValueError → "not configured" text, no exception — D5
    ...


@pytest.mark.parametrize("command", ["connect", "disconnect", "connections", "jira_status"])
async def test_permission_denied_discloses_nothing(command: str, principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: service method raises PermissionError → denied text, no account data — AC-14
    ...


async def test_unknown_provider_lists_registered(principal: Principal, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: start_connect raises ValueError("Unknown provider") or provider not in registry → reply lists ids
    ...
```

### `.../tests/integrations/slack/test_slack_wrapper_jira.py` (MODIFY)
```python
# FILL IN: the aliases are now always registered: change the "not registered without oauth_manager"
# assertions (:113-114) to assert "connect_jira" and "login" ARE registered; keep the dispatch test (:117)
# but patch connection_commands.resolve_principal / IntegrationsService instead of the Jira manager — AC-6
```

### FILL IN checklist
- [ ] `_provider_arg` parsing.
- [ ] `login_handler` button response.
- [ ] `connect_handler`, `disconnect_handler`, `status_handler`, `connections_handler` bodies.
- [ ] New test bodies + wrapper test update.

---

## Acceptance Criteria

- [ ] Unlinked `/connect <p>` replies with the `/login` instruction and creates no OAuth state (AC-6).
- [ ] Linked `/connect <p>` calls `start_connect(channel="slack", principal=…)` and returns the auth URL (AC-6).
- [ ] `/connect_jira`, `/disconnect_jira`, `/jira_status` behave as the generic commands with `jira` (AC-6).
- [ ] Denied / missing authorizer → no state, deletion or account data (AC-14).
- [ ] No server imports in integrations; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_connection_commands.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_wrapper_jira.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/slack/test_slack_jira_commands.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** (Module 2; G4, AC-6, AC-14)
3. **Check dependencies** — TASK-5034, TASK-5038, TASK-5041, TASK-5042 must be `"done"`
4. **Verify the Codebase Contract** — confirm the app keys TASK-5041 actually set (`channel_link_issuer`, `connection_authorizer`)
5. **Update status** → `"in-progress"`; commit only the index
6. **Implement** from the blueprint
7. **Verify** with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-integrations/src`
8. **Commit** only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-5044 connections-web-slack verified`
10. **Completion Note** — state the link delivery mechanism and that `jira_commands.py` was left unchanged

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
