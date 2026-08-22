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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
