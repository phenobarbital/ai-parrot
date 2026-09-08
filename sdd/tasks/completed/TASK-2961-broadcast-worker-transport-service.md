# TASK-2961: BroadcastService facade, owner reconciliation watchdog and authenticated worker transport

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2953, TASK-2960
**Parallel**: false
**Parallelism notes**: Creates `broadcast/service.py` + `broadcast/worker_transport.py`; one small hook in `handler.py` (`broadcast_service` becomes a typed `BroadcastService`). Sequential after TASK-2960.

---

## Context

Spec §2: "For a socket connected to another worker, an internal aiohttp WebSocket relay authenticates the worker and carries participant/owner/floor epochs in bounded messages. Public clients cannot select an owner address. Resolve it from trusted server configuration/registry, prevent arbitrary URLs, use TLS/service credentials outside loopback, enforce message size/time limits and fence stale owner epochs. No raw microphone audio in Redis pub/sub. Live objects stay on the producer process." Plus "Ownership, admission and cleanup": watchdog ≤ 5 s, fence expired owners, cleanup ≤ 30 s, cross-worker stop, reconciliation via LiveKit participant listing. Module 4 (worker_transport) + the service object Modules 5/6 wire.

## Scope

- `broadcast/service.py`: `class BroadcastService` — the single object HTTP (TASK-2962), WS (TASK-2960) and the example (TASK-2963) depend on. Constructor: `registry: BroadcastRegistry`, `room_manager: LiveKitRoomManager`, `nova_bot_factory: Callable[[], VoiceBot]`, `worker_id: str`, `worker_registry: WorkerAddressRegistry` (see below), `principal_resolver` (callable `(AuthenticatedUser|Mapping, agent_id) -> ParticipantPrincipal`), `authorize_agent` (callable `(principal, agent_id) -> bool`), knobs. Methods (all async, all check scope/authority and raise `errors.*`): `create_broadcast(principal, agent_id) -> descriptor`, `get_public_state(principal, agent_id, bid)`, `join(principal, agent_id, bid) -> (lease, is_first)`; when `is_first`: `claim_owner` then `start_producer(bid)` (creates `BroadcastSession` + `BroadcastVoiceSession` + owner loop) exactly once; `connection(principal, bid, lease_id) -> ViewerJoinResponse` (idempotent per lease; mints `mint_viewer_token(room, lease.livekit_identity, ttl_s=60)` once and caches its expiry; raises retryable `BroadcastNotReady` while `starting`); `leave(principal, bid, lease_id)` (release + succession + stop producer if audience empty + `room_manager.remove_participant`); `raise_hand/cancel_hand/dismiss_hand`; `set_floor(principal, bid, target, expected_version)` → `FloorCoordinator.handoff`; `release_floor`; `stop(principal, bid)` (moderator only; `registry.request_stop`; owner observes ≤ 1 s); `resolve_principal`, `subscribe(bid, send_fn)/unsubscribe` (in-process fan-out of public state; Redis remains authoritative); `attach_speaker_input(bid, lease_id, floor_epoch) -> SpeakerInput` (local if this worker owns the producer, else a `RemoteSpeakerInput` over the worker transport).
- Watchdog task (`run_reconciler()` every 5 s): `registry.expire(now)`; for expired owners: fence (`owner_epoch` advance), remove room participants (`room_manager.list_participant_identities`/`remove_participant`), `delete_room`, `transition(failed, owner_lost)`; report `orphaned_vendor_session=True` when the owner-only vendor token is gone (cannot confirm vendor stop — spec §7). Expired control leases ⇒ remove participant → release seat → succession. Redis/LiveKit outage ⇒ log `reconciliation_uncertain`, retain slots (fail closed).
- `broadcast/worker_transport.py`: `WorkerAddressRegistry` (Redis hash `{prefix}:workers` worker_id → URL, written by each worker on start with TTL; **reads only server-configured/registered URLs**, rejects anything not `ws(s)://`), `WorkerRelayServer` (aiohttp route `/internal/voice-broadcast/relay` mounted only on the owner; authenticates a per-deployment shared service token from `PARROT_BROADCAST_WORKER_TOKEN` via header, requires TLS unless peer is loopback, max message 128 KiB, idle timeout 15 s, each message `{"owner_epoch","lease_id","floor_epoch","turn_id","seq","pcm_b64"}` validated → `validate_audio_authority` → `BroadcastVoiceSession.push_audio`; control frames `start_turn`/`end_turn`/`release`), and `RemoteSpeakerInput` client used by the ingress worker (bounded send queue, closes on `stale_owner_epoch`).
- `handler.py`: type the `broadcast_service` kwarg as `Optional["BroadcastService"]` (lazy import) and route mic frames via `service.attach_speaker_input(...)`.
- Tests: `tests/voice/test_voice_broadcast_service.py` (in-memory registry, fake room manager/session factories: first join starts producer once under race; leave/succession; stop; connection idempotency; reconciler fencing with fake clock) and `tests/voice/test_voice_broadcast_worker_transport.py` (two aiohttp test apps: ingress → owner relay; bad token 401; oversize 1009; stale owner epoch closes; arbitrary URL refused).

**NOT in scope**: REST endpoints (TASK-2962), example wiring (TASK-2963).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/service.py` | CREATE | `BroadcastService` + reconciler |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/worker_transport.py` | CREATE | Worker registry, relay server, remote speaker input |
| `packages/ai-parrot-integrations/src/parrot/voice/handler.py` | MODIFY | Typed service hook, remote/local speaker input |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_service.py` | CREATE | Service tests |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_worker_transport.py` | CREATE | Transport tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp; from aiohttp import web, WSMsgType   # handler.py:33 ; avatar_ws.py:41
from parrot.integrations.liveavatar.broadcast import models, errors, BroadcastRegistry, InMemoryBroadcastRegistry  # TASK-2951/2952
from parrot.integrations.liveavatar.broadcast.session import BroadcastSession           # TASK-2958
from parrot.integrations.liveavatar.broadcast.voice_relay import BroadcastVoiceSession  # TASK-2959
from parrot.integrations.liveavatar.broadcast.floor import FloorCoordinator, validate_audio_authority  # TASK-2960
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager               # + TASK-2954 admin ops
from parrot.bots.voice import VoiceBot                                                   # bots/voice.py:89
from parrot.core.ws_auth import AuthenticatedUser                                        # ws_auth.py:34
```

### Existing patterns
- Env-driven lazy config: `voice_session.py:137-149` (env read inside the method, actionable `RuntimeError`).
- Cross-process helper to **not** copy: `output_transport.py:40 RedisBroadcastForwarder` is a pub/sub envelope forwarder — fine for wake-ups, never for PCM or as source of truth.
- Keep-alive task pattern with cancel: `client.py:611-660 _start_keep_alive/_acancel_keep_alive/_keep_alive_loop`.

### Does NOT Exist
- ~~`BroadcastService`, `WorkerAddressRegistry`, `WorkerRelayServer`, `RemoteSpeakerInput`~~ — new.
- ~~Producer migration to another worker~~ — forbidden; end the broadcast.
- ~~PCM over Redis pub/sub~~ — forbidden.
- ~~Client-supplied owner URL~~ — forbidden; address comes from the worker registry only.

## Implementation Notes

- `join()` first-admission path: `lease, is_first = await registry.reserve_viewer(...)`; if `is_first`: `claimed, epoch = await registry.claim_owner(...)`; only the claimer calls `start_producer`; a loser (rare) serves participants via the relay.
- Owner loop = `BroadcastSession` renew loop + stop poll (already in TASK-2958); the service just supervises the task and logs.
- `WorkerRelayServer` uses the same `PARROT_BROADCAST_WORKER_TOKEN` on both sides; compare with `hmac.compare_digest`. Refuse to start when the token is unset and bind is non-loopback.

## Acceptance Criteria

- [ ] 10 concurrent `join()` on one broadcast ⇒ `start_producer` called once, one owner; `connection()` returns the same token/identity for the same lease and `BroadcastNotReady` while starting.
- [ ] Moderator `stop()` ⇒ producer closes, state `ended`; non-moderator `stop()` ⇒ `NotModerator`.
- [ ] Reconciler with fake clock: owner silent 15 s ⇒ fenced, `remove_participant` for every listed identity, `delete_room`, `failed/owner_lost`, `orphaned_vendor_session` flagged; total ≤ 30 s simulated.
- [ ] Transport: valid token+epoch frames reach `push_audio`; wrong token ⇒ 401; > 128 KiB ⇒ close 1009; stale `owner_epoch` ⇒ close + `RemoteSpeakerInput` raises; non-registered URL refused.
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_service.py packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_worker_transport.py -q` green; `ruff check` clean.

## Test Specification

```python
async def test_first_join_starts_producer_once_under_race(service_factory): ...
async def test_connection_is_idempotent_per_lease(service_factory): ...
async def test_stop_requires_moderator(service_factory): ...
async def test_reconciler_fences_dead_owner_and_cleans_room(service_factory, clock): ...
async def test_relay_rejects_bad_token_and_oversize(aiohttp_client): ...
async def test_relay_forwards_authorized_pcm(aiohttp_client): ...
```

## Agent Instructions
1. Read spec §2 "Ownership, admission and cleanup" + moderation bullet on cross-worker relay + §7 Known Risks. 2. Verify TASK-2953/2958/2959/2960 APIs. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**: `sdd-worker` (autonomous session)
**Date**: 2026-09-08
**Status**: done

**Notes**:

- Created `broadcast/service.py` (`BroadcastService`, `BroadcastNotReady`,
  `ReconcileReport`, `default_principal_resolver`) and
  `broadcast/worker_transport.py` (`WorkerAddressRegistry`, `WorkerRelayServer`,
  `RelayFrame`, `SpeakerInput`/`LocalSpeakerInput`/`RemoteSpeakerInput`,
  `WorkerTransportError`), exported both from the package, and routed the handler's
  microphone path through `service.attach_speaker_input(...)`.
- Tests: `test_voice_broadcast_service.py` → **30 passed**;
  `test_voice_broadcast_worker_transport.py` → **35 passed**. Whole `tests/voice/`
  → **434 passed** (was 369; same 11 pre-existing environment failures / 27 errors).
  `ruff check` clean.
- **Every AC has a named test:**
  - 10 concurrent `join()` → exactly one `is_first`, exactly one `FakeMediaSession`
    instance, `started == 1`, one owner at epoch 1. A second service on a *different*
    worker id joining the same broadcast starts **nothing**
    (`test_a_worker_that_loses_the_owner_race_does_not_start_media`) — spec §2 forbids
    a second producer, and a loser serves through the relay.
  - `connection()` returns the *same object* on retry and mints exactly one viewer
    token; `BroadcastNotReady` (status 409) while `starting`; another principal's lease
    is refused.
  - `stop()` refuses a viewer **and the creator** — only the current moderator.
  - Reconciler: owner silent 16 s → fenced, all three listed identities removed,
    `delete_room`, `failed`/`owner_lost`, `orphaned_vendor_sessions` flagged, and the
    elapsed simulated time asserted `<= 30 s`.
  - Transport: right token+epoch reaches `push_audio`; wrong/absent token → 401;
    oversize → close 1009/1008; stale owner epoch → close; non-`ws(s)://` URL refused
    (6 parametrised cases).
- **The relay re-validates on the owner.** `test_relay_revalidates_the_floor_on_the_owner`
  lands a revoke between ingress and the producer and asserts the frame is refused there.
  Passing ingress validation is explicitly not a permit — that second check is the whole
  reason the relay carries the fencing tuple rather than just PCM.
- **Security choices worth review:** the owner's address comes only from
  `WorkerAddressRegistry` and goes through one `validate_url` choke point; non-loopback
  relays must be `wss://` on the client side and TLS-or-loopback on the server side; the
  shared token is compared with `hmac.compare_digest`; and `WorkerRelayServer.setup_routes`
  **refuses to mount** without a token rather than starting unauthenticated.
- `RemoteSpeakerInput` drops oversized blocks and counts them instead of buffering:
  microphone audio delivered seconds late would have the agent answer a question the
  speaker has moved on from.
- **`_project()` closes the TASK-2958 seam.** `BroadcastRegistry.transition` has no
  parameters for `room_name` / `avatar_identity` / `direct_identity`, so the service
  joins the producer's `media_state()` onto the descriptor when building the public
  projection. `test_public_state_carries_producer_media_facts` asserts
  `selected_identity == "avatar-x"`, `media_ready is True`, and that the result still
  contains no `token`/`secret`/`ws_url`/`api_key`.
- **`orphaned_vendor_session` is keyed off the broadcast having reached `avatar`**, not
  off `descriptor.liveavatar_session_id`. Found by a failing test: nothing persists that
  id onto the descriptor (same `transition` gap), so the field-based condition would have
  silently never fired and the honest "we cannot confirm the vendor stopped" report would
  never have been emitted. Commented in the source.
- Reconciliation fails closed everywhere: a registry outage or a LiveKit outage records
  `reconciliation_uncertain` and **retains** seats; an expired control lease is removed
  from the room *before* its seat is released, so a replacement admission can never
  overlap a still-connected participant.

**Deviations from spec**: none of substance. Notes for the reviewer:
1. `BroadcastNotReady` is defined in `service.py` rather than `errors.py`, because
   `errors.py` belongs to TASK-2952's file set and this task's Files table does not
   include it.
2. The task listed `subscribe(bid, send_fn)/unsubscribe`; the implemented pair is
   lease-scoped (`attach_control`/`detach_control`, with `subscribe`/`unsubscribe` as
   aliases) because TASK-2960's `BroadcastControlService` protocol — already merged and
   tested — requires the lease-scoped form to route `floor_revoked` to one participant.
3. `default_principal_resolver` takes the tenant from server configuration with a
   `default` fallback rather than from the request; a client-chosen tenant would defeat
   the scoping model. Real multi-tenant deployments inject their own resolver.
