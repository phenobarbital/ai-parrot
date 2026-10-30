# TASK-4955: Integrations wiring (principal resolver, notifiers, publisher) + Telegram /connect_jira requires a principal

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4954, TASK-4952, TASK-4953
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 wiring + U3, AC-9. The integrations manager builds the Jira manager; it must also give it a
`ConnectionEventPublisher` (with the notifier registry holding the three adapters) and make sure a server
`PrincipalResolver` is registered. Telegram `/connect_jira` must pass the session principal (the user's
`nav_user_id` after `/login`) or reply "please /login first" and create no OAuth state. Status/disconnect commands
resolve the principal too, so a linked user keeps the connection without re-authorizing.

---

## Scope

- `integrations/manager.py`: `_build_principal_resolver(app)` (IdentityPrincipalResolver over `app['authdb']`, else
  `None`); `_register_channel_notifiers(app)` (register the three adapters once); a shared
  `ConnectionEventPublisher` stored at `app['connection_event_publisher']` (create if absent); pass
  `event_publisher=` at both Jira construction sites; call `set_principal_resolver` when a resolver is built.
- `telegram/jira_commands.py`: `register_jira_commands(router, oauth_manager, session_clearer=None, session_lookup=None)`;
  `connect_jira_handler` builds `Principal(user_id=session.nav_user_id, channel="telegram", channel_user_id=tid)` from
  `session_lookup(tid)`, else `resolve_principal("telegram", tid)`, else replies the `/login` message and returns;
  `validate_token`/`revoke` calls use `principal.user_id` with `channel_user_id=tid` where supported.
- `telegram/wrapper.py`: pass `session_lookup=lambda tid: self._user_sessions.get(int(tid))` (closure like `_clear_jira_session`).
- `telegram/post_auth_jira.py`: pass `principal=` (it already knows `nav_user_id`, :102-103).
- Tests `test_telegram_connect_jira_requires_principal`; update `test_post_auth_jira.py`.

**NOT in scope**: Slack/MS Teams commands (TASK-4956); deleting the old callback (TASK-4958). NOTE: until TASK-4958 lands, Jira completion may notify twice (old callback + adapters) — expected inside the feature branch.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | resolver, notifiers, publisher wiring |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` | MODIFY | principal-required connect |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | session_lookup closure |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` | MODIFY | pass principal |
| `packages/ai-parrot-integrations/tests/test_telegram_jira_principal.py` | CREATE | unit tests |
| `packages/ai-parrot/tests/unit/test_post_auth_jira.py` | MODIFY | principal kwarg |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.auth.principal import Principal, resolve_principal, set_principal_resolver   # TASK-4937
from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEventPublisher  # TASK-4938
from parrot.integrations.core.auth.notifiers import (TelegramJiraNotifierAdapter, SlackJiraNotifierAdapter,
                                                     MSTeamsJiraNotifierAdapter)         # TASK-4953
from parrot.services.identity_principal import IdentityPrincipalResolver                 # TASK-4952 (lazy import: server optional)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py
async def connect_jira_handler(message, oauth_manager) -> None        # :50 anchor; user_id = str(message.from_user.id);
                                                                      #   validate_token(_TELEGRAM_CHANNEL, user_id) :72; create_authorization_url(
                                                                      #   _TELEGRAM_CHANNEL, user_id, extra_state={"chat_id": message.chat.id}) :79
async def disconnect_jira_handler(message, oauth_manager, session_clearer=None)   # revoke(_TELEGRAM_CHANNEL, user_id) :114
# jira status handler: validate_token(_TELEGRAM_CHANNEL, user_id) :142
def register_jira_commands(router, oauth_manager, session_clearer=None) -> None   # :156
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
self._user_sessions: Dict[int, TelegramUserSession] = {}             # :178
register_jira_commands(self.router, oauth_manager, session_clearer=_clear_jira_session)   # :426
# TelegramUserSession.nav_user_id (used at knowledge_upload.py:128, post_auth_jira.py:102)
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py
        url, nonce = await self._oauth.create_authorization_url(...)  # :109 ; extra_state["nav_user_id"] = session.nav_user_id :103
# JiraOAuthManager (after TASK-4954): get_valid_token(channel, user_id, *, channel_user_id=None); revoke(channel, user_id, *,
#   channel_user_id=None); create_authorization_url(channel, user_id, extra_state=None, *, principal=None); validate_token(channel, user_id)
```

### Does NOT Exist
- ~~`PermissionContext.nav_user_id`~~ — the session object (`TelegramUserSession.nav_user_id`) carries it, not the permission context.
- ~~a Telegram principal cache~~ — not needed; resolve per command.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/test_telegram_jira_principal.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/test_post_auth_jira.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py#connect_jira_handler",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py#register_jira_commands"
  ]
}
```

---

## Implementation Notes

- Reply text must keep `parse_mode=None` (see the handler docstring: Markdown would break on underscores).
- `/login first` reply: "Please /login first to link your Telegram account, then run /connect_jira again."
- `validate_token(channel, principal.user_id)` — if `validate_token` lacks `channel_user_id`, legacy migration still
  happens through `get_valid_token` inside it (TASK-4954 keeps that path).

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Wiring helpers in integrations/manager.py — *why*: notifiers must be registered before TASK-4958 switches the route.
2. Telegram connect/status/disconnect principal resolution — *why*: U3 / AC-9.
3. wrapper.py session_lookup and post_auth_jira principal — *why*: the combined login flow already knows nav_user_id.
4. Tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` (MODIFY)
```python
# AFTER `def _build_credential_store(app: Any) -> Any:` (added by TASK-4954) add:
def _build_principal_resolver(app: Any) -> Any:
    """IdentityPrincipalResolver over app['authdb'] (registered process-wide), else None."""
    # FILL IN: lazy import; set_principal_resolver(resolver); return resolver

def _connection_publisher(app: Any) -> Any:
    """Shared ConnectionEventPublisher at app['connection_event_publisher'] with the Jira adapters registered."""
    # FILL IN: registry = ChannelNotifierRegistry(); register the 3 adapters (idempotent); create publisher once
# FILL IN: at both JiraOAuthManager( sites (MS Teams ~:367, Slack ~:926 — the two blocks TASK-4954 edited) add
#          event_publisher=_connection_publisher(app), and call _build_principal_resolver(app) once before.
```

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/jira_commands.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def connect_jira_handler(' telegram/jira_commands.py → :50)
async def connect_jira_handler(message: Message, oauth_manager: "JiraOAuthManager",
                               session_lookup: Optional[Callable[[str], Any]] = None) -> None:
    # KEEP the from_user guard. Then:
    tid = str(message.from_user.id)
    principal = await _telegram_principal(tid, session_lookup)
    if principal is None:
        await message.reply(_LOGIN_FIRST, parse_mode=None)
        return
    # FILL IN: validate_token(_TELEGRAM_CHANNEL, principal.user_id) → "already connected"; else
    #          create_authorization_url(_TELEGRAM_CHANNEL, tid, extra_state={"chat_id": message.chat.id}, principal=principal)


async def _telegram_principal(tid: str, session_lookup: Optional[Callable[[str], Any]]) -> Optional["Principal"]:
    """Session nav_user_id first, then the registered resolver; None → caller replies /login first."""
    # FILL IN — bounded by U3 (never key by the telegram id)
# FILL IN: same principal resolution in the status and disconnect handlers; register_jira_commands gains session_lookup
```

### FILL IN checklist
- [ ] manager.py helpers + both construction sites
- [ ] telegram handlers (connect/status/disconnect) + register_jira_commands signature
- [ ] wrapper.py:426 passes session_lookup
- [ ] post_auth_jira.py:109 passes principal
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-9: a Telegram user without `nav_user_id` (and no identity row) gets the /login reply and no OAuth state is created
- [ ] A linked Telegram user (identity row present) is reported connected without re-authorizing
- [ ] Jira managers built by the integrations manager carry `credential_store` and `event_publisher`; a server resolver is registered when `authdb` exists

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/test_telegram_jira_principal.py -q`
- `pytest packages/ai-parrot/tests/unit/test_post_auth_jira.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/test_telegram_jira_principal.py
@pytest.mark.asyncio
async def test_telegram_connect_jira_requires_principal(): ...   # no session nav id + resolver None → /login reply, no nonce in redis
@pytest.mark.asyncio
async def test_telegram_connect_uses_session_principal(): ...    # session nav 1042 → create_authorization_url(principal.user_id == "1042")
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
