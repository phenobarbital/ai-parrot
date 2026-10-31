# TASK-5078: Review robustness fixes — SSE subscribe gap, O365 legacy cleanup, nonce restore, duplicate connected

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: in-progress
**Priority**: low
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-5059
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:19c0633ffc61`

---

## Context

Follow-up from the FEAT-777 review (ledger `issue:19c0633ffc61`, tech_debt/low). Five minor robustness items:

- (a) `connection_events.py`: `response.prepare()` ran before `push.subscribe()` reached Redis, so an event
  published in that gap was lost.
- (b) `o365_devicecode_provider.py`: when `migrate_legacy_device_grant` returns `None` (a current record or a
  disconnect tombstone won) the legacy entry was not deleted and `resolve` ran a redundant device flow.
- (c) `channel_links.py`: the nonce is consumed before the identity claim, so a transient 500 burned it.
- (d) `AgentChat.svelte` `handleAuthConnected`: popup and SSE both fire `connected`; the second call showed the
  manual-retry warning while the single auto-retry was already in flight.
- (e) `slack/notifier.py` process-wide notifier — already a documented v1 limit; no change.

## Scope

- `RedisConnectionPush.subscribe(user_id, *, ready=None)` sets `ready` once the Redis SUBSCRIBE is acknowledged.
- `ConnectionEventsHandler.get` waits for `ready` (bounded) before `prepare()`; a subscription that fails before
  it is ready returns 503 instead of an empty 200 stream.
- `_migrate_legacy`: on `None` from the manager, delete the legacy entry (it can never be imported) and re-read
  the current grant; return it when present, otherwise fall back to the device flow.
- `ChannelLinkIssuer.restore(nonce, claim)`: re-store a consumed claim for its remaining TTL (`SET NX`);
  `ChannelLinksHandler.post` calls it when the identity claim raises.
- `handleAuthConnected`: a duplicate `connected` for an origin already auto-retried is a no-op.

**NOT in scope**: (e); durable (Redis-backed) legacy-cleanup markers — a leftover legacy blob is inert because the
current-record-wins check and the 400-day revoke tombstone both block re-import, and any later miss path deletes it.

## Files to Modify

- `packages/ai-parrot-server/src/parrot/services/connection_push.py`
- `packages/ai-parrot-server/src/parrot/handlers/connection_events.py`
- `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py`
- `packages/ai-parrot/src/parrot/auth/channel_link.py`
- `packages/ai-parrot-server/src/parrot/handlers/channel_links.py`
- `packages/ai-parrot-server/ui/src/lib/components/agents/AgentChat.svelte`
- tests: `packages/ai-parrot-server/tests/unit/test_connection_events_handler.py`,
  `packages/ai-parrot-server/tests/unit/test_connection_push.py`,
  `packages/ai-parrot-server/tests/unit/test_channel_links_handler.py`,
  `packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py`

## Acceptance Criteria

- [ ] SSE handler does not call `prepare()` until the subscription is ready; early subscription failure → 503.
- [ ] Legacy entry deleted when migration returns `None`; current grant returned without a device flow.
- [ ] A claim exception restores the nonce; a later confirm can succeed.
- [ ] Duplicate `connected` does not flag manual retry.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src pytest -q \
  packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py \
  packages/ai-parrot-server/tests/unit/test_connection_events_handler.py \
  packages/ai-parrot-server/tests/unit/test_connection_push.py \
  packages/ai-parrot-server/tests/unit/test_channel_links_handler.py
```

## Completion Note

(pending)
