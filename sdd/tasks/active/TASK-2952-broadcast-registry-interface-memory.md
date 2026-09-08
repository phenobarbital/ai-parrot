# TASK-2952: BroadcastRegistry interface + in-memory reference implementation

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2951
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Extends the `broadcast/` package created by TASK-2951 (imports its models). Does not touch handler/session files, so it can run alongside TASK-2954–2957 in the same worktree if edited sequentially.

---

## Context

Implements spec §2 "Ownership, admission and cleanup" + "Moderation and exclusive speaking floor" as a storage-agnostic contract (Module 2). The in-memory implementation is the **reference semantics** the Redis implementation (TASK-2953) must match, and it is what every deterministic unit test uses (spec §4: "A registry interface permits an in-memory fake for unit tests").

## Scope

- `broadcast/registry.py`:
  - `class BroadcastRegistry(ABC)` with async methods (exact names from spec §2 "New Public Interfaces"): `create(descriptor) -> BroadcastDescriptor`, `get(tenant_id, broadcast_id) -> BroadcastDescriptor | None`, `claim_owner(tenant_id, broadcast_id, worker_id) -> tuple[bool, int]` (returns `(claimed, owner_epoch)`), `renew_owner(…, worker_id, owner_epoch) -> bool`, `reserve_viewer(tenant_id, broadcast_id, principal, livekit_identity, now) -> ViewerLease` (raises `ViewerLimitReached`, `BroadcastTerminal`), `confirm_viewer(…, lease_id)`, `heartbeat_control(…, lease_id, now)`, `release_viewer(…, lease_id) -> ReleaseOutcome` (dataclass: `audience_empty: bool`, `floor_returned_to: str|None`, `new_moderator: str|None`), `raise_hand`, `cancel_hand`, `dismiss_hand(…, moderator_lease_id, target_lease_id)`, `grant_floor(…, moderator_lease_id, target_lease_id | None, expected_version) -> BroadcastDescriptor` (enters `switching`, clears speaker, `floor_epoch += 1`, `version += 1`), `commit_floor(…, target_lease_id, floor_epoch) -> BroadcastDescriptor` (barrier acknowledged → `granted`), `abort_floor(…, floor_epoch)` (→ `idle`), `release_floor(…, speaker_lease_id)`, `revoke_floor(...)` (alias of grant to moderator), `elect_moderator(…, now) -> str | None`, `transition(…, new_state, *, output_epoch=None, reason=None, expected_owner_epoch) -> BroadcastDescriptor`, `request_stop(…, by_lease_id)`, `stop_requested(…) -> bool`, `bind_speaker_socket(…, lease_id, socket_id, floor_epoch) -> bool` (409 semantics: raises `SpeakerConnectionExists`), `unbind_speaker_socket`, `expire(…, now) -> list[ExpiryEvent]` (pending 60 s, owner lease 15 s, control 15 s, terminal 300 s), `list_leases`.
  - Exceptions in `broadcast/errors.py`: `BroadcastError(reason: BroadcastReason)`, `ViewerLimitReached`, `BroadcastTerminal`, `StaleVersion`, `FloorNotGranted`, `StaleFloorEpoch`, `SpeakerConnectionExists`, `NotModerator`, `NotSpeaker`, `NotOwner`.
  - `class InMemoryBroadcastRegistry(BroadcastRegistry)` with a single `asyncio.Lock` per broadcast, injectable `clock: Callable[[], float]` for deterministic TTL tests. **Invariants** (each enforced and tested): pending+active leases ≤ `max_viewers`; exactly one `moderator_lease_id`; at most one `speaker_lease_id`; first successful `reserve_viewer` sets moderator + initial speaker and returns `lease.admission_sequence == 1`; `grant_floor` requires `expected_version == version` else `StaleVersion`; only `granted`/`idle` → `switching` allowed; released lease IDs get a tombstone until `credential_expires_at` so re-use of that identity is refused; moderator departure → `elect_moderator` picks earliest `admission_sequence` among `confirmed` leases with fresh heartbeat; last departure → `state=ended`, `reason=audience_empty`.
- Tests `tests/voice/test_voice_broadcast_registry.py` parametrised over the in-memory registry (TASK-2953 reuses the same suite against Redis via a fixture).

**NOT in scope**: Redis implementation, LiveKit calls, HTTP.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/registry.py` | CREATE | ABC + `InMemoryBroadcastRegistry` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/errors.py` | CREATE | Typed exceptions carrying `BroadcastReason` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/__init__.py` | MODIFY | Re-export registry + errors |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_registry.py` | CREATE | Contract suite (fixture `registry` → in-memory) |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.broadcast.models import (  # TASK-2951 — verify it landed before starting
    BroadcastDescriptor, BroadcastState, FloorState, LeaseState, BroadcastReason,
    HandRequest, ParticipantPrincipal, ViewerLease, MAX_VIEWERS, PENDING_TTL_S,
    OWNER_LEASE_TTL_S, CONTROL_EXPIRY_S, TERMINAL_RETENTION_S, VIEWER_CREDENTIAL_TTL_S,
)
import asyncio, contextlib  # stdlib
```

### Existing patterns
- `packages/ai-parrot/src/parrot/voice/session.py:230` `_cancel_turn()` — cancellation-safe pattern with `contextlib.suppress(asyncio.CancelledError)`.
- Logging: `self.logger = logging.getLogger(__name__)` (see `room_manager.py:76`).

### Does NOT Exist
- ~~`RedisBroadcastRegistry`~~ — TASK-2953.
- ~~`parrot.memory.*` conversation memory as a registry~~ — unrelated; do not repurpose `RedisConversation`.
- ~~`RedisBroadcastForwarder` as a registry~~ (`output_transport.py:40`) — it is a pub/sub envelope forwarder only.

## Implementation Notes

- Make every mutating method take `now: float | None = None` and default to `self._clock()` so the Redis impl can pass server time.
- `reserve_viewer` on the **first** admission must atomically: set `moderator_lease_id`, `speaker_lease_id`, `floor_state=granted`, `floor_epoch=1`, and return `claim_needed=True` on the lease (or a `(lease, is_first)` tuple) so the caller performs `claim_owner` + producer startup **once**.
- `grant_floor(target=None)` = revoke → speaker becomes the moderator after `commit_floor`. Moderator reclaim = `grant_floor(target=moderator_lease_id)`.
- Never store PCM, tokens, AWS creds, or LiveAvatar access tokens in the descriptor.

## Acceptance Criteria

- [ ] 10 concurrent `reserve_viewer` via `asyncio.gather` on a fresh broadcast → exactly 10 leases, exactly one moderator, 11th raises `ViewerLimitReached`.
- [ ] Two concurrent `grant_floor` with the same `expected_version` → exactly one succeeds, the other raises `StaleVersion`; never two `speaker_lease_id`s.
- [ ] `grant_floor` → `switching` + `floor_epoch` incremented; `commit_floor` → `granted`; `abort_floor` → `idle`; audio with old epoch rejected (`StaleFloorEpoch`) by a `validate_audio_authority(descriptor, lease_id, floor_epoch, socket_id)` helper.
- [ ] Moderator leaves → earliest remaining confirmed lease elected; last leaves → `ended`.
- [ ] Owner lease expires after 15 s of no renew (fake clock); pending broadcast expires after 60 s.
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_registry.py -q` green; `ruff check` clean.

## Test Specification

```python
import asyncio, pytest
from parrot.integrations.liveavatar.broadcast import InMemoryBroadcastRegistry, errors

class FakeClock:
    def __init__(self): self.t = 1_000.0
    def __call__(self): return self.t

@pytest.fixture
def clock(): return FakeClock()

@pytest.fixture
def registry(clock): return InMemoryBroadcastRegistry(clock=clock)

async def test_first_admission_elects_single_moderator_under_race(registry): ...
async def test_eleventh_viewer_rejected(registry): ...
async def test_conflicting_grants_install_one_speaker(registry): ...
async def test_stale_epoch_audio_rejected(registry): ...
async def test_moderator_departure_elects_earliest(registry): ...
async def test_owner_lease_expires(registry, clock): ...
async def test_tombstone_blocks_identity_reuse(registry, clock): ...
```

## Agent Instructions
1. Read spec §2 sections named in Context. 2. Verify TASK-2951 models exist. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`, Completion Note.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
