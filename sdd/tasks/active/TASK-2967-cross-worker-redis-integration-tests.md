# TASK-2967: Cross-worker Redis integration tests, admission limit and LiveKit token/admission suite

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2962
**Parallel**: false
**Parallelism notes**: Test-only task; creates `tests/e2e/test_voicebot_multiroom_heygen_avatar.py` (deterministic + Redis-gated parts) and may extend the Redis registry test module. Can run alongside TASK-2965 (different files).

---

## Context

Spec §4 Integration Tests rows: "Cross-worker registry" (two independent service instances sharing real Redis: create on A, join/status/stop on B; never an eleventh viewer; owner death fences publication and cleans up), "LiveKit token/admission" (decode grants; viewers cannot publish; producer identities differ; disconnect/reconnect/replay do not bypass capacity), "Ten-viewer limit" through different HTTP workers, "Moderation races/departure". Module 7 deterministic/Redis half; AC2, AC3, AC4, AC7, AC12–AC14 server-side evidence.

## Scope

- `tests/e2e/test_voicebot_multiroom_heygen_avatar.py` (repo-root `tests/`, same gating style as `tests/e2e/test_conversation_history_redis_e2e.py`): skip whole module with reason "Redis not reachable — NOT VERIFIED" unless `PARROT_TEST_REDIS_URL` (default `redis://localhost:6379/3`) pings. Fixtures build **two** aiohttp apps (`worker A`, `worker B`) each with its own `BroadcastService` over its own `RedisBroadcastRegistry` (shared Redis, unique prefix), fake `LiveKitRoomManager` (records mint/create/remove/delete; returns decodable unsigned JWT-like tokens or real `LiveKitRoomManager` with dummy key/secret — real minting works offline), fake avatar/publisher factories, a Nova bot factory stub, and the routes from `register_voice_broadcast_routes` with a stub principal resolver keyed by `Authorization` header.
- Tests:
  - create on A → `GET` on B sees it; first `POST /viewers` on B elects moderator and starts the producer **on B**; A's `GET` shows `media_ready` after B's start.
  - 12 concurrent `POST /viewers` split across A and B → exactly 10 × 201, 2 × 409 `viewer_limit_reached`; exactly one producer start across both services (assert on fake factory call count).
  - Every `connection` token decodes with `canPublish=false`, `canPublishData=false`, unique `sub`; avatar and direct publisher identities differ from each other and from all viewers.
  - `DELETE viewers/{lease}` then a new `POST /viewers` reuses no identity; replaying the old `connection` token after leave is refused by the registry tombstone (`connection` → 410/404).
  - Moderator `POST stop` on A → producer owned by B stops within 1.5 s (poll `GET`), state `ended`; non-moderator stop → 403 on both workers.
  - Owner death: kill B's producer task without cleanup, advance the fake clock/`expire` → within ≤ 30 s simulated A's reconciler fences it, fake room manager saw `remove_participant` for every identity + `delete_room`, state `failed/owner_lost`.
  - Moderation races: concurrent conflicting `POST floor` from the moderator on A and B with the same `expected_version` → one 200 / one 409; two speaker sockets for one lease → second 409 (`speaker_connection_exists`) via the WS route on the other worker (relay path from TASK-2961 exercised with the worker registry pointing A→B over the test server URL).
  - Moderator leaves → earliest remaining lease elected; all `GET`s converge to the same `moderator_lease_id`.
- Emit a machine-readable summary to `artifacts/logs/feat-537-crossworker-<date>.json` (counts, timings) — no tokens.

**NOT in scope**: browsers (TASK-2968), real vendors (TASK-2969).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/e2e/test_voicebot_multiroom_heygen_avatar.py` | CREATE | Two-worker Redis integration suite |
| `artifacts/logs/feat-537-crossworker-*.json` | CREATE (runtime) | Evidence summary |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pytest, pytest_asyncio                                          # tests/e2e/test_conversation_history_redis_e2e.py:24-25 (pytest-asyncio 1.4.0; root pyproject has no asyncio_mode=auto → use @pytest.mark.asyncio or pytest_asyncio fixtures)
from aiohttp import web; from aiohttp.test_utils import TestServer, TestClient  # aiohttp 3.14.3 ; pattern tests/voice/test_voice_demo_avatar_browser.py:40
from parrot.handlers.voice_broadcast import register_voice_broadcast_routes    # TASK-2962
from parrot.integrations.liveavatar.broadcast.service import BroadcastService  # TASK-2961
from parrot.integrations.liveavatar.broadcast.redis_registry import RedisBroadcastRegistry  # TASK-2953
from parrot.integrations.liveavatar.broadcast.worker_transport import WorkerAddressRegistry  # TASK-2961
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager     # room_manager.py:47 (inline credentials ctor :66; tokens decodable via base64 — test_room_manager.py:82)
```

### Existing patterns
- Redis e2e fixture: `tests/e2e/test_conversation_history_redis_e2e.py:41-47` (`redis://localhost:6379/3`, unique `TEST_PREFIX`, ping assert, SCAN cleanup).
- Root pytest config: `pyproject.toml:211-230` (`--strict-markers`, `filterwarnings = error`, `testpaths=["tests"]`, markers `asyncio`, `real_llm`). Add no new marker here; use `pytest.skip`.

### Does NOT Exist
- ~~`fakeredis`~~ — not installed; real Redis or skip.
- ~~A shared in-process registry between "workers"~~ — the point is two independent `RedisBroadcastRegistry` instances.
- ~~Producer migration on owner death~~ — assert `failed/owner_lost`, not a restart.

## Implementation Notes

- Run A and B as two `TestServer`s in the same event loop; the worker registry must map worker ids to the servers' URLs so the relay works.
- Use `asyncio.gather` for races; assert **counts**, never ordering.
- Fake clock: inject a clock into both services and registries; call `service.run_reconciler_once(now)` to avoid sleeping.
- `filterwarnings=error` at root: make sure no `ResourceWarning`/`DeprecationWarning` leaks (close clients).

## Acceptance Criteria

- [ ] With Redis: all tests above pass; without Redis: module skipped with the NOT VERIFIED reason (never silently green).
- [ ] Exactly 10 admissions and exactly 1 producer start across two workers under a 12-way race.
- [ ] Token grants decoded: viewers subscribe-only, identities unique, producers distinct.
- [ ] Stop and owner-death fencing observed cross-worker within budgets; role convergence after moderator departure.
- [ ] Evidence JSON written; `ruff check tests/e2e/test_voicebot_multiroom_heygen_avatar.py` clean.

## Test Specification

```python
pytestmark = pytest.mark.asyncio

@pytest_asyncio.fixture
async def two_workers(redis_url): ...  # yields (clientA, clientB, fakes, clock)

async def test_create_on_a_join_on_b_starts_producer_once(two_workers): ...
async def test_twelve_way_admission_race_admits_ten(two_workers): ...
async def test_viewer_tokens_subscribe_only_and_unique(two_workers): ...
async def test_leave_and_replay_cannot_bypass_capacity(two_workers): ...
async def test_moderator_stop_cross_worker(two_workers): ...
async def test_owner_death_fenced_within_thirty_seconds(two_workers): ...
async def test_conflicting_grants_and_duplicate_speaker_socket(two_workers): ...
async def test_moderator_departure_elects_earliest(two_workers): ...
```

## Agent Instructions
1. Read spec §4 Integration Tests table + §5 AC2/3/4/7/12/13/14. 2. Verify landed APIs. 3. Index → `in-progress`. 4. Implement; run with a local Redis if available and say so. 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
