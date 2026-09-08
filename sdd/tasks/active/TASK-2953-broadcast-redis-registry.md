# TASK-2953: RedisBroadcastRegistry (cross-worker atomic admission, ownership, floor)

**Feature**: FEAT-537 — Nova VoiceBot avatar broadcast for multiple browsers
**Spec**: `sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2952
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Adds `broadcast/redis_registry.py` and a Redis-gated test module; reuses TASK-2952's contract suite. No shared production file with other tasks.

---

## Context

Spec §2: "persist scoped metadata, moderation and admission state in Redis so another worker can serve participants or request shutdown … Admission is atomic across workers: pending plus active reservations must never exceed ten." This is the production `BroadcastRegistry` (Module 2) and the substrate for AC2, AC7, AC12–AC14 across processes.

## Scope

- `broadcast/redis_registry.py`: `class RedisBroadcastRegistry(BroadcastRegistry)` built on `redis.asyncio.Redis` (lazy import, same style as `output_transport.py:62`). `from_url(redis_url, *, key_prefix="parrot:voice-broadcast")`.
- Key layout, namespaced by tenant + broadcast: `{prefix}:{tenant}:{bid}:descriptor` (JSON of `BroadcastDescriptor`, **minus** anything secret — there is nothing secret in it by construction), `…:leases` (hash lease_id → JSON `ViewerLease`), `…:tombstones` (zset identity → expiry), `…:hands` (zset lease_id → sequence), `…:owner` (string `worker_id:epoch`, TTL 15 s), `…:stop` (flag), `…:speaker_socket` (string), `{prefix}:{tenant}:index` (set of live broadcast ids for reconciliation).
- **Atomicity**: every compound operation (`reserve_viewer`, `claim_owner`, `grant_floor`/`commit_floor`/`abort_floor`, `release_viewer` + succession, `elect_moderator`, `transition`, `bind_speaker_socket`) is a single **Lua script** (`redis.register_script` / `Script.__call__`) with CAS on `version`/`owner_epoch`/`floor_epoch`. No read-modify-write from Python. TTLs: pending 60 s, owner 15 s (`SET … PX … NX` then `PEXPIRE` on renew only if value matches), terminal 300 s (`EXPIRE` the whole key family on `ended|failed`).
- Never store PCM, credentials, AWS keys, LiveAvatar access tokens, or worker network addresses; store `owner_worker_id` (opaque id) only — address resolution is TASK-2961's registry-of-workers concern.
- `expire(now)` uses Redis server time (`TIME`) not client clock; `heartbeat_control` writes do **not** bump `version` (spec: lease heartbeat writes do not increment the public version).
- Tests `tests/voice/test_voice_broadcast_redis_registry.py`: reuse the TASK-2952 suite by importing its test functions through a shared `registry` fixture parametrised with the Redis backend when `PARROT_TEST_REDIS_URL` is set (default `redis://localhost:6379/3` per `tests/e2e/test_conversation_history_redis_e2e.py`), unique key prefix per run, cleanup via `SCAN`+`DEL`; skip with reason "Redis not reachable — NOT VERIFIED" otherwise. Add cross-instance tests: two `RedisBroadcastRegistry` objects (separate connections) racing 12 admissions → exactly 10; owner claim raced → one winner; stop requested on A visible on B.

**NOT in scope**: pub/sub wake-ups (optional later), worker address registry, HTTP.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/redis_registry.py` | CREATE | Lua-backed registry |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/broadcast/__init__.py` | MODIFY | Lazy export `RedisBroadcastRegistry` (no hard `redis` import at package import) |
| `packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_redis_registry.py` | CREATE | Redis-gated contract + cross-instance tests |
| `packages/ai-parrot-integrations/pyproject.toml` | MODIFY | Add extra `broadcast = ["ai-parrot-integrations[liveavatar]", "redis>=5.0"]` (redis today only in `msteams` extra, line 56) |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import redis.asyncio as aioredis   # lazy, inside from_url — pattern: output_transport.py:66 ; installed redis 5.2.1
from parrot.integrations.liveavatar.broadcast.registry import BroadcastRegistry, InMemoryBroadcastRegistry  # TASK-2952
from parrot.integrations.liveavatar.broadcast import errors, models                                           # TASK-2951/2952
```

### Existing Signatures / patterns
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_transport.py:62
@classmethod
def from_url(cls, redis_url: str, *, channel: str = DEFAULT_OUTPUT_CHANNEL) -> "RedisBroadcastForwarder":
    import redis.asyncio as aioredis
    return cls(aioredis.from_url(redis_url, decode_responses=True), channel=channel)
# :89 aclose(): close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)

# tests/e2e/test_conversation_history_redis_e2e.py:41-47 — real Redis fixture style: unique prefix, ping check, cleanup
```
- `pyproject.toml` (integrations) `[project.optional-dependencies]` starts at line 33; `liveavatar` extra at 94-97; `msteams` has `"redis>=5.0"` at 56.

### Does NOT Exist
- ~~`fakeredis`~~ — NOT installed in the venv; do not add it. Use real Redis gated by env, else skip.
- ~~`RedisConversation` as a registry~~ — conversation memory, unrelated.
- ~~`redis.asyncio.Redis.watch()`-style optimistic transactions for this~~ — use Lua scripts (single round trip, atomic across workers).

## Implementation Notes

- Keep Lua scripts as module-level string constants with a short comment each; register once per client (`self._scripts = {name: client.register_script(src)}`).
- Descriptor JSON via `model_dump_json()` / `model_validate_json()`. Version check inside Lua: `if cjson.decode(...)["version"] ~= tonumber(ARGV[1]) then return {err="stale_version"} end` → map to `errors.StaleVersion`.
- `claim_owner`: `SET owner "<worker>:<epoch>" NX PX 15000` where epoch = `INCR …:owner_epoch`. `renew_owner` compares value before `PEXPIRE`.
- Cleanup: on `ended|failed` set 300 s TTL on all keys of the family; `SREM` from index after expiry in `expire()`.

## Acceptance Criteria

- [ ] Entire TASK-2952 contract suite passes against Redis (when reachable).
- [ ] Cross-instance: 12 concurrent admissions over 2 registries → 10 leases; one owner; stop visible across instances within one `get()`.
- [ ] Redis contents never include strings `token`, `secret`, `ws_url` (test scans all keys of the family).
- [ ] `import parrot.integrations.liveavatar.broadcast` works without `redis` installed (lazy).
- [ ] `pytest packages/ai-parrot-integrations/tests/voice/test_voice_broadcast_redis_registry.py -q` green or skipped-with-reason; `ruff check` clean.

## Test Specification

```python
import os, uuid, pytest
REDIS_URL = os.environ.get("PARROT_TEST_REDIS_URL", "redis://localhost:6379/3")

@pytest.fixture
async def redis_registry():
    from parrot.integrations.liveavatar.broadcast.redis_registry import RedisBroadcastRegistry
    reg = RedisBroadcastRegistry.from_url(REDIS_URL, key_prefix=f"t537:{uuid.uuid4().hex[:8]}")
    try:
        await reg.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable at {REDIS_URL} — NOT VERIFIED: {exc}")
    yield reg
    await reg.purge_all_for_tests(); await reg.aclose()

async def test_two_instances_never_admit_eleventh(redis_registry): ...
async def test_owner_claim_race_single_winner(redis_registry): ...
async def test_no_secret_like_values_in_redis(redis_registry): ...
```

## Agent Instructions
1. Read spec §2 "Ownership, admission and cleanup". 2. Verify TASK-2952 landed. 3. Index → `in-progress`. 4. Implement + tests (run with a local Redis if available; state clearly in the note if skipped). 5. Move to `completed/`, index → `done`.

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
