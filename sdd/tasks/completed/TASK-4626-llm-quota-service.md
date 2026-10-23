# TASK-4626: `services/llm_quota.py` — sliding-window LLM quota behind a Protocol

**Feature**: FEAT-728 — FormBuilder LLM-validation enforcement policy + LLM quota
**Spec**: `sdd/specs/formbuilder-llm-validation-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Public forms register five auth-exempt URLs
(`services/public_forms.py:13-52`), two of which reach the LLM: `/validate`
with the `llm_validation` opt-in, and `/data`, where the plausibility check
needs no opt-in at all. Neither has a quota, and there is no rate-limit
facility anywhere in `parrot_formdesigner` to reuse. This task builds that
facility as standalone, dependency-free code; TASK-4627 wires it in and closes
the ledger issue.

The backend is a `Protocol` from day one so a shared (Redis) limiter can replace
the in-process one later without respecifying the call sites.

---

## Scope

- Create `services/llm_quota.py` with `QuotaDecision`, the `LLMQuotaBackend`
  Protocol, `InProcessSlidingWindow` and `LLMQuota`.
- Key every charge on `{tenant}:{form_uid}:{identity}`, with `identity` =
  authenticated user id when a navigator session exists, else the client IP.
- Bound the key map with LRU eviction; use a monotonic clock.
- Write unit tests driving the clock by hand (no `sleep`).

**NOT in scope**: wiring it into handlers or `setup_form_api` (TASK-4627 — it
also closes the ledger issue); a Redis backend (spec Non-Goal); any change to
the plausibility checker or the gate.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py` | CREATE | `QuotaDecision`, `LLMQuotaBackend`, `InProcessSlidingWindow`, `LLMQuota` |
| `packages/parrot-formdesigner/tests/unit/services/test_llm_quota.py` | CREATE | Window, eviction, identity and disabled-mode tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from aiohttp import web
# aiohttp is a hard dependency of this package (verified: api/handlers.py:1 region imports `from aiohttp import web`)
# test side:
from parrot_formdesigner.services.llm_quota import (
    InProcessSlidingWindow,
    LLMQuota,
    QuotaDecision,
)
```

### Existing Signatures to Use

```python
# How a navigator session is detected in this package — the ONLY verified way:
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:576-580
    session_id: str | None = None
    if "session" in request:              # line 577
        _sid = request["session"].get("id")
        session_id = str(_sid) if _sid else None

# Public-form URLs are auth-exempt, so an anonymous request has NO session:
# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py:13
def public_form_paths(form_uid: str, tenant: str, base_path: str = "/api/v1") -> list[str]:
    """… five globs: the form, /schema, /render/*, /data, /validate."""

# Prior art for an in-process sliding window (pattern only — DO NOT import it):
# packages/ai-parrot-server/src/parrot/handlers/voice_broadcast.py:149
class _RateLimiter: ...
```

### Does NOT Exist

- ~~`parrot_formdesigner.services.rate_limit`~~ / ~~`.throttle`~~ — there is no
  rate-limit module in this package. THIS task creates the first one.
- ~~`from parrot.handlers.voice_broadcast import _RateLimiter`~~ — it exists but
  is private and lives in another distribution (`ai-parrot-server`). Importing
  it would create a cross-distribution dependency. Copy the *pattern*, not the
  code.
- ~~`AuthContext.user_id`~~ / ~~`.is_authenticated`~~ — `AuthContext` carries
  outbound credentials only (`services/auth_context.py:40-44`).
- ~~`request.user`~~ / ~~`request["user"].id`~~ — not a verified accessor in
  this package; use `request["session"]` as shown above.
- ~~`aiolimiter`~~ / ~~`limits`~~ / ~~`slowapi`~~ — no new dependency is
  permitted (spec §7 External Dependencies: none).
- ~~`LLMValidationConfig.quota_limit`~~ — the quota is NEVER read from form
  schema (spec AC14); a tenant must not be able to raise its own limit.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py",
      "action": "CREATE"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/services/test_llm_quota.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- **Monotonic clock only** (`time.monotonic()`): a wall-clock jump must not
  grant or deny quota. Make the clock injectable so tests advance it by hand —
  no `asyncio.sleep` in tests.
- **Bounded keys.** Anonymous identities are attacker-chosen, so the key map is
  itself an attack surface: `OrderedDict` + `move_to_end` + eviction at
  `max_keys` (spec AC13 and §7).
- **`trust_forwarded_for` defaults to `False`.** Trusting a client-settable
  header by default would let an attacker mint unlimited identities; leaving it
  off means that behind a proxy all anonymous callers share one bucket. Both
  directions are documented in §7 — do not "improve" the default.
- **Never raise.** `acquire()` returns a decision; the caller chooses the HTTP
  consequence. A backend failure must degrade to `allowed=True` with a warning,
  never a 500 on the submit path.
- Async throughout; one `asyncio.Lock` guarding the window map.
- `enabled=False` short-circuits before any key work.

### References in Codebase

- `packages/ai-parrot-server/src/parrot/handlers/voice_broadcast.py:149` —
  in-process sliding window shape (pattern reference only).
- `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:576-580`
  — session detection.

---

## Implementation Blueprint

### Steps (in order)

1. Write the models and the Protocol first — *why*: TASK-4627 codes against
   `QuotaDecision` and `LLMQuota.acquire`, so the surface must be final before
   the wiring task starts.
2. Implement `InProcessSlidingWindow` with an injectable clock — *why*: the
   tests for the window boundary are only honest if they control time.
3. Implement `LLMQuota` (identity resolution + key building) — *why*: keeping
   identity policy here, not in handlers, is what lets both call sites charge
   identically.
4. Write the unit tests — *why*: eviction and the window boundary are exactly
   the parts a later refactor would silently break.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py` (CREATE)

```python
"""Server-side quota for LLM-backed form calls (FEAT-728).

Public forms expose ``/validate`` and ``/data`` without authentication
(services/public_forms.py:13), and both can reach the LLM plausibility
checker. This module bounds those calls per identity and form. It is never
configured from form schema — a tenant must not be able to raise its own
limit (spec AC14).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Callable, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from aiohttp import web

__all__ = ["LLMQuota", "LLMQuotaBackend", "InProcessSlidingWindow", "QuotaDecision"]

logger = logging.getLogger(__name__)


class QuotaDecision(BaseModel):
    """One limiter answer."""

    allowed: bool
    retry_after_s: int = Field(default=0, ge=0)


class LLMQuotaBackend(Protocol):
    """Swap-in point for a shared limiter (e.g. Redis) — see spec §8 Q2."""

    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
        """Charge one call to ``key``; return whether it is allowed."""
        ...


class InProcessSlidingWindow:
    """Per-key sliding window on a monotonic clock, bounded by LRU eviction.

    Per-worker state: with N gunicorn workers the effective limit is N times
    the configured one (spec §7). ``max_keys`` caps adversarial key growth
    from anonymous IPs; the least-recently-used key is evicted at the cap.
    """

    def __init__(self, *, max_keys: int = 4096, clock: Callable[[], float] | None = None) -> None:
        self._max_keys = max_keys
        self._clock = clock or time.monotonic
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
        """Charge one call to ``key``.

        Returns ``allowed=False`` with the seconds until the oldest hit in the
        window expires (always >= 1 when denied, so ``Retry-After`` is useful).
        """
        now = self._clock()
        async with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
            self._hits.move_to_end(key)
            # FILL IN: prune hits older than `now - window_s`, then either append `now`
            #          and allow, or compute retry_after_s from hits[0] and deny
            #          — bounded by AC12/AC13 (denied => retry_after_s >= 1)
            # FILL IN: evict the least-recently-used key while len(self._hits) > self._max_keys
            #          — bounded by AC13
            raise NotImplementedError


class LLMQuota:
    """Quota for LLM-backed form calls, keyed by ``{tenant}:{form_uid}:{identity}``."""

    def __init__(
        self,
        backend: LLMQuotaBackend | None = None,
        *,
        enabled: bool = True,
        limit: int = 10,
        window_s: float = 60.0,
        trust_forwarded_for: bool = False,
    ) -> None:
        self.backend: LLMQuotaBackend = backend or InProcessSlidingWindow()
        self.enabled = enabled
        self.limit = limit
        self.window_s = window_s
        self.trust_forwarded_for = trust_forwarded_for
        self.logger = logging.getLogger(__name__)

    def identity(self, request: "web.Request") -> str:
        """The caller's quota identity.

        The authenticated user id when navigator populated a session
        (verified: api/handlers.py:576-580), else the client IP —
        ``X-Forwarded-For``'s first hop only when ``trust_forwarded_for`` is on,
        because that header is client-settable.
        """
        # FILL IN: session id first, then forwarded-for (guarded), then request.remote,
        #          then the literal "anonymous" when everything is None
        #          — bounded by AC12 and §7 "Proxies collapse identities"
        raise NotImplementedError

    async def acquire(self, request: "web.Request", *, tenant: str | None, form_uid: str) -> QuotaDecision:
        """Charge one LLM call. Always allows when ``enabled`` is False.

        Never raises: a backend failure is logged and allowed, because a limiter
        outage must not take the submit path down with it.
        """
        if not self.enabled:
            return QuotaDecision(allowed=True)
        key = f"{tenant or '-'}:{form_uid}:{self.identity(request)}"
        try:
            return await self.backend.acquire(key, limit=self.limit, window_s=self.window_s)
        except Exception as exc:  # noqa: BLE001 — a limiter outage must not break submissions
            self.logger.warning("LLM quota backend failed (%s); allowing the call", type(exc).__name__)
            return QuotaDecision(allowed=True)
```

**Why this shape**: `LLMQuota` owns *policy* (identity, key shape, failure
mode) and the backend owns *counting*, which is what makes the Redis swap a
one-class change later. The broad `except` is deliberate and narrow in effect —
it logs an exception type and allows; never widen it to swallow the decision
itself. `identity()` is sync because it only reads the request.

### `packages/parrot-formdesigner/tests/unit/services/test_llm_quota.py` (CREATE)

```python
"""Unit tests for the LLM quota (FEAT-728, TASK-4626)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from parrot_formdesigner.services.llm_quota import InProcessSlidingWindow, LLMQuota, QuotaDecision


class FakeClock:
    """Monotonic clock the tests advance by hand — no sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _request(*, session: dict | None = None, remote: str = "203.0.113.7", headers: dict | None = None) -> MagicMock:
    """MagicMock request shaped like the public-form path (no session by default)."""
    # FILL IN: build a MagicMock supporting `"session" in request`, request["session"],
    #          request.remote and request.headers — mirror tests/formdesigner/test_http_plausibility.py::_request


class TestSlidingWindow:
    async def test_allows_under_limit(self) -> None:
        # FILL IN: `limit` consecutive acquires allowed — bounded by AC12

    async def test_denies_over_limit_with_retry_after(self) -> None:
        # FILL IN: the limit+1-th is denied with retry_after_s >= 1 — bounded by AC12

    async def test_window_slides(self) -> None:
        # FILL IN: advance past window_s -> allowed again — bounded by AC13 (monotonic clock)

    async def test_keys_are_independent(self) -> None:
        # FILL IN: two keys do not share a budget — bounded by AC12

    async def test_evicts_lru_at_max_keys(self) -> None:
        # FILL IN: max_keys=2, three keys -> map never exceeds 2 — bounded by AC13


class TestIdentity:
    def test_prefers_session_user(self) -> None:
        # FILL IN — bounded by AC12

    def test_falls_back_to_remote(self) -> None:
        # FILL IN: no session -> request.remote — bounded by AC12

    def test_ignores_forwarded_for_by_default(self) -> None:
        # FILL IN: X-Forwarded-For present, trust_forwarded_for=False -> remote wins — §7

    def test_uses_forwarded_for_when_trusted(self) -> None:
        # FILL IN: first hop only — §7


class TestQuotaPolicy:
    async def test_disabled_always_allows(self) -> None:
        # FILL IN: enabled=False never touches the backend — bounded by AC12

    async def test_key_includes_tenant_and_form(self) -> None:
        # FILL IN: a recording fake backend sees "{tenant}:{form_uid}:{identity}" — AC12

    async def test_backend_failure_allows(self) -> None:
        # FILL IN: a backend raising -> allowed=True, warning logged — bounded by §7
```

**Why this shape**: the `FakeClock` is the whole reason these tests are fast and
deterministic; a test that calls `asyncio.sleep` to cross the window is a defect.
`_request` must mirror the MagicMock shape already used in
`tests/formdesigner/test_http_plausibility.py` so TASK-4627 can reuse it.

### FILL IN checklist

- [ ] `llm_quota.py::InProcessSlidingWindow.acquire` — prune/append/deny + LRU eviction; bounded by AC12/AC13
- [ ] `llm_quota.py::LLMQuota.identity` — session → (guarded) forwarded-for → `request.remote` → `"anonymous"`; bounded by AC12 and §7
- [ ] `test_llm_quota.py::_request` — MagicMock shape mirroring the existing HTTP tests
- [ ] `test_llm_quota.py::*` — 12 bodies; bounded by AC12, AC13 and §7's proxy note

---

## Acceptance Criteria

- [ ] `InProcessSlidingWindow` allows `limit` calls per `window_s` per key, denies the next with `retry_after_s >= 1`, and re-allows once the window slides (spec AC12/AC13).
- [ ] The key map never holds more than `max_keys` keys; eviction is least-recently-used (spec AC13).
- [ ] The clock is monotonic and injectable; no test sleeps.
- [ ] `LLMQuota.identity()` prefers the navigator session user id, then `request.remote`, and reads `X-Forwarded-For` only when `trust_forwarded_for=True`.
- [ ] `LLMQuota.acquire()` keys on `{tenant}:{form_uid}:{identity}`, returns `allowed=True` when `enabled=False`, and never raises — a backend failure logs a warning and allows (spec AC12/AC14).
- [ ] Nothing in the module reads `FormSchema` or `LLMValidationConfig` (spec AC14).
- [ ] No new third-party dependency is added.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py packages/parrot-formdesigner/tests/unit/services/test_llm_quota.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/services/test_llm_quota.py -q`

---

## Test Specification

See the CREATE block above. Every timing test drives `FakeClock`; a
`asyncio.sleep`-based test is a defect, not a slow test.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug formbuilder-llm-validation-enforcement --feature-id FEAT-728`)
2. **Read the spec** at the path listed above (§3 Module 4, §7 Known Risks)
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — confirm `api/handlers.py:576-580` still
   detects the session as documented before you copy the pattern.
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`. Tests inside a
   worktree need `PYTHONPATH=packages/parrot-formdesigner/src`.
7. **Verify** the Validation Commands pass
8. **Commit the code** — stage only the two files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4626 formbuilder-llm-validation-enforcement verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Delivered by seat glm (nova, zai.glm-4.7-flash), 1 attempt, 211s. Merge-tier validation green (189 passed). Review found retry_after_s ignored window_s; fixed in fa18c0e96de9ce5acbf3a317efc267721f18b37a with an exact-value test. Feedback: coder-feedback:6d0d1fcc75d81293964b0da2. Review: coder-review:489283f0d5b1194ddbec3134.
