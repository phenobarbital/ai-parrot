# TASK-5067: `MSTeamsConnectionNotifier` + `MSTeamsConversationRefStore` (in `connections.py`)

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5066
**Assigned-to**: unassigned

---

## Context

Spec §2 "Notifier (M4)", §3 Module 4, AC-6, AC-7. One provider-agnostic FEAT-773 `ChannelNotifier` for
`channel="msteams"` handles `connection.completed`, `connection.revoked`, `connection.refresh_failed`, routes each
message through the adapter of the bot that owns the conversation, and never raises. This task adds the classes
**additively**; removing `MSTeamsOAuthNotifier` / `MSTeamsJiraNotifierAdapter` and wiring happen in TASK-5072
and TASK-5073. Depends on TASK-5066 because both write `connections.py`.

---

## Scope

- `MSTeamsConversationRefStore(redis, ttl_s=30*86400)`: `save(nav_user_id, ref)` / `get(nav_user_id)` on key
  `msteams:convref:{nav_user_id}` (JSON). Redis errors are logged; `get` returns `None`.
- `MSTeamsConnectionNotifier(ref_store)`: `channel = "msteams"`, `attach(app_id, adapter)`,
  `notify(event, state_payload)`:
  - ref = `state_payload["extra"]["conversation_reference"]` when present, else `ref_store.get(event.user_id)`;
  - app id = `state_payload["extra"]["bot_app_id"]`, else the ref's `bot.id` minus the `28:` prefix;
    unknown app id → warning, no send;
  - text per kind (exact): completed → `"<Provider> connected as **<display_name>**. Ask again to use it."`;
    revoked → `"<Provider> disconnected."`; refresh_failed → ``"<Provider> access expired — `/connect <id>` to reconnect."``
    — never token material, never `event.reason`;
  - `adapter.continue_conversation(ConversationReference.deserialize(ref), cb, app_id)`; every failure logged.
- Tests: `test_notifier_completed_uses_state_ref`, `test_notifier_refresh_failed_uses_ref_store`,
  `test_notifier_multi_bot_routing`, `test_notifier_never_raises`, ref-store round trip.

**NOT in scope**: registering in `ChannelNotifierRegistry` (TASK-5073), wrapper `attach`/`save` calls (TASK-5071/5072),
deleting old notifiers (TASK-5072/5073).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` | MODIFY | append ref store + notifier |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from botbuilder.schema import Activity, ConversationReference                     # verified: oauth_callback.py:120-124
from parrot.auth.oauth2.events import ConnectionEvent                             # verified: auth/oauth2/events.py:17
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry                    # verified: auth/oauth2/registry.py (get :106)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/events.py
class ConnectionEvent(BaseModel):                                                  # :17
    kind: ConnectionEventKind; user_id: str; canonical_identity; tenant_id; provider: str
    account_id: str = ""; display_name: str = ""; channel: str; occurred_at: float; reason: Optional[str]
class ChannelNotifier(Protocol): channel: str; async def notify(self, event, state_payload) -> None   # :33-38

# proactive pattern — oauth_callback.py:119-142
conv_ref = ConversationReference.deserialize(conversation_ref_dict)
async def _callback(turn_context): await turn_context.send_activity(Activity(type="message", text=...))
await self._adapter.continue_conversation(conv_ref, _callback, self._app_id)

# OAuth2ProviderRegistry().get(provider_id) -> Optional[OAuth2Provider] (.display_name)          # registry.py:106
```
`connections.py` (after TASK-5066) already defines `logger`, `MSTEAMS_CHANNEL`, `TeamsConnectState`.

### Does NOT Exist
- ~~`MSTeamsConnectionNotifier`~~ / ~~`MSTeamsConversationRefStore`~~ — created here.
- ~~a `connection.failed` event kind~~ — spec Q4 default: not added.
- ~~a new Redis client~~ — the store receives the app's existing client (`app["redis"]`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEvent",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ChannelNotifier",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/registry.py#OAuth2ProviderRegistry"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Append the ref store, then the notifier, at the end of `connections.py`. 2. Fill the gaps. 3. Tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/connections.py` (MODIFY — append at end of file)
```python
_CONVREF_KEY = "msteams:convref:{nav_user_id}"
_CONVREF_TTL_S = 30 * 86400


class MSTeamsConversationRefStore:
    """Latest personal conversation reference per Navigator user (Redis, JSON)."""

    def __init__(self, redis: Any, ttl_s: int = _CONVREF_TTL_S) -> None:
        self._redis = redis
        self._ttl_s = ttl_s

    async def save(self, nav_user_id: str, conversation_reference: Dict[str, Any]) -> None:
        """Store (and refresh the TTL of) the reference; log and swallow Redis errors."""
        # FILL IN: json.dumps + redis.set(key, value, ex=self._ttl_s) in try/except logger.warning — bounded by spec §2 Notifier
        ...

    async def get(self, nav_user_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored reference or ``None`` (missing, undecodable or Redis error)."""
        # FILL IN: redis.get + json.loads (bytes or str) in try/except → None
        ...


class MSTeamsConnectionNotifier:
    """FEAT-773 ``ChannelNotifier`` for Teams: every provider, every lifecycle event, multi-bot routing."""

    channel = MSTEAMS_CHANNEL

    def __init__(self, ref_store: Optional[MSTeamsConversationRefStore]) -> None:
        self._ref_store = ref_store
        self._adapters: Dict[str, Any] = {}

    def attach(self, app_id: str, adapter: Any) -> None:
        """Register the adapter of one Teams bot under its Microsoft app id."""
        if app_id:
            self._adapters[app_id] = adapter

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None:
        """Send the lifecycle message to the owning conversation; log every failure, never raise."""
        try:
            extra = (state_payload or {}).get("extra") or {}
            ref = extra.get("conversation_reference") or None
            if ref is None and self._ref_store is not None:
                ref = await self._ref_store.get(event.user_id)
            if not ref:
                logger.warning("Teams notifier: no conversation reference for provider=%s", event.provider)
                return
            app_id = self._resolve_app_id(extra, ref)
            adapter = self._adapters.get(app_id or "")
            if adapter is None:
                logger.warning("Teams notifier: no adapter attached for app id %r", app_id)
                return
            text = self._message(event)
            # FILL IN: deserialize ref, define the send callback, await adapter.continue_conversation(conv_ref, cb, app_id)
        except Exception:  # noqa: BLE001 — FEAT-773 publisher contract: never raise
            logger.exception("Teams notifier failed for provider=%s kind=%s", event.provider, event.kind)

    @staticmethod
    def _resolve_app_id(extra: Dict[str, Any], ref: Dict[str, Any]) -> Optional[str]:
        """``bot_app_id`` from state, else the reference's ``bot.id`` without the ``28:`` prefix."""
        # FILL IN — bounded by spec §2 Notifier (adapter choice rule)
        ...

    @staticmethod
    def _message(event: ConnectionEvent) -> str:
        """Exact per-kind text from spec §2; never includes token material or event.reason."""
        provider = OAuth2ProviderRegistry().get(event.provider)
        name = getattr(provider, "display_name", None) or event.provider
        # FILL IN: the three exact strings keyed by event.kind
        ...
```
Add `import json` and `from parrot.auth.oauth2.events import ConnectionEvent`,
`from parrot.auth.oauth2.registry import OAuth2ProviderRegistry` to the module imports; import botbuilder
inside `notify` (as oauth_callback.py does) so the module imports without a live Bot Framework.

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py` (CREATE)
```python
"""FEAT-775 M4: Teams connection notifier (AC-6, AC-7)."""
import pytest

from parrot.auth.oauth2.events import ConnectionEvent
from parrot.integrations.msteams.connections import MSTeamsConnectionNotifier, MSTeamsConversationRefStore

# FILL IN fixtures: fake adapter recording continue_conversation(ref, cb, app_id) and running cb with a fake
#   turn context capturing send_activity text; dict-backed fake redis (async set/get); a serialized ref with
#   bot.id "28:app-2"; event factory.

# test_notifier_completed_uses_state_ref — state extra ref + bot_app_id → that adapter; exact "connected as" text
# test_notifier_refresh_failed_uses_ref_store — no state → ref store by event.user_id; "/connect jira" text
# test_notifier_revoked_text — "Jira disconnected."
# test_notifier_multi_bot_routing — adapters for app-1 and app-2; ref bot.id "28:app-2" → adapter 2 only
# test_notifier_never_raises — adapter raising / no ref / unknown app id → no exception, warning logged
# test_ref_store_round_trip_and_ttl — save then get; TTL passed as ex=30*86400
```

### FILL IN checklist
- [ ] ref store save/get
- [ ] `_resolve_app_id`, `_message`, send callback
- [ ] six tests

---

## Acceptance Criteria

- [ ] All three event kinds delivered with the exact texts; no token material or raw reason (AC-6).
- [ ] Multi-bot routing picks the owning bot's adapter (AC-6).
- [ ] Every failure logged, never raised (AC-7).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_connection_notifier.py -q`

---

## Test Specification

Six tests listed in the test-file block.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

