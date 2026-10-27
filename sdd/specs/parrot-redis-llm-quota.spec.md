---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [parrot-formdesigner, docs]
tags: [formdesigner, llm-quota, redis, rate-limit, multi-worker]
---

# Feature Specification: Shared Redis backend for the FormDesigner LLM quota

**Feature ID**: FEAT-748
**Date**: 2026-10-25
**Author**: Juan Ruffato (Trocdigital / FieldSync), for Jesus Lara's review
**Status**: draft
**Target version**: next `parrot-formdesigner` release (Jesus decides the number)

---

## 1. Motivation & Business Requirements

### Problem Statement

`LLMQuota` (FEAT-728, `services/llm_quota.py`) bounds the LLM-backed form calls
per `{tenant}:{form_uid}:{identity}`. The only backend shipped is
`InProcessSlidingWindow`, whose state lives in one worker. The package's own docs
state the consequence and the intended fix:

> With **N gunicorn workers**, the effective limit is **N × configured limit**. [...]
> The `LLMQuotaBackend` Protocol exists exactly to allow a shared backend
> (e.g., Redis) to be plugged in later.
> — `docs/formdesigner-llm-validation-enforcement.md` §6.2, spec FEAT-728 §8 Q2

FieldSync needed that shared backend for FEAT-809 (enforced LLM validation on
execution submit, a per-user budget that must hold across pods), so it wrote one
**inside FieldSync** (`fieldsync/domains/execution/submit_audit/quota.py`, ~110
lines, tested against a real Redis). That is the wrong home: any consumer of
`parrot-formdesigner` with more than one worker has the same problem, and the
Protocol seam that was left for it is in this package.

This spec proposes **lifting that backend into `parrot-formdesigner`** so FieldSync
can delete its copy and every consumer gets a correct multi-worker quota by passing
one object.

It also lifts the one other piece FieldSync had to subclass `LLMQuota` for:
`LLMQuota.identity()` keys on `request["session"]["id"]`, i.e. per **session**. N
devices of one user get N budgets and a re-login resets the budget. FieldSync's
authenticated user lives elsewhere on the request, so it overrode `identity()`.
A one-argument hook removes the need to subclass.

### Goals

- G1. `RedisSlidingWindow` — an `LLMQuotaBackend` whose window is shared by every
  worker/pod that points at the same Redis.
- G2. Atomic: two workers can never both take the last slot (one server-side step
  per call).
- G3. `ping()` on the backend and on `LLMQuota`, so a host can report limiter health
  without reaching into private state.
- G4. `LLMQuota(identity_resolver=...)` so a host can key the quota on its own notion
  of caller (typically the user id) without subclassing.
- G5. No behaviour change for existing consumers: the default stays
  `InProcessSlidingWindow`, the default identity rule is untouched, and importing
  `parrot_formdesigner` still does not require `redis`.

### Non-Goals (explicitly out of scope)

- Changing any default (the default backend stays in-process; nothing turns Redis on
  by itself).
- A second algorithm (token bucket, fixed window) or per-form limits configured from
  the form schema (FEAT-728 AC14: a tenant must never raise its own limit).
- Quota for anything other than the LLM-backed form calls.
- Redis Cluster / Sentinel specifics beyond "a `redis.asyncio.Redis` client is passed
  in" (see §8 Q3).
- The FieldSync-side removal. It follows this release and is listed in §7 only so
  the reviewer can see what disappears.

---

## 2. Architectural Design

### Overview

A new module `services/llm_quota_redis.py` holds `RedisSlidingWindow`. It is a sorted
set per key (score = timestamp in integer milliseconds, member = a unique token),
operated by **one Lua script** per `acquire`:

1. read the Redis server clock (`TIME`) — never the worker's, so clock skew between
   pods cannot skew the window;
2. drop members older than the window (`ZREMRANGEBYSCORE`);
3. if fewer than `limit` remain: record this call, refresh the key TTL, allow;
4. otherwise deny, reporting the oldest hit so `Retry-After` is honest.

A `MULTI` cannot do this (it cannot branch on `ZCARD`), and a non-atomic
read-then-write lets two workers both take the last slot. Denied calls are **not**
recorded, so a client hammering a closed window does not extend its own lockout.

The key written to Redis is `"{prefix}" + sha256(key)`, so the caller identity (user
id, IP) and form uid never appear in Redis in the clear. Every key carries a TTL of
`ceil(window_s)`, so memory is self-bounding without the LRU the in-process backend
needs.

**Failure semantics are unchanged and stay where they are.** `RedisSlidingWindow`
lets Redis exceptions propagate; `LLMQuota.acquire` already catches any backend
exception, logs a WARNING and **allows** the call (`llm_quota.py:141`, "a limiter
outage must not take the submit path down"). This spec keeps that contract and
adds a test that pins it end to end with a dead Redis.

`LLMQuota.identity()` gains an optional first step: if an `identity_resolver` was
given and returns a non-empty string, that string is the identity. Otherwise the
existing rule runs byte for byte (session id, guarded forwarded-for, `request.remote`,
`"anonymous"`).

### Component Diagram

```
setup_form_api(llm_quota=LLMQuota(RedisSlidingWindow(redis), identity_resolver=fn))
        │
        ▼
LLMQuota.acquire(request, tenant, form_uid)
        │  key = "{tenant}:{form_uid}:{identity(request)}"
        ▼
RedisSlidingWindow.acquire(key, limit, window_s) ──EVALSHA──▶ Redis (one Lua step)
        │
        └── raises ──▶ LLMQuota logs WARNING, allows the call (unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LLMQuotaBackend` Protocol | implements | `acquire(key, *, limit, window_s) -> QuotaDecision`; Protocol itself unchanged |
| `LLMQuota` | extends | adds `identity_resolver` kwarg and `ping()`; no signature break |
| `QuotaDecision` | returns | `retry_after_s >= 1` whenever denied, like `InProcessSlidingWindow` |
| `setup_form_api(llm_quota=...)` | unchanged | already accepts any `LLMQuota` (`api/routes.py:228`) |
| `pyproject.toml` `redis` extra | reuses | `redis>=4.5` already declared; the module imports `redis` lazily |

### Data Models

None new. `QuotaDecision` is reused as is.

### New Public Interfaces

```python
class RedisSlidingWindow:                      # parrot_formdesigner.services.llm_quota_redis
    def __init__(self, redis: "Redis", *, key_prefix: str = "parrot:llmq:") -> None: ...
    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision: ...
    async def ping(self) -> bool: ...          # never raises

class LLMQuota:                                # parrot_formdesigner.services.llm_quota
    def __init__(..., identity_resolver: Callable[["web.Request"], str | None] | None = None) -> None: ...
    async def ping(self) -> bool: ...          # never raises; True for a backend with no ping
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Redis backend | yes | Lua script, key scheme, integer-ms scores, retry-after maths and error contract fixed in §2 and §7 | — |
| M2: `ping()` + `identity_resolver` on `LLMQuota` | yes | exact semantics fixed in §2 | — |
| M3: Docs + changelog | yes | replace §6.2 "known limitation" with the Redis recipe | — |

### Module 1: Redis backend
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota_redis.py` (new)
- **Responsibility**: shared, atomic sliding window behind the `LLMQuotaBackend` Protocol.
- **Depends on**: `services/llm_quota.py` (`QuotaDecision`, `LLMQuotaBackend`).
- **Interface Skeleton**:
  ```python
  # services/llm_quota_redis.py  (new)
  KEY_PREFIX = "parrot:llmq:"

  class RedisSlidingWindow:  # satisfies LLMQuotaBackend
      """ONE window shared by every worker that uses the same Redis.

      Redis exceptions propagate on purpose: ``LLMQuota.acquire`` logs a WARNING and
      allows the call (a limiter outage never fails a submit).
      """
      def __init__(self, redis: "Redis", *, key_prefix: str = KEY_PREFIX) -> None:
          """Register the Lua script once (redis-py calls it by EVALSHA, reloading on NOSCRIPT)."""
      async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
          """Charge one call; denied => ``retry_after_s >= 1`` from the oldest hit."""
      async def ping(self) -> bool:
          """True when Redis answers PING; any exception => False (an outage is a state, not an error)."""
  ```

### Module 2: `ping()` and `identity_resolver` on `LLMQuota`
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py` (modifies)
- **Responsibility**: host-supplied identity; limiter health without private access.
- **Depends on**: Module 1 (only for the `ping` convention; no import).
- **Interface Skeleton**:
  ```python
  # services/llm_quota.py  (modifies LLMQuota, line 86)
  class LLMQuota:
      def __init__(self, backend=None, *, enabled=True, limit=10, window_s=60.0,
                   trust_forwarded_for=False,
                   identity_resolver: Callable[["web.Request"], str | None] | None = None) -> None: ...
      def identity(self, request) -> str:
          """``identity_resolver(request)`` when it returns a non-empty str; else the existing rule.

          A resolver that raises is treated as "unknown caller" (logged at DEBUG, falls back)."""
      async def ping(self) -> bool:
          """``backend.ping()`` when the backend has one, else True (in-process is always reachable).
          Never raises."""
  ```

### Module 3: Docs and changelog
- **Path**: `docs/formdesigner-llm-validation-enforcement.md` (repo-level `docs/`), `packages/parrot-formdesigner/CHANGELOG.md`
- **Responsibility**: §6.2 stops calling per-worker quota "a known limitation to fix later" and documents the Redis recipe and the identity hook.
- **Depends on**: Modules 1-2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_identity_resolver_wins` | M2 | resolver returns `"user:7"` → that is the identity, session id ignored |
| `test_identity_resolver_none_falls_back` | M2 | resolver returns `None`/`""` → session id, then IP, then `"anonymous"` as today |
| `test_identity_resolver_raises_falls_back` | M2 | resolver raises → falls back, no exception escapes |
| `test_identity_default_unchanged` | M2 | no resolver → byte-identical to current behaviour (existing tests stay green) |
| `test_llmquota_ping_in_process_true` | M2 | `InProcessSlidingWindow` has no `ping` → `True` |
| `test_llmquota_ping_backend_exception_false` | M2 | backend `ping` raises → `False`, no raise |

### Integration Tests (real Redis; skipped with an explicit reason when none is reachable)
| Test | Description |
|---|---|
| `test_allows_up_to_limit_then_denies` | `limit=3`: 3 allowed, 4th denied with `retry_after_s >= 1` |
| `test_window_slides` | after the window passes, a slot frees (short window, no mock clock: the clock is Redis's) |
| `test_denied_calls_are_not_recorded` | hammering a closed window does not delay the reopening |
| `test_two_instances_share_one_limit` | two `RedisSlidingWindow` on the same Redis enforce ONE limit |
| `test_concurrent_acquire_never_overshoots` | N concurrent acquires with `limit=k` allow exactly `k` |
| `test_keys_are_hashed_and_have_ttl` | no raw identity in any key; every key has a TTL ≤ `ceil(window_s)` |
| `test_limit_zero_denies_with_full_window_wait` | parity with `InProcessSlidingWindow` (empty window ⇒ honest wait) |
| `test_redis_down_through_llmquota_allows_and_warns` | dead port ⇒ `LLMQuota.acquire` allows and logs one WARNING (the fail-open contract, end to end) |
| `test_ping_true_and_false` | live ⇒ `True`; dead ⇒ `False`, never raises |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_redis.py
- packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_identity_ping.py
- packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py
markers: none

### Test Data / Fixtures
```python
@pytest.fixture
async def redis_client():
    """A real redis.asyncio client on DB 15; skips with a reason when unreachable.
    Deletes only the keys the test created (never FLUSHDB)."""
```
`fakeredis` is not installed in this repo and cannot run Lua without `lupa`, so a
dict stub would test nothing about the script. These tests need a real Redis.

### E2E Scenarios

Policy: `none` — a library backend with unit and real-Redis integration coverage; no
HTTP surface of its own (`test_llm_quota_http.py` already covers the handlers and is
in the contract above).

---

## 5. Acceptance Criteria

- [ ] AC1. `RedisSlidingWindow` satisfies `LLMQuotaBackend` (passes where a backend is typed, e.g. `LLMQuota(backend=RedisSlidingWindow(...))`).
- [ ] AC2. Two workers on one Redis enforce one limit; N concurrent acquires with `limit=k` allow exactly `k` (mutation: a non-atomic read-then-write makes the concurrency test RED).
- [ ] AC3. Denied ⇒ `retry_after_s >= 1`, computed from the oldest hit and Redis's clock; denied calls are not recorded.
- [ ] AC4. Keys are `prefix + sha256(key)`; none contains the raw identity or form uid; every key has a TTL.
- [ ] AC5. A Redis outage through `LLMQuota` allows the call and logs a WARNING (fail-open contract unchanged).
- [ ] AC6. `LLMQuota(identity_resolver=...)` follows §2; with no resolver, behaviour is byte-identical (every existing quota test passes unmodified).
- [ ] AC7. `ping()` exists on the backend and on `LLMQuota`, never raises.
- [ ] AC8. `import parrot_formdesigner` and `import parrot_formdesigner.services.llm_quota` work without the `redis` package installed.
- [ ] AC9. Docs §6.2 replaced; CHANGELOG entry; the `redis` extra documented as the way to enable it.
- [ ] AC10. No change to any default: `setup_form_api` without `llm_quota` still builds the in-process one.

---

## 6. Codebase Contract

Verified against `ai-parrot` `dev` at `c971d247c`.

### Verified Imports
```python
from parrot_formdesigner.services.llm_quota import (   # llm_quota.py:24 (__all__)
    LLMQuota, LLMQuotaBackend, InProcessSlidingWindow, QuotaDecision,
)
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py
class QuotaDecision(BaseModel):                       # line 29
    allowed: bool
    retry_after_s: int = Field(default=0, ge=0)
class LLMQuotaBackend(Protocol):                      # line 36
    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision: ...  # line 39
class InProcessSlidingWindow:                         # line 44
    async def acquire(self, key, *, limit, window_s) -> QuotaDecision                         # line 58
class LLMQuota:                                       # line 86
    def __init__(self, backend=None, *, enabled=True, limit=10, window_s=60.0,
                 trust_forwarded_for=False)           # line 89
    def identity(self, request) -> str                # line 105
    async def acquire(self, request, *, tenant, form_uid) -> QuotaDecision  # line 141 (catches any backend exception, WARNING + allow)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `RedisSlidingWindow` | `LLMQuota(backend=...)` | constructor arg | `llm_quota.py:89` |
| `LLMQuota` instance | `setup_form_api(llm_quota=...)` | kwarg, stashed on the app | `api/routes.py:228,397-399` |
| quota charge | submit / validate handlers | `quota_check=lambda: self._llm_quota().acquire(...)` | `api/handlers.py:1438,2154` |

### Does NOT Exist (Anti-Hallucination)
- ~~`RedisSlidingWindow` in `parrot_formdesigner`~~ — only in FieldSync today (`fieldsync/domains/execution/submit_audit/quota.py`); the reference implementation to port.
- ~~`LLMQuota.ping` / `LLMQuota.identity_resolver`~~ — added by this spec.
- ~~`fakeredis`~~ — not installed; cannot execute the Lua step.
- ~~A Redis URL setting for the quota~~ — the backend takes a client; the package has no such config key.

### Edit Sites (Blueprint Anchors)

Verified against: `c971d247c`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota_redis.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py` | MODIFY | `class LLMQuota:` | `llm_quota.py:86` | 1 |
| `docs/formdesigner-llm-validation-enforcement.md` | MODIFY | `### 6.2 Gotcha: the quota is per worker` | `:259` | 1 |
| `packages/parrot-formdesigner/CHANGELOG.md` | MODIFY | `## [Unreleased]` | `:5` | 2 (quote the first, `:5`) |
| `packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_redis.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_identity_ping.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Lazy `redis` import inside the new module only (mirror `services/partial_saves.py:240`); `llm_quota.py` stays import-light.
- Google docstrings, strict type hints, `self.logger`; async throughout.
- **Reference implementation** (battle-tested, ported not rewritten): FieldSync `submit_audit/quota.py` — the Lua script, key hashing, retry-after maths and `ping()`. It passed 5 real-Redis tests and a shared-limit mutation check (per-instance state turns the two-instance test RED), and went through FEAT-809's code review.

### Known Risks / Gotchas
- **Integer milliseconds.** Scores and script arguments must be integers; a float rendered with `%.14g` keeps only ~0.1 ms of a ms-epoch timestamp and silently coarsens the window. The reference script formats with `%d`.
- **`redis.replicate_commands()`.** The script calls it first because on Redis < 5 (or with script-effects replication off) a write after the non-deterministic `TIME` is refused, and the quota would then fail open forever. On Redis ≥ 7 it is a deprecated no-op; verified working on Redis 8.10.1. If the package's minimum Redis is ≥ 7, it can be dropped (§8 Q2).
- **Window start is Redis's clock**, not the worker's: `retry_after_s` is computed from values the script returns, never from `time.time()`.
- **Key prefix change for FieldSync.** FieldSync's keys are `fieldsync:llmq:*`; the lifted default is `parrot:llmq:*`. FieldSync may pass `key_prefix="fieldsync:llmq:"` to keep live windows, or accept a one-time reset (windows are 60 s, so a reset is harmless).
- **Identity resolver contract.** It returns the *final* identity string (FieldSync returns `"user:<id>"`); the package adds no prefix. A resolver must be cheap and synchronous (it runs on the request path).
- **Fail-open is a product decision made in FEAT-728**, not here. This spec only pins it with a test.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `redis` | `>=4.5` (existing `redis` extra) | `redis.asyncio`, `register_script` |

### What FieldSync deletes once this ships (for the reviewer; not in scope)
- `RedisSlidingWindow` and its Lua script (`submit_audit/quota.py`, ~65 lines).
- `UserScopedLLMQuota` (the subclass) → a 6-line `identity_resolver` function around the existing `_session_user_id`.
- FieldSync's own backend tests, replaced by this package's.
- `pyproject.toml` pin bump to the release that carries this (same lockstep rule as the 1.3.0 bump).

---

## 8. Open Questions

- [ ] Q1. Module name/location: `services/llm_quota_redis.py` (proposed; keeps `redis` out of `llm_quota.py`) vs. a `services/quota/` package. — *Owner: Jesus*
- [ ] Q2. Minimum supported Redis version: keep `redis.replicate_commands()` (safe on < 5) or drop it (≥ 7 only)? Proposed: keep, it costs nothing. — *Owner: Jesus*
- [ ] Q3. Accept a `redis.asyncio.Redis` client only (proposed; the host owns the pool, as FieldSync does), or also a `redis_url` with lazy connect like `PartialSaveStore`? A URL option can be added later without breaking this API. — *Owner: Jesus*
- [ ] Q4. Is `identity_resolver` the right shape, or would you rather expose `identity()` as an overridable seam only (status quo, subclassing)? Proposed: the kwarg, because it removes a subclass FieldSync has to maintain against private details. — *Owner: Jesus*
- [ ] Q5. Release number and whether this rides with `1.3.x` or `1.4.0`. Not blocking (it is additive and defaults to today's behaviour). — *Owner: Jesus*

---

## 9. Design Research Cross-Check

Skipped: no accepted exploration document (this lifts an already-built, already-reviewed FieldSync component; the reference implementation is the design).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-25 | Juan Ruffato | Initial draft, for Jesus's approval |
