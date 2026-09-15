# TASK-2951: Broadcast data models and public-state projection

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Creates only the new `broadcast/{__init__,models}.py` files and their test; shares no file with TASK-2950/2954/2955/2956/2957. Safe to run in a separate worktree.

---

## Context

Implements spec §2 "Data Models" (Module 2 foundation). Every later module (registry, session, handler, HTTP API, browser) serialises these contracts. The public projection is the **only** thing that may reach a browser; getting the "never leaks credentials" invariant right here protects AC3.

## Scope

- Create package `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/` with `__init__.py` (re-exports) and `models.py` containing Pydantic v2 models:
  - Enums: `BroadcastState` (`pending|starting|avatar|audio_only|stopping|ended|failed`), `FloorState` (`idle|switching|granted`), `LeaseState` (`pending|active|leaving`), `BroadcastReason` (safe reason codes: `viewer_limit_reached`, `speaker_connection_exists`, `floor_not_granted`, `stale_floor_epoch`, `stale_version`, `avatar_startup_timeout`, `avatar_control_lost`, `avatar_track_lost`, `nova_failure`, `livekit_failure`, `owner_lost`, `stopped_by_moderator`, `audience_empty`, `pending_expired`).
  - `HandRequest(lease_id, display_name, sequence, requested_at)`.
  - `ParticipantPrincipal(user_id, tenant_id, agent_id, display_name, roles)` — the scoped authenticated principal every API/WS op is checked against (the existing `AuthenticatedUser` carries `user_id/username/email/roles`; this model adds tenant/agent scope).
  - `BroadcastDescriptor` — all fields listed in spec §2 table incl. `moderator_lease_id`, `speaker_lease_id`, `floor_epoch`, `floor_state`, `hand_requests: list[HandRequest]`, `voice_session_id`, `room_name`, `owner_worker_id`, `owner_epoch`, `version`, `state`, `output_epoch`, `avatar_identity`, `direct_identity`, `selected_audio_track_id`, `selected_video_track_id`, `max_viewers: int = 10` (ge=1, le=10), `admission_sequence`, timestamps, `failure_reason: BroadcastReason | None`, `liveavatar_session_id: str | None` (audit only; never a token).
  - `BroadcastPublicState` + `BroadcastDescriptor.to_public_state()` — includes viewer count/limit, moderator/speaker **display IDs** (lease IDs, never user IDs/emails), floor state/epoch, hand queue, `media_ready`, `state`, `version`, `output_epoch`, selected identity/track IDs, `reason`. Must reject (model-level `model_validator`) any field named like `*token*`, `*secret*`, `ws_url`, `owner_worker_address`.
  - `ViewerLease(lease_id, principal: ParticipantPrincipal, livekit_identity, state, credential_expires_at, admission_deadline, confirmed, admission_sequence, last_control_heartbeat, speaker_socket_id: str | None)`.
  - `ViewerJoinResponse(public_state, lease_id, livekit_url, room, client_token, expires_at)`.
  - `BroadcastAudioFrame(owner_epoch, speaker_lease_id, floor_epoch, turn_id, output_epoch, sequence, pcm: bytes, sample_count)` with validators: even byte length, `sample_count == len(pcm)//2`, non-empty, ≤ 96_000 bytes.
- Constants module-level: `MAX_VIEWERS = 10`, `PENDING_TTL_S = 60`, `OWNER_LEASE_TTL_S = 15`, `OWNER_RENEW_S = 5`, `CONTROL_HEARTBEAT_S = 5`, `CONTROL_EXPIRY_S = 15`, `TERMINAL_RETENTION_S = 300`, `VIEWER_CREDENTIAL_TTL_S = 60`, `HANDOFF_BARRIER_TIMEOUT_S = 3.0`, `AVATAR_STARTUP_DEADLINE_S = 15.0`, `MAX_QUEUED_PCM_BYTES = 96_000`, `INPUT_SAMPLE_RATE = 16_000`, `OUTPUT_SAMPLE_RATE = 24_000`.
- Tests in `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_models.py`.

**NOT in scope**: registry logic, Redis, HTTP, JS.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/__init__.py` | CREATE | Re-export models/constants |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/models.py` | CREATE | Pydantic contracts + projection |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_models.py` | CREATE | Unit tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # verified: liveavatar/models.py:15 (pydantic v2 style used throughout)
from parrot.core.ws_auth import AuthenticatedUser  # packages/ai-parrot/src/parrot/core/ws_auth.py:34 (dataclass: user_id, username, email, roles, permissions, raw_payload)
from parrot.integrations.liveavatar.models import LiveKitRoomTokens  # models.py:58 (livekit_url, room, client_token, agent_token) — NEVER serialise whole model to a viewer
```

### Existing Signatures to Follow
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/models.py:18-56
class LiveAvatarConfig(BaseModel):
    api_key: str = Field(..., description="...")   # style: Field(..., description=...) on every attr
```

### Does NOT Exist
- ~~`parrot.integrations.liveavatar.broadcast`~~ — you are creating it.
- ~~`ParticipantPrincipal`, `BroadcastDescriptor`, `BroadcastPublicState`, `ViewerLease`, `ViewerJoinResponse`, `BroadcastAudioFrame`~~ — new.
- ~~A tenant field on `AuthenticatedUser`~~ — it has none; tenant/agent scope comes from the resolver (TASK-2962) and lives on `ParticipantPrincipal`.

## Implementation Notes

- Pydantic v2: use `model_config = ConfigDict(frozen=False, extra="forbid")`; `to_public_state()` is a plain method returning `BroadcastPublicState`.
- `BroadcastAudioFrame.pcm: bytes` — validate with `@field_validator("pcm")`; reject odd lengths with `ValueError("pcm must be 16-bit aligned")`.
- Display names: `HandRequest.display_name` must be sanitised (`str.strip()[:64]`, fallback `"participant"`).
- Google-style docstrings on every class; `from __future__ import annotations`.

## Acceptance Criteria

- [ ] `from parrot.integrations.liveavatar.broadcast import BroadcastDescriptor, BroadcastPublicState, ViewerLease, ViewerJoinResponse, BroadcastAudioFrame, ParticipantPrincipal` works.
- [ ] `to_public_state()` output never contains keys matching `token|secret|ws_url|api_key|worker` (test asserts recursively over `model_dump()`).
- [ ] `max_viewers > 10` and odd-length PCM raise `ValidationError`.
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_models.py -q` passes; `ruff check` clean.

## Test Specification

```python
import pytest
from pydantic import ValidationError
from parrot.integrations.liveavatar.broadcast import (
    BroadcastDescriptor, BroadcastAudioFrame, BroadcastState, FloorState, MAX_VIEWERS,
)

def _descriptor(**kw) -> BroadcastDescriptor: ...

def test_public_state_has_no_secret_like_keys():
    dumped = _descriptor().to_public_state().model_dump()
    forbidden = ("token", "secret", "ws_url", "api_key", "worker")
    def walk(o): ...
    assert not any(any(f in k.lower() for f in forbidden) for k in walk(dumped))

def test_max_viewers_cannot_exceed_ten():
    with pytest.raises(ValidationError):
        _descriptor(max_viewers=11)

def test_audio_frame_rejects_odd_length():
    with pytest.raises(ValidationError):
        BroadcastAudioFrame(owner_epoch=1, speaker_lease_id="l", floor_epoch=1, turn_id="t", output_epoch=1, sequence=0, pcm=b"\x00\x01\x02", sample_count=1)

def test_state_enum_values():
    assert {s.value for s in BroadcastState} == {"pending","starting","avatar","audio_only","stopping","ended","failed"}
```

## Agent Instructions
1. Read spec §2 "Data Models" + "New Public Interfaces".
2. Verify imports above. 3. Index → `in-progress`. 4. Implement + tests. 5. Move to `completed/`, index → `done`, fill Completion Note.

## Completion Note

**Completed by**: `sdd-worker` (autonomous session)
**Date**: 2026-09-08
**Status**: done

**Notes**:

- Created `broadcast/__init__.py` (re-exports) and `broadcast/models.py` with every
  contract and constant the task listed: `BroadcastState`, `FloorState`, `LeaseState`,
  `BroadcastReason` (all 14 codes), `HandRequest`, `ParticipantPrincipal`,
  `BroadcastDescriptor`, `BroadcastPublicState`, `ViewerLease`, `ViewerJoinResponse`,
  `BroadcastAudioFrame`, plus the 13 module-level constants.
- **AC3 invariant is enforced structurally, not by convention.**
  `BroadcastPublicState` carries `extra="forbid"` (stops a *caller* smuggling a token
  in) **and** a `model_validator(mode="after")` that scans its own declared field names
  for `token|secret|ws_url|api_key|worker|credential|password` and raises. That means a
  future maintainer who adds a leaky field breaks every test that constructs a public
  state, rather than leaking silently. Tested by
  `test_public_state_has_no_secret_like_keys` (recursive walk over `model_dump()`) and
  `test_public_state_omits_internal_descriptor_fields`.
- `to_public_state(*, viewer_count=0, media_ready=None)`: seat occupancy lives in the
  lease records (registry, TASK-2952/2953), not on the descriptor — the spec §2
  descriptor table lists no viewer-count field — so the registry supplies it and a bare
  descriptor projects `0`. The task's own test scaffold calls `to_public_state()` with
  no arguments, which still works. `media_ready` is derived (`state ∈ {avatar,
  audio_only}` **and** `room_name` set) with a caller override.
- Added `BroadcastDescriptor.selected_identity` as a derived property rather than a
  stored field: in `avatar` the avatar publisher is authoritative, in `audio_only` the
  direct publisher is, and in every other state there is no authoritative source (so
  browsers stay muted). Storing it would let the two drift apart.
- Two helper classmethods justify the task's two "Verified Imports" and enforce
  invariants at the only place they can be enforced:
  `ParticipantPrincipal.from_authenticated_user(user, *, tenant_id, agent_id)` —
  tenant/agent scope is taken from the *caller's* trusted resolution, deliberately not
  read off the token payload — and `ViewerJoinResponse.from_tokens(...)`, the sole
  sanctioned path from `LiveKitRoomTokens` to a client response, which structurally
  drops `agent_token`. `test_viewer_join_response_drops_the_publisher_token` asserts the
  publisher JWT is nowhere in the dump.
- `BroadcastAudioFrame` validates: non-empty, 16-bit aligned (`"pcm must be 16-bit
  aligned"`), ≤ `MAX_QUEUED_PCM_BYTES` (96 000), and `sample_count == len(pcm)//2`.
  Added `is_current(owner_epoch, floor_epoch, output_epoch, turn_id=None)` so the
  fencing tuple is checked in one place by every downstream consumer instead of being
  re-implemented per call site.
- Display names sanitised via a shared `_safe_display_name()` (`strip()[:64]`, fallback
  `"participant"`) applied by `field_validator` on both `ParticipantPrincipal` and
  `HandRequest`.
- Tests: `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_models.py -q`
  → **28 passed**. `ruff check` clean on the new package and the test module.
- The `AVATAR_STARTUP_DEADLINE_S` / `HANDOFF_BARRIER_TIMEOUT_S` / `MAX_QUEUED_PCM_BYTES`
  constants are the *unverified defaults* TASK-2950 flagged (the live gate did not run).
  They are module constants precisely so downstream tasks can make them configurable
  knobs without touching call sites.

**Deviations from spec**: none. Two additions beyond the literal field lists, both
inside scope and both invariant-enforcing rather than architectural: the derived
`selected_identity` property and `BroadcastAudioFrame.is_current()`. No registry, Redis,
HTTP or JS logic was added.
