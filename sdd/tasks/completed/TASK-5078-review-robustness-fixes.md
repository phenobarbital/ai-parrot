# TASK-5078: Review robustness fixes — SSE subscribe gap, O365 legacy cleanup, nonce restore, duplicate connected

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
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

- [x] SSE handler does not call `prepare()` until the subscription is ready; early subscription failure → 503.
- [x] Legacy entry deleted when migration returns `None`; current grant returned without a device flow.
- [x] A claim exception restores the nonce; a later confirm can succeed.
- [x] Duplicate `connected` does not flag manual retry.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src pytest -q \
  packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py \
  packages/ai-parrot-server/tests/unit/test_connection_events_handler.py \
  packages/ai-parrot-server/tests/unit/test_connection_push.py \
  packages/ai-parrot-server/tests/unit/test_channel_links_handler.py
```

## Completion Note

Implemented in 097955f6de (feature branch), filed by `/sdd-fix issue:19c0633ffc61`.

- (a) `RedisConnectionPush.subscribe(..., ready=)` sets the event after SUBSCRIBE; the handler waits up to
  `SUBSCRIBE_TIMEOUT_SECONDS` (5s) before `prepare()`, returns 503 when the subscription fails first, and cancels
  the producer if the request is cancelled during the wait. On timeout it streams anyway (logged).
- (b) `_migrate_legacy` deletes the legacy entry on every non-error outcome and, when the manager returned `None`,
  re-reads the current grant (`_current_token`) instead of falling through to a device flow. Durable markers were
  not added: a leftover legacy blob is inert (current-record-wins + 400-day tombstone), documented on `_delete_legacy`.
- (c) `ChannelLinkIssuer.restore()` re-stores a consumed claim for its remaining TTL only (`SET NX`); the confirm
  handler calls it when `claim_channel_identity` raises. A failing restore is logged and the response stays 500.
- (d) No production change needed: `ConnectIntegrationPill.notifyConnected()` already guards against the popup + SSE
  double fire (landed in TASK-5055) and the `{#each}` is keyed on `msg.id`, so the pill never remounts. A per-pill
  dedupe in AgentChat was tried and reverted as redundant (mutation check: tests passed with it disabled). Two
  vitest assertions now pin the behaviour (in-flight duplicate shows no warning; a new pill for an already
  auto-retried turn still asks for a manual retry).
- (e) Unchanged — documented v1 limit.

Validation: 31 passed (pytest, the Validation Commands plus `test_channel_link.py` and `test_connection_events.py`,
with real Redis db 15); vitest `AgentChat.auth-retry.test.ts` + `integrations/` 13 passed; ruff + black clean.
