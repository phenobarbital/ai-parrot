# TASK-2138: `WorkdayRestClient` — REST `/ccx/api` client on aiohttp

**Feature**: FEAT-415 — Workday Interfaces Homologation (flowtask → ai-parrot)
**Spec**: `sdd/specs/workday-interfaces-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2136
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec. `rest.py` is the single largest gap:
217 lines that exist in flowtask and are **entirely absent** from ai-parrot.

It matters because the WSDL services have **no operation** to read raw time
clock events. Workday's REST API does — and it echoes back the
client-assigned `Time_Clock_Event_ID` as `reference_ID` plus the effective
`timeEntryCode` applied to *In* events. Without this client, an agent can
write a punch but cannot verify it landed.

flowtask's version is built on `httpx`. `CLAUDE.md` forbids `httpx` and
`requests` and mandates `aiohttp`, and `httpx` is not a declared dependency
of `ai-parrot-tools` (it is only present transitively via `httpx-sse`).
So this is a **reimplementation preserving the public surface**, not a copy.

---

## Scope

- Create `rest.py` with `WorkdayRestClient`, built on `aiohttp`.
- Preserve the public surface exactly: `__init__(*, config, timeout,
  time_tracking_version)`, `base_url` property, `set_token`, `get_token`,
  `get`, `find_worker`, `get_time_clock_events`, `find_time_clock_event`.
- Add an explicit `close()` for session lifecycle (see constraints).
- OAuth **refresh-token** grant, same as `SOAPClient` — bearer token cached
  **in memory** until shortly before expiry. No Redis dependency.
- Share `WorkdayConfig` so the TASK-2136 environment selector applies to
  REST as well as SOAP (host and credentials come from the config).
- Surface the WID-required constraint as an actionable error: the
  `timeTracking` `worker` parameter requires a Workday **WID**; Employee_ID
  values are rejected by Workday with `400 "not found"`.
- On a 401 despite a cached token, re-authenticate **exactly once** — never
  an unbounded retry loop.
- Write unit tests with a mocked aiohttp session (no network).

**NOT in scope**:
- Exposing any of this as an agent-facing tool in `parrot_tools/workday/tool.py`.
- The `workday` pyproject extra — TASK-2144.
- The manual smoke script — TASK-2144.
- Any SOAP handler/model change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/rest.py` | CREATE | `WorkdayRestClient` on aiohttp |
| `packages/ai-parrot-tools/tests/workday/test_rest_client.py` | CREATE | Unit tests with a mocked aiohttp session |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import aiohttp                                    # MANDATED — never httpx/requests
from parrot_tools.interfaces.workday.config import WorkdayConfig  # verified: config.py:112
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/config.py
class WorkdayConfig(BaseModel):                    # line 112
    timeout: int = 300                             # line 138
    def resolved_client_id(self) -> str | None:    # line 146
    def resolved_client_secret(self) -> str | None:# line 152
    def resolved_token_url(self) -> str | None:    # line 158
    def resolved_refresh_token(self) -> str | None:# line 164
    def resolved_tenant(self) -> str | None:       # line 182
    def resolved_workday_url(self) -> str | None:  # line 194
    # ADDED BY TASK-2136 (dependency):
    #   env / resolved_env / resolved_is_sandbox
```

### Reference Source (flowtask — READ ONLY, httpx-based)

`../flowtask/flowtask/interfaces/workday/rest.py` — port the **surface and
semantics**, replace the transport:

```python
class WorkdayRestClient:                                                        # line 41
    def __init__(self, *, config=None, timeout=30, time_tracking_version="v5")  # line 58
    def base_url(self) -> str:                                                  # line 77
    def set_token(self, token: str, expires_in: int = 300) -> None:             # line 81
    async def get_token(self) -> str:                                           # line 91
    async def get(self, path, params=None) -> dict:                             # line 129
    async def find_worker(self, search: str, *, limit: int = 20) -> list[dict]: # line 157
    async def get_time_clock_events(...)                                        # line 174
    async def find_time_clock_event(...)                                        # line 199
```

Endpoints verified against a Workday implementation tenant (2026-07-03):
- `GET /ccx/api/v1/{tenant}/workers?search={text}` — rows carry `id` (the WID) and `descriptor`
- `GET /ccx/api/timeTracking/v5/{tenant}/timeClockEvents?worker={WID}` — raw clock events

`v6` of the timeTracking service returned 400 when probed; default to `v5`.

### Does NOT Exist

- ~~`parrot_tools/interfaces/workday/rest.py`~~ — **CREATE it**; there is nothing to edit
- ~~`parrot_tools.interfaces.workday.WorkdayRestClient`~~ — not exported anywhere yet
- ~~`httpx` as a declared dependency of `ai-parrot-tools`~~ — NOT declared (only transitive via `httpx-sse`). **Do not import httpx.**
- ~~a `workday` extra in `packages/ai-parrot-tools/pyproject.toml`~~ — added by TASK-2144, not this task
- ~~`SOAPClient._get_bearer_token` reuse for REST~~ — `SOAPClient` (`soap.py:171`) has its own token logic tied to the Zeep transport; do NOT try to share its instance. Implement the grant independently against `resolved_token_url`.
- ~~a Redis token cache~~ — flowtask's REST client deliberately avoids Redis; keep the in-memory cache

---

## Implementation Notes

### Key Constraints
- **`aiohttp` only.** An acceptance criterion greps for `httpx` in this file.
- **Session lifecycle**: `httpx` used `async with httpx.AsyncClient(...)` per request (flowtask `rest.py:106,144`). A naive port to `aiohttp` that creates a `ClientSession` per request is wasteful and leak-prone. Either create the session lazily and close it in `close()`, or use a short-lived `async with aiohttp.ClientSession()` per request — but whichever you choose, `close()` must leave no unclosed session and the tests must prove it.
- Token cache is in-memory, refreshed shortly before expiry; a 401 with a cached token triggers exactly ONE re-auth.
- Async throughout; no blocking I/O.
- Pydantic is not required for the raw dict returns — preserve flowtask's `list[dict]` / `dict` shapes so callers port cleanly.
- Google-style docstrings + strict type hints; module logger, never `print`.

### References in Codebase
- `packages/ai-parrot/src/parrot/interfaces/soap.py:171` — `_get_bearer_token()` shows the refresh-token grant shape used elsewhere in the project
- `packages/ai-parrot-tools/tests/workday/test_homologation_read.py` — `AsyncMock`/`MagicMock` fixture patterns

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/rest.py` exists with the full public surface listed above
- [ ] `from parrot_tools.interfaces.workday.rest import WorkdayRestClient` works
- [ ] `grep -n "httpx\|requests" packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/rest.py` returns nothing
- [ ] `get_token()` reuses the cached bearer and refreshes shortly before expiry
- [ ] A 401 with a cached token triggers exactly one re-authentication
- [ ] `find_worker()` returns rows carrying `id` (WID) and `descriptor`
- [ ] Passing an Employee_ID where a WID is required surfaces an actionable error, not an opaque 400
- [ ] `close()` leaves no unclosed aiohttp session
- [ ] The client honours the TASK-2136 environment selector (sandbox host/credentials)
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/workday/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/rest.py`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/workday/test_rest_client.py
import pytest
from parrot_tools.interfaces.workday.rest import WorkdayRestClient


class TestTokenHandling:
    async def test_token_cached_until_expiry(self):
        """Second call reuses the cached bearer — no second token request."""

    async def test_token_refreshed_before_expiry(self):
        """Token near expiry triggers a refresh."""

    async def test_401_reauthenticates_exactly_once(self):
        """A 401 despite a cached token re-auths once, not in a loop."""


class TestEndpoints:
    async def test_find_worker_returns_wid_rows(self):
        """Rows carry id (WID) and descriptor."""

    async def test_time_clock_events_requires_wid(self):
        """Employee_ID input surfaces an actionable error, not a raw 400."""

    async def test_find_time_clock_event_matches_reference_id(self):
        """Locates the event whose reference_ID matches the client-assigned id."""


class TestLifecycle:
    async def test_close_leaves_no_open_session(self):
        """No unclosed aiohttp session after close()."""

    def test_module_does_not_import_httpx(self):
        import parrot_tools.interfaces.workday.rest as mod
        src = open(mod.__file__).read()
        assert "httpx" not in src and "requests" not in src
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2136 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/workday-interfaces-homologation.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-2138-workday-rest-client-aiohttp.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-05
**Notes**: Created `rest.py` — `WorkdayRestClient` reimplemented on `aiohttp`
(never `httpx`/`requests`, incl. in comments/docstrings — verified by grep
and a dedicated test) preserving flowtask's public surface verbatim:
`__init__(*, config, timeout, time_tracking_version)`, `base_url`,
`set_token`, `get_token`, `get`, `find_worker`, `get_time_clock_events`,
`find_time_clock_event`, plus explicit `close()`. Session is lazily created
and reused (`_ensure_session`); `close()` closes and clears it. Token is
cached in-memory (`time.monotonic()`-based expiry, no Redis); a `401`
despite a cached token clears the cache and re-authenticates exactly once
before retrying the request. `get_time_clock_events` catches
`aiohttp.ClientResponseError(status=400)` and re-raises a new
`WorkdayRestError` naming the WID requirement, so an Employee_ID misuse is
actionable instead of an opaque 400.

Two deliberate adaptations beyond a literal flowtask port, both required by
ai-parrot's vendor-neutral `WorkdayConfig` (`tenant`/`workday_url` default to
`None`, unlike flowtask's hardcoded defaults): `base_url` uses
`resolved_workday_url` (conf-resolved fallback) instead of the raw
`workday_url` field, and both endpoint methods use `resolved_tenant` instead
of the raw `tenant` field. Without these, an all-defaults `WorkdayConfig()`
would crash on `.rstrip()`/`None` string formatting.

23 new tests (`test_rest_client.py`) using `pytest-aiohttp`'s `aiohttp_server`
fixture against a real local server (no network, no hand-rolled async
context-manager mocks) — covers token caching/refresh/401-retry-once, all
three endpoints, session lifecycle, the `httpx`/`requests`-absence check, and
the TASK-2136 environment-selector integration. Full `tests/workday/` suite
(95 tests) passes; `ruff check` clean.

**Deviations from spec**: `get_time_clock_events` additionally accepts
`**criteria: Any` (matching the spec's §2 `New Public Interfaces` signature
listing, which differs slightly from the task's own Codebase Contract
excerpt of the flowtask source) so callers can forward extra query
parameters; `limit` is still explicit and defaulted as flowtask has it.
