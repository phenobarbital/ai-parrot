# TASK-2324: Close the streaming auth bypasses (`stream.py`, `user.py`)

**Feature**: FEAT-446 — SaaS Auth Hardening (S0 of Parrot Research Cloud)
**Spec**: `sdd/specs/saas-auth-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2320
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / Goal G4. `StreamHandler` appends its four routes to
navigator-auth's `exclude_list`, making every bot stream anonymous;
`UserSocketManager` does the same for its `/ws/user` prefix. Files are
disjoint from TASK-2322/2323, so this can proceed right after TASK-2320.

---

## Scope

- `handlers/stream.py`: delete the four `exclude_list.append(...)` calls
  (lines 385, 388, 391, 394), keeping the adjacent route registrations
  (386, 389, 392, 395). The navigator-auth middleware then enforces
  authentication on `/bots/{bot_id}/stream/{sse,ndjson,chunked,ws}`.
- Verify the four stream methods obtain the session/user after the change
  (they may currently assume anonymity); add an authenticated-session read
  where needed so the stream knows its principal.
- `handlers/user.py`: make `exclude_list.append(route_prefix)` (line 82)
  conditional — executed only when `PARROT_SAAS_MODE` is false (flag-gated
  exclusion per spec §7 "WS auth" gotcha; first-class WS auth is deferred,
  spec §8 open question).
- Unit tests: exclusion list state under both flag values; stream route
  registration unchanged.

**NOT in scope**: the other exclude_list sites — `orchestrator.py:363-365`
(`/autonomous/admin`), `mcp/parrot_server.py:219-222`, `services/whatsapp.py:1334-1337`,
and app.py's `/a2a`, `/.well-known/*`, `/api/messages`, `/api/msagentsdk/*`
excludes are intentionally self-managed schemes (spec §1 Non-Goals). Do NOT
touch them. First-class WebSocket token auth (S1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/stream.py` | MODIFY | remove 4 excludes |
| `packages/ai-parrot-server/src/parrot/handlers/user.py` | MODIFY | flag-gate exclude |
| `packages/ai-parrot-server/tests/unit/test_stream_auth.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_auth.conf import exclude_list   # stream.py:7, user.py:20
from parrot.conf import PARROT_SAAS_MODE       # created by TASK-2320
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/stream.py — the block to edit
exclude_list.append('/bots/*/stream/sse')                              # line 385  ← delete
app.router.add_post('/bots/{bot_id}/stream/sse', self.stream_sse)      # line 386  ← keep
exclude_list.append('/bots/*/stream/ndjson')                           # line 388  ← delete
app.router.add_post('/bots/{bot_id}/stream/ndjson', self.stream_ndjson)# line 389  ← keep
exclude_list.append('/bots/*/stream/chunked')                          # line 391  ← delete
app.router.add_post('/bots/{bot_id}/stream/chunked', self.stream_chunked) # 392   ← keep
exclude_list.append('/bots/*/stream/ws')                               # line 394  ← delete
app.router.add_get('/bots/{bot_id}/stream/ws', self.stream_websocket)  # line 395  ← keep

# packages/ai-parrot-server/src/parrot/handlers/user.py
class UserSocketManager(...):
    def __init__(self, ..., route_prefix: str = '/ws/user', ...):      # line 67
        exclude_list.append(route_prefix)                              # line 82  ← flag-gate

# navigator-auth middleware enforcement (why deleting the exclude closes the route):
# .venv/.../navigator_auth/middlewares/abstract.py:85 raises web.HTTPUnauthorized
```

### Does NOT Exist
- ~~`PARROT_SAAS_MODE`~~ until TASK-2320 merges — verify first.
- ~~`@is_authenticated` on StreamHandler methods~~ — enforcement here comes
  from removing the exclusion (middleware), matching the spec's design; add
  the decorator ONLY if the integration test in TASK-2325 shows the
  middleware alone does not reject anonymous callers.
- ~~`/ws/userinfo`~~ — the real prefix is `/ws/user` (user.py:67).
- ~~`StreamHandler` in navigator-auth's own excludes~~ — the appends in
  stream.py are the only source.

---

## Implementation Notes

### Key Constraints
- **Breaking change by design** for anonymous stream consumers (spec §7).
- Keep the route paths and handler methods byte-identical — only the
  exclusion behavior changes.
- The `user.py` gate reads the flag at setup time; document in the docstring
  that `/ws/user` remains open in legacy mode and closed in SaaS mode.
- Wildcard exclude patterns (`/bots/*/stream/sse`) belong to navigator-auth's
  matcher — when writing tests, assert against `exclude_list` contents, not
  route behavior (route behavior is TASK-2325's integration suite).

### References in Codebase
- `orchestrator.py:363-365` — the conditional-append pattern
  (`if path not in exclude_list`) to mirror for the user.py gate

---

## Acceptance Criteria

- [ ] grep shows zero `exclude_list.append('/bots/` in stream.py
- [ ] `/ws/user` excluded only when `PARROT_SAAS_MODE=false` (unit test both ways)
- [ ] Stream route registrations unchanged (4 routes still registered)
- [ ] `pytest packages/ai-parrot-server/tests/unit/test_stream_auth.py -v` green
- [ ] `ruff check` clean on touched files

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_stream_auth.py
class TestStreamExclusions:
    def test_no_stream_excludes_after_setup(self): ...
    def test_ws_user_excluded_legacy(self, monkeypatch): ...
    def test_ws_user_not_excluded_saas(self, monkeypatch): ...
    def test_stream_routes_still_registered(self): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2320 completed; 3. re-verify contract;
4. index → `"in-progress"`; 5. implement; 6. verify; 7. move to
   `sdd/tasks/completed/`; 8. index → `"done"`; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Removed all four `exclude_list.append('/bots/*/stream/...')`
calls from `handlers/stream.py::configure_routes` (the now-unused
`from navigator_auth.conf import exclude_list` import was also removed);
kept the four route registrations byte-identical (verified via a live
`app.router.routes()` dump — all 4 routes still registered, same
methods/paths). Did NOT add `@is_authenticated()` or any session/user
read inside the four stream methods (`stream_sse`, `stream_ndjson`,
`stream_chunked`, `stream_websocket`) — none of them currently use the
caller's identity for any logic (they only read `bot_id` from the URL
and `prompt`/kwargs from the body), and the task's own "Does NOT Exist"
list says to add the decorator "ONLY if the integration test in
TASK-2325 shows the middleware alone does not reject anonymous callers."
Enforcement now comes entirely from navigator-auth's middleware once the
route is no longer excluded (verified against
`navigator_auth/middlewares/abstract.py:85`, which raises
`web.HTTPUnauthorized`). Left this in place for TASK-2325 to prove/
adjust with its integration suite rather than pre-emptively guessing at
per-stream session-read requirements.
`handlers/user.py::UserSocketManager.__init__`: `exclude_list.append(
route_prefix)` is now gated behind
`if not PARROT_SAAS_MODE and route_prefix not in exclude_list:`, mirroring
the conditional-append pattern at `autonomous/orchestrator.py:363-365`.
`PARROT_SAAS_MODE` is imported lazily inside `__init__` (not at module
top) so tests can `monkeypatch.setattr(parrot.conf, "PARROT_SAAS_MODE",
...)` before constructing the manager and have it observed immediately —
same pattern as TASK-2322's `_saas_mode()` indirection.
`pytest packages/ai-parrot-server/tests/unit/test_stream_auth.py -v` —
4 passed (all from the Test Specification). Tests assert against
`exclude_list` contents (never route behavior), per the Key Constraint,
using an autouse fixture that snapshots/restores the shared, mutable
`exclude_list` around each test to avoid cross-test pollution.
Ruff: before/after diff against `dev` — stream.py flat at 14 errors
(pre-existing, untouched by my edits); user.py flat at 59 (one
transient new `RUF100` from a `# noqa: PLC0415` I added and then removed
since that check isn't enabled in this project's ruff config); new test
file clean after `ruff check --fix`.
Confirmed NOT touched (per "NOT in scope"):
`autonomous/orchestrator.py:363-365` (`/autonomous/admin`),
`mcp/parrot_server.py` excludes, `services/whatsapp.py` excludes, and
app.py's `/a2a`, `/.well-known/*`, `/api/messages`, `/api/msagentsdk/*`
excludes — grep-verified zero changes to any of those files.

**Deviations from spec**: none — the "verify the four stream methods
obtain session/user... add a read where needed" scope note was
evaluated and found not-needed (no current logic depends on caller
identity); documented above rather than adding speculative code.

---

### Addendum (post-implementation code-review, before push)

The FEAT-446 adversarial code review flagged (🟠 IMPORTANT, "plausible
rather than proven") that closing `stream_websocket()`'s exclude-list
entry might have made its pre-existing `Sec-WebSocket-Protocol: jwt,
<token>` auth convention unreachable — added specifically because
browsers can't set custom headers (e.g. `Authorization`) on a WS
upgrade request. **Verified TRUE**, not just plausible: traced
navigator-auth's `auth_middleware`/`verify_exceptions`
(`.venv/.../navigator_auth/auth.py:833-1040`) and `IdP.get_payload()`
(`backends/idp/__init__.py:255`) — the global middleware only reads
the `Authorization` header or a session cookie; it has zero awareness
of `Sec-WebSocket-Protocol`. Wrote a probe test confirming a WS request
carrying ONLY a valid subprotocol JWT (no cookie, no Authorization
header) got `401` before this fix — a genuine regression this task's
own exclude-list removal introduced for that one auth path (browser
clients with an existing session cookie were unaffected, since cookies
ARE sent automatically on same-origin WS upgrades).

Fixed with a new `_ws_subprotocol_preauth_middleware` on
`StreamHandler`, registered via `app.middlewares.insert(0, ...)` in
`configure_routes()` (guaranteed to run before navigator-auth's
`auth_middleware` regardless of `AuthHandler.setup()` call order,
since that method only ever *appends*). For the WS route only, it
validates the subprotocol token with the exact check
`stream_websocket()` already performed, and on success sets
`request["authenticated"] = True` — the same signal navigator-auth's
own `verify_exceptions()` already treats as "skip my check," so no
navigator-auth internals were touched. Verified with 4 new integration
tests in `test_saas_auth_hardening.py::TestWsSubprotocolPreauth`: valid
subprotocol-only token now passes (no longer 401); no credentials at
all still 401; an invalid subprotocol token still 401; other routes
(e.g. `/stream/sse`) are unaffected by a stray subprotocol header.
Ruff flat at 14 (dev baseline), zero new lint debt.
